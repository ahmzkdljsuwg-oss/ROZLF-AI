"""Minimal aiohttp health/status server for Render."""

from __future__ import annotations

import logging
import time

from aiohttp import web

from .. import __version__
from .container import AppContainer

log = logging.getLogger(__name__)


def build_app(container: AppContainer) -> web.Application:
    app = web.Application()
    app["container"] = container
    app.router.add_get("/", _index)
    app.router.add_get("/health", _health)
    app.router.add_get("/status", _status)
    return app


async def _index(request: web.Request) -> web.Response:
    return web.json_response({"service": "ROZLF AI", "version": __version__})


async def _health(request: web.Request) -> web.Response:
    container: AppContainer = request.app["container"]
    payload = await status_payload(container)
    healthy = bool(payload["telegram_ready"]) and (
        payload["markets"]["forex"]["available"] or payload["markets"]["otc"]["available"]
    )
    return web.json_response(payload, status=200 if healthy else 503)


async def _status(request: web.Request) -> web.Response:
    container: AppContainer = request.app["container"]
    return web.json_response(await status_payload(container))


async def status_payload(container: AppContainer) -> dict:
    markets = await container.registry.market_overview()
    by_market = {row["market"]: row for row in markets}
    stats = await container.stats.overview() if container.stats else {}
    return {
        "service": "ROZLF AI",
        "version": __version__,
        "timestamp": int(time.time()),
        "telegram_ready": bool(container.settings.telegram_bot_token),
        "delivery_mode": container.settings.delivery_mode,
        "ai": {"provider": "mistral", "configured": container.ai.configured},
        "markets": {
            "forex": by_market.get("FOREX", {"available": False}),
            "otc": by_market.get("OTC", {"available": False}),
            "smarty": by_market.get("SMARTY", {"available": False}),
        },
        "runtime": container.state.snapshot(),
        "signals": {
            "total": stats.get("total", 0),
            "open": stats.get("open", 0),
            "resolved": stats.get("resolved", 0),
            "accuracy": stats.get("accuracy"),
        },
    }


async def start_server(container: AppContainer, port: int) -> web.AppRunner:
    runner = web.AppRunner(build_app(container), access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("health server listening on :%s", port)
    return runner
