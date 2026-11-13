"""Authenticated, read-only HTTP bridge between ROZLF AI and a local MT5 terminal.

Run this on the Windows PC or VPS that has MetaTrader 5 installed and logged in.
It never places orders and exposes no trading endpoints.
"""
from __future__ import annotations

import asyncio
import hmac
import logging
from datetime import datetime, timezone

from aiohttp import web

from .client import MT5Client, MT5Error, canonical_symbol
from .settings import BridgeSettings

LOG = logging.getLogger("rozlf.mt5_bridge")
FRAME_SECONDS = {"1min": 60, "5min": 300, "15min": 900, "30min": 1800, "1h": 3600}
MAX_LIMIT = 1500


def _authorised(request: web.Request, key: str) -> bool:
    if not key:
        return False
    supplied = request.headers.get("X-API-Key", "")
    if not supplied:
        auth = request.headers.get("Authorization", "")
        supplied = auth[7:] if auth.lower().startswith("bearer ") else ""
    return bool(supplied) and hmac.compare_digest(supplied, key)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_seconds(value: str | None) -> float | None:
    stamp = _parse_time(value)
    if stamp is None:
        return None
    return (datetime.now(timezone.utc) - stamp).total_seconds()


def create_app(settings: BridgeSettings | None = None, client: MT5Client | None = None) -> web.Application:
    settings = settings or BridgeSettings.from_env()
    client = client or MT5Client(settings)

    async def guard(request: web.Request) -> None:
        if not _authorised(request, settings.api_key):
            raise web.HTTPUnauthorized(text='{"error":"unauthorised"}', content_type="application/json")

    @web.middleware
    async def auth_middleware(request: web.Request, handler):
        if request.path != "/health":
            await guard(request)
        return await handler(request)

    @web.middleware
    async def errors_middleware(request: web.Request, handler):
        try:
            return await handler(request)
        except MT5Error as exc:
            status = 503 if exc.code.startswith("MT5_") else 400
            return web.json_response(
                {"ok": False, "error": exc.code, "message": exc.message}, status=status
            )
        except web.HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            LOG.exception("MT5 bridge request failed")
            return web.json_response({"ok": False, "error": "BRIDGE_ERROR", "message": str(exc)}, status=500)

    async def health(request: web.Request) -> web.Response:
        status = await asyncio.to_thread(client.status)
        if request.path == "/health" and not _authorised(request, settings.api_key):
            status = {"terminal_connected": status.get("terminal_connected", False)}
        return web.json_response({
            "ok": bool(status.get("terminal_connected")),
            "service": "ROZLF-MT5-BRIDGE",
            "server_time": datetime.now(timezone.utc).isoformat(),
            "mode": "read-only",
            **status,
        })

    async def symbols(request: web.Request) -> web.Response:
        rows = await asyncio.to_thread(client.symbols)
        return web.json_response({"ok": True, "terminal_connected": True, "source": "MetaTrader 5", "count": len(rows), "symbols": rows})

    async def candles(request: web.Request) -> web.Response:
        symbol = (request.query.get("symbol") or "").strip()
        frame = (request.query.get("timeframe") or "5min").strip()
        if not symbol or canonical_symbol(symbol) is None:
            raise web.HTTPBadRequest(text='{"ok":false,"error":"BAD_SYMBOL"}', content_type="application/json")
        if frame not in FRAME_SECONDS:
            raise web.HTTPBadRequest(text='{"ok":false,"error":"BAD_TIMEFRAME"}', content_type="application/json")
        try:
            limit = max(50, min(MAX_LIMIT, int(request.query.get("limit", "320"))))
        except ValueError:
            limit = 320
        broker, rows = await asyncio.to_thread(client.candles, symbol, frame, limit)
        last_time = rows[-1]["time"] if rows else None
        age = _age_seconds(last_time)
        threshold = max(settings.max_age_seconds, FRAME_SECONDS[frame] * 2)
        stale = age is None or age > threshold
        if stale:
            return web.json_response({
                "ok": False, "error": "MT5_STALE_DATA", "symbol": symbol.upper(),
                "broker": broker, "last_time": last_time, "age_seconds": age,
            }, status=503)
        return web.json_response({
            "ok": True, "market": "MT5", "source": "MetaTrader 5", "terminal_connected": True,
            "symbol": symbol.upper(), "canonical": canonical_symbol(symbol), "broker": broker, "timeframe": frame,
            "last_time": last_time, "age_seconds": age,
            "server_time": datetime.now(timezone.utc).isoformat(), "candles": rows,
        })

    async def quote(request: web.Request) -> web.Response:
        symbol = (request.query.get("symbol") or "").strip()
        if not symbol or canonical_symbol(symbol) is None:
            raise web.HTTPBadRequest(text='{"ok":false,"error":"BAD_SYMBOL"}', content_type="application/json")
        broker, tick = await asyncio.to_thread(client.quote, symbol)
        age = _age_seconds(tick.get("time"))
        if age is None or age > settings.max_age_seconds:
            return web.json_response({
                "ok": False, "error": "MT5_STALE_TICK", "symbol": symbol.upper(),
                "broker": broker, "last_time": tick.get("time"), "age_seconds": age,
            }, status=503)
        return web.json_response({
            "ok": True, "market": "MT5", "source": "MetaTrader 5", "terminal_connected": True,
            "symbol": symbol.upper(), "canonical": canonical_symbol(symbol), "broker": broker, "age_seconds": age, **tick,
        })

    app = web.Application(middlewares=[errors_middleware, auth_middleware], client_max_size=64 * 1024)
    app.router.add_get("/health", health)
    app.router.add_get("/symbols", symbols)
    app.router.add_get("/candles", candles)
    app.router.add_get("/quote", quote)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = BridgeSettings.from_env()
    if not settings.api_key:
        raise SystemExit("MT5_BRIDGE_KEY is required; set a long random value.")
    LOG.info("ROZLF MT5 bridge listening on %s:%s (read-only)", settings.host, settings.port)
    web.run_app(create_app(settings), host=settings.host, port=settings.port, print=None)


if __name__ == "__main__":
    main()
