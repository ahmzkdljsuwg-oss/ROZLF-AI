"""Public read-only JSON API for the native ROZLF iOS application.

No Telegram initData is required, so the iPhone app never needs a bot token or
an API key. The endpoints expose analysis output only; they cannot place trades.
"""
from __future__ import annotations

import logging

from aiohttp import web

from mini_app import app_service, service
from providers.base import DataUnavailable, utc_now

LOG = logging.getLogger(__name__)


def install(app: web.Application, context_provider, respond) -> None:
    def _context(provider):
        ctx = provider()
        if ctx is None:
            raise web.HTTPServiceUnavailable(
                text='{"error": "ENGINE_NOT_READY", "message": "The analysis engine is not ready"}',
                content_type="application/json",
            )
        return ctx

    async def health(request: web.Request) -> web.Response:
        ctx = _context(context_provider)
        ai = ctx.mistral.health() if ctx is not None else {}
        return respond(
            {
                "status": "ok" if ctx is not None and ctx.generator is not None else "degraded",
                "service": "ROZLF AI",
                "engine": "ONLINE" if ctx is not None and ctx.generator is not None else "OFFLINE",
                "database": (
                    "postgresql" if ctx is not None and "postgresql" in ctx.settings.async_database_url
                    else "sqlite" if ctx is not None else None
                ),
                "ai": ai,
                "sources": ctx.registry.statuses() if ctx is not None else {},
                "checked_at": utc_now().isoformat(),
            }
        )

    async def bootstrap(request: web.Request) -> web.Response:
        ctx = _context(context_provider)
        overview = await app_service.markets(ctx)
        settings = await app_service.settings(ctx)
        history = await app_service.history(ctx)
        return respond(
            {
                "brand": {"name": "ROZLF AI", "tagline": "ADVANCED TRADING INTELLIGENCE"},
                "connection": {
                    "engine": "ONLINE",
                    "database": "postgresql" if "postgresql" in ctx.settings.async_database_url else "sqlite",
                    "ai_configured": bool(ctx.mistral.health().get("configured")),
                    "checked_at": utc_now().isoformat(),
                },
                "markets": overview["markets"],
                "available_markets": overview["available_markets"],
                "total_markets": overview["total_markets"],
                "last_update": overview.get("last_update"),
                "settings": settings["settings"],
                "durations": list(service.MINI_DURATIONS),
                "stats": history.get("stats", {}),
            }
        )

    async def markets(request: web.Request) -> web.Response:
        return respond(await app_service.markets(_context(context_provider)))

    async def market_detail(request: web.Request) -> web.Response:
        ctx = _context(context_provider)
        key = service.market_key(request.match_info.get("market", ""))
        if key is None:
            return respond({"error": "UNKNOWN_MARKET", "message": "Unknown market"}, 404)
        try:
            payload = await service.market_snapshot(ctx, key)
        except DataUnavailable as exc:
            return respond({"error": exc.code, "message": exc.message, "detail": exc.detail}, 200)
        return respond(payload)

    async def analyse(request: web.Request) -> web.Response:
        ctx = _context(context_provider)
        try:
            body = await request.json()
        except Exception:
            return respond({"error": "BAD_REQUEST", "message": "JSON body is required"}, 400)
        key = service.market_key(str(body.get("market", "")))
        if key is None:
            return respond({"error": "UNKNOWN_MARKET", "message": "Unknown market"}, 400)
        raw_duration = body.get("duration")
        if raw_duration in (None, "", "auto"):
            duration = None
        else:
            try:
                duration = int(raw_duration)
            except (TypeError, ValueError):
                return respond({"error": "BAD_DURATION", "message": "duration must be seconds or auto"}, 400)
        try:
            payload = await app_service.analyse(ctx, key, body.get("asset"), duration)
        except DataUnavailable as exc:
            return respond(
                {
                    "error": exc.code,
                    "message": exc.message,
                    "detail": exc.detail,
                    "market": key.value,
                    "status": "UNAVAILABLE",
                },
                200,
            )
        except ValueError as exc:
            return respond({"error": "ANALYSIS_REJECTED", "message": str(exc)}, 400)
        except Exception:
            LOG.exception("app analysis failed for market=%s", key.value)
            return respond({"error": "ANALYSIS_FAILED", "message": "The analysis could not be completed"}, 500)
        return respond(payload)

    async def recommendations(request: web.Request) -> web.Response:
        return respond(await app_service.recommendations(_context(context_provider)))

    async def history(request: web.Request) -> web.Response:
        return respond(await app_service.history(_context(context_provider)))

    async def get_settings(request: web.Request) -> web.Response:
        return respond(await app_service.settings(_context(context_provider)))

    async def save_settings(request: web.Request) -> web.Response:
        ctx = _context(context_provider)
        try:
            body = await request.json()
            minimum = float(body.get("min_confidence"))
        except Exception:
            return respond({"error": "BAD_REQUEST", "message": "min_confidence is required"}, 400)
        if minimum not in (50.0, 60.0, 70.0, 80.0, 90.0):
            return respond({"error": "BAD_CONFIDENCE", "message": "min_confidence must be 50, 60, 70, 80 or 90"}, 400)
        return respond(await app_service.save_settings(ctx, minimum))

    app.router.add_get("/api/app/health", health)
    app.router.add_get("/api/app/bootstrap", bootstrap)
    app.router.add_get("/api/app/markets", markets)
    app.router.add_get("/api/app/market/{market}", market_detail)
    app.router.add_post("/api/app/analyse", analyse)
    app.router.add_get("/api/app/recommendations", recommendations)
    app.router.add_get("/api/app/history", history)
    app.router.add_get("/api/app/settings", get_settings)
    app.router.add_post("/api/app/settings", save_settings)
