"""ROZLF-EO-BRIDGE: read-only ExpertOption prices and candles over HTTPS."""
from __future__ import annotations

import contextlib
import hmac
import os
import logging
import time as _time
from typing import Any

from aiohttp import web

from .catalog import Instrument, find_smarty, resolve, timeframe_seconds
from .eo_client import BridgeError, ExpertOptionClient
from .settings import BridgeSettings

logger = logging.getLogger("eo_bridge.api")

SERVICE = "ROZLF-EO-BRIDGE"


def _json(payload: dict[str, Any], status: int = 200) -> web.Response:
    return web.json_response(payload, status=status)


def _error(code: str, message: str, status: int = 503) -> web.Response:
    return _json({"error": code, "message": message}, status=status)


def _requested_symbol(value: str) -> str:
    return (value or "").upper().replace("/", "").strip()


class BridgeApp:
    def __init__(self, settings: BridgeSettings, client: ExpertOptionClient | None = None) -> None:
        self.settings = settings
        self.client = client or ExpertOptionClient(settings)

    # ------------------------------------------------------------------ middleware
    @web.middleware
    async def _auth(self, request: web.Request, handler):
        if request.path in {"/", "/health", "/verify/smarty", "/verify/asset"}:
            return await handler(request)
        supplied = request.headers.get("X-API-Key") or request.query.get("api_key") or ""
        expected = self.settings.api_key or ""
        if not expected or not hmac.compare_digest(supplied, expected):
            return _error("UNAUTHORIZED", "Invalid or missing X-API-Key", status=401)
        return await handler(request)

    # -------------------------------------------------------------------- handlers
    async def index(self, _: web.Request) -> web.Response:
        return _json(
            {
                "service": SERVICE,
                "description": "Read-only ExpertOption market data bridge for ROZLF AI",
                "endpoints": ["/health", "/assets", "/discover", "/smarty", "/quote", "/candles",
                          "/verify/smarty", "/verify/asset"],
                "docs": "https://github.com/ahmzkdljsuwg-oss/ROZLF-AI/tree/main/eo_bridge",
            }
        )

    async def health(self, _: web.Request) -> web.Response:
        status = self.client.status()
        payload = {
            "service": SERVICE,
            "ok": bool(self.settings.configured and status["connected"]),
            "configured": self.settings.configured,
            "region": status["region"],
            "assets": status["assets"],
            "connected": status["connected"],
            "last_message_age_seconds": status["last_message_age_seconds"],
            "last_error": status["last_error"],
            "build": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "unknown")[:7],
            "assets_debug": status.get("assets_debug") or {},
            "seen_actions": status.get("seen_actions") or {},
            "msg_shapes": status.get("msg_shapes") or [],
            "timeframes_payload": status.get("timeframes_payload"),
        }
        return _json(payload, status=200)

    async def assets(self, request: web.Request) -> web.Response:
        market = (request.query.get("market") or "").lower()
        try:
            instruments = await self.client.ensure_assets()
        except BridgeError as exc:
            return _error(exc.code, exc.message)
        if market:
            instruments = [item for item in instruments if item.market == market]
            if market == "smarty" and not instruments:
                return _error(
                    "SMARTY_UNAVAILABLE",
                    "SMRTY (id 240) is not offered on this ExpertOption account right now",
                    status=404,
                )
        return _json(
            {
                "service": SERVICE,
                "market": market or "all",
                "count": len(instruments),
                "assets": [item.as_dict() for item in instruments],
            }
        )

    async def quote(self, request: web.Request) -> web.Response:
        instrument, error = await self._resolve(request)
        if error is not None:
            return error
        assert instrument is not None
        try:
            candle, tf = await self.client.get_quote(instrument)
        except BridgeError as exc:
            return _error(exc.code, exc.message)
        return _json(self._quote_payload(instrument, candle.time, candle.close, tf))

    async def candles(self, request: web.Request) -> web.Response:
        instrument, error = await self._resolve(request)
        if error is not None:
            return error
        assert instrument is not None
        code = request.query.get("timeframe") or "5min"
        seconds = timeframe_seconds(code)
        if seconds is None:
            return _error("BAD_TIMEFRAME", f"Unsupported timeframe '{code}'", status=400)
        try:
            limit = max(10, min(int(request.query.get("limit", 300)), 1500))
        except ValueError:
            limit = 300
        try:
            candles = await self.client.get_candles(instrument, seconds, limit=limit)
        except BridgeError as exc:
            return _error(exc.code, exc.message)
        requested = _requested_symbol(request.query.get("symbol", ""))
        return _json(
            {
                "service": SERVICE,
                "market": instrument.market,
                "symbol": requested,
                "eo_symbol": instrument.symbol,
                "timeframe": code,
                "source": "ExpertOption",
                "candles": [candle.as_dict() for candle in candles],
            }
        )

    async def discover(self, _: web.Request) -> web.Response:
        try:
            instruments = await self.client.ensure_assets()
        except BridgeError as exc:
            return _error(exc.code, exc.message)
        import time as _time

        by_market: dict[str, list[dict[str, Any]]] = {market: [] for market in ("otc", "smarty", "gold", "forex")}
        for item in instruments:
            by_market.setdefault(item.market, []).append(item.as_dict())
        return _json(
            {
                "service": SERVICE,
                "source": "ExpertOption",
                "discovered": True,
                "generated_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
                "counts": {market: len(items) for market, items in by_market.items()},
                "otc_symbols": sorted(item["symbol"] for item in by_market.get("otc", [])),
                "smarty": by_market.get("smarty", []),
                "gold_symbols": sorted(item["symbol"] for item in by_market.get("gold", [])),
            }
        )


    async def verify_smarty(self, _: web.Request) -> web.Response:
        """Unauthenticated liveness probe: proves real SMARTY assets/candles exist.

        Returns metadata only (no token, no keys); a bare last close is included
        so operators can eyeball that the feed is live.
        """
        if not self.settings.eo_token:
            return _error("EO_TOKEN_MISSING", "Bridge has no ExpertOption session token", status=503)
        try:
            instruments = await self.client.ensure_assets()
        except BridgeError as exc:
            return _error(exc.code, exc.message, status=503)
        instrument = find_smarty(instruments)
        if instrument is None:
            candidates = [
                item.as_dict()
                for item in instruments
                if "smart" in f"{item.symbol} {item.name}".lower()
                or "smrty" in f"{item.symbol} {item.name}".lower()
                or 230 <= item.id <= 260
            ]
            counts: dict[str, int] = {}
            for item in instruments:
                counts[item.market] = counts.get(item.market, 0) + 1
            return _json(
                {
                    "error": "SMARTY_UNAVAILABLE",
                    "message": "No asset matched SMRTY/id 240 on this ExpertOption account",
                    "discovered_assets": len(instruments),
                    "market_counts": counts,
                    "candidates": [dict(c) for c in candidates[:20]],
                },
                status=404,
            )
        tested: dict[str, Any] = {}
        for tf in (5, 10, 15, 30, 60, 180, 300, 900):
            try:
                probe = await self.client.get_candles(instrument, tf, limit=200)
            except BridgeError as exc:
                tested[str(tf)] = {"error": exc.code, "detail": str(exc.message)[:200]}
                continue
            tested[str(tf)] = {
                "candles": len(probe),
                "last_candle": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(probe[-1].time)),
                "last_close": probe[-1].close,
            }
        candles = None
        seconds = 60
        for tf in (5, 10, 15, 60, 30, 180, 300, 900):
            if isinstance(tested.get(str(tf)), dict) and "candles" in tested[str(tf)]:
                try:
                    candles = await self.client.get_candles(instrument, tf, limit=200)
                    seconds = tf
                    break
                except BridgeError:
                    continue
        if candles is None:
            return _json(
                {
                    "error": "NO_CANDLES",
                    "message": f"ExpertOption returned no candles for {instrument.symbol}",
                    "asset": instrument.as_dict(),
                    "raw_asset": self.client.raw_asset(instrument.id),
                    "timeframes_tested": tested,
                    "timeframes_payload": self.client.status().get("timeframes_payload"),
                    "candle_debug": self.client.status().get("candle_debug"),
                },
                status=503,
            )
        now = _time.time()
        times = [candle.time for candle in candles]
        invalid = [
            candle for candle in candles
            if not (candle.high >= max(candle.open, candle.close) and candle.low <= min(candle.open, candle.close))
        ]
        stale_seconds = round(max(0.0, now - times[-1]), 1)
        return _json(
            {
                "service": SERVICE,
                "source": "ExpertOption",
                "asset_id": instrument.id,
                "symbol": instrument.symbol,
                "name": instrument.name,
                "market": instrument.market,
                "active": instrument.is_active,
                "expirations": {
                    "step_seconds": self.client.raw_asset(instrument.id).get("expiration_step"),
                    "count": self.client.raw_asset(instrument.id).get("expiration_count"),
                    "max_seconds": self.client.raw_asset(instrument.id).get("expiration_max_seconds"),
                    "purchase_time": self.client.raw_asset(instrument.id).get("purchase_time"),
                },
                "timeframe": f"{seconds}s",
                "timeframes_tested": tested,
                "raw_asset": self.client.raw_asset(instrument.id),
                "candles": len(candles),
                "first_candle": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(times[0])),
                "last_candle": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(times[-1])),
                "stale_seconds": stale_seconds,
                "duplicate_timestamps": len(times) - len(set(times)),
                "future_candles": sum(1 for ts in times if ts > now + 5),
                "invalid_ohlc": len(invalid),
                "last_close": candles[-1].close,
                "candles_ohlc": [
                    {"time": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(c.time)),
                     "open": c.open, "high": c.high, "low": c.low, "close": c.close}
                    for c in candles[-120:]
                ],
                "recent": [
                    {"time": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(c.time)), "close": c.close}
                    for c in candles[-3:]
                ],
                "connected": bool(self.client.connected),
                "last_message_age_seconds": self.client.status().get("last_message_age_seconds"),
                "last_error": self.client.status().get("last_error"),
            }
        )

    async def verify_asset(self, request: web.Request) -> web.Response:
        """Unauthenticated liveness probe for one ExpertOption asset id."""
        if not self.settings.eo_token:
            return _error("EO_TOKEN_MISSING", "Bridge has no ExpertOption session token", status=503)
        try:
            wanted = int(request.query.get("id") or 0)
        except ValueError:
            return _error("BAD_ID", "id must be a number", status=400)
        try:
            instruments = await self.client.ensure_assets()
        except BridgeError as exc:
            return _error(exc.code, exc.message, status=503)
        target = next((item for item in instruments if item.id == wanted), None)
        if target is None:
            near = [
                item.as_dict() for item in instruments
                if "INDEX" in item.symbol or "INDEX" in item.name.upper()
            ]
            return _json(
                {
                    "error": "ASSET_UNAVAILABLE",
                    "message": f"Asset id {wanted} is not offered on this ExpertOption account",
                    "discovered_assets": len(instruments),
                    "index_candidates": near[:40],
                },
                status=404,
            )
        tested: dict[str, Any] = {}
        for tf in (5, 15, 30, 60, 180, 300, 900):
            try:
                probe = await self.client.get_candles(target, tf, limit=120)
            except BridgeError as exc:
                tested[str(tf)] = {"error": exc.code, "detail": str(exc.message)[:160]}
                continue
            tested[str(tf)] = {
                "candles": len(probe),
                "last_close": probe[-1].close,
                "last_candle": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(probe[-1].time)),
            }
        return _json(
            {
                "service": SERVICE,
                "source": "ExpertOption",
                "asset": target.as_dict(),
                "raw_asset": self.client.raw_asset(target.id),
                "timeframes_tested": tested,
                "connected": bool(self.client.connected),
                "last_message_age_seconds": self.client.status().get("last_message_age_seconds"),
                "last_error": self.client.status().get("last_error"),
            }
        )

    async def smarty(self, request: web.Request) -> web.Response:
        if not self.settings.eo_token:
            return _error("EO_TOKEN_MISSING", "Bridge has no ExpertOption session token", status=503)
        try:
            instruments = await self.client.ensure_assets()
        except BridgeError as exc:
            return _error(exc.code, exc.message)
        instrument = find_smarty(instruments)
        if instrument is None:
            return _error(
                "SMARTY_UNAVAILABLE",
                "SMRTY (id 240) is not offered on this ExpertOption account right now",
                status=404,
            )
        if not instrument.is_active:
            return _error("INACTIVE_ASSET", f"{instrument.symbol} is currently closed", status=503)
        code = request.query.get("timeframe") or "1min"
        seconds = timeframe_seconds(code)
        if seconds is None:
            return _error("BAD_TIMEFRAME", f"Unsupported timeframe '{code}'", status=400)
        try:
            limit = max(10, min(int(request.query.get("limit", 120)), 1500))
        except ValueError:
            limit = 120
        try:
            candles = await self.client.get_candles(instrument, seconds, limit=limit)
        except BridgeError as exc:
            return _error(exc.code, exc.message)
        latest = candles[-1]
        stale_seconds = max(0.0, _time.time() - latest.time)
        if stale_seconds > max(120.0, seconds * 3):
            return _error(
                "SMARTY_STALE",
                f"Latest {instrument.symbol} candle is {int(stale_seconds)}s old; no signal from stale data",
                status=503,
            )
        payload = self._quote_payload(instrument, latest.time, latest.close, seconds)
        payload.update(
            {
                "asset_id": instrument.id,
                "asset": instrument.as_dict(),
                "timeframe": code,
                "candles": [candle.as_dict() for candle in candles],
            }
        )
        return _json(payload)

    async def _resolve(self, request: web.Request) -> tuple[Instrument | None, web.Response | None]:
        market = (request.query.get("market") or "").lower()
        symbol = _requested_symbol(request.query.get("symbol", ""))
        if not market or not symbol:
            return None, _error("BAD_REQUEST", "market and symbol are required", status=400)
        if not self.settings.eo_token:
            return None, _error("EO_TOKEN_MISSING", "Bridge has no ExpertOption session token", status=503)
        try:
            instruments = await self.client.ensure_assets()
        except BridgeError as exc:
            return None, _error(exc.code, exc.message)
        instrument = resolve(instruments, market, symbol)
        if instrument is None:
            available = sorted({item.symbol for item in instruments if item.market == market})
            return None, _error(
                "UNSUPPORTED_SYMBOL",
                f"{symbol} is not offered in {market.upper()} on this ExpertOption account"
                + (f"; available: {', '.join(available)}" if available else ""),
                status=404,
            )
        if not instrument.is_active:
            return None, _error("INACTIVE_ASSET", f"{instrument.symbol} is currently closed", status=503)
        return instrument, None

    def _quote_payload(self, instrument: Instrument, timestamp: int, price: float, tf: int) -> dict[str, Any]:
        import time as _time

        from .eo_client import Candle  # noqa: F401  (kept for type clarity)

        return {
            "service": SERVICE,
            "market": instrument.market,
            "symbol": _requested_symbol_name(instrument),
            "eo_symbol": instrument.symbol,
            "bid": price,
            "ask": price,
            "price_type": "last_candle_close",
            "candle_seconds": tf,
            "time": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(timestamp)),
            "source": "ExpertOption",
            "stale_seconds": round(_time.time() - timestamp, 1),
            "precision": instrument.precision,
        }

    # ---------------------------------------------------------------------- setup
    def build(self) -> web.Application:
        app = web.Application(middlewares=[self._auth])
        app["bridge"] = self
        app.router.add_get("/", self.index)
        app.router.add_get("/health", self.health)
        app.router.add_get("/assets", self.assets)
        app.router.add_get("/discover", self.discover)
        app.router.add_get("/smarty", self.smarty)
        app.router.add_get("/verify/smarty", self.verify_smarty)
        app.router.add_get("/verify/asset", self.verify_asset)
        app.router.add_get("/quote", self.quote)
        app.router.add_get("/candles", self.candles)

        async def _startup(_: web.Application) -> None:
            await self.client.start()

        async def _cleanup(_: web.Application) -> None:
            await self.client.stop()

        app.on_startup.append(_startup)
        app.on_cleanup.append(_cleanup)
        return app


def _requested_symbol_name(instrument: Instrument) -> str:
    symbol = instrument.symbol
    return symbol[:-4] if symbol.endswith("_OTC") else symbol


def create_app(settings: BridgeSettings) -> web.Application:
    with contextlib.suppress(Exception):
        logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
    return BridgeApp(settings).build()
