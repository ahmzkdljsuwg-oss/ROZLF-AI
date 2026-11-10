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
        if request.path in {"/", "/health"}:
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
                "endpoints": ["/health", "/assets", "/discover", "/smarty", "/quote", "/candles"],
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
