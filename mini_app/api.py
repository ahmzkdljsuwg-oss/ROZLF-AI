"""Secure Mini App API + static Telegram Web App served by the bot's web service."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from aiohttp import web

from mini_app import service
from mini_app.auth import AuthError, authenticate
from providers.base import DataUnavailable

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
ContextProvider = Callable[[], object | None]

INDEX_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def _json(payload: dict, status: int = 200) -> web.Response:
    body = json.dumps(payload, ensure_ascii=False, default=str)
    return web.Response(
        text=body,
        status=status,
        content_type="application/json",
        charset="utf-8",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "SAMEORIGIN",
        },
    )


def _context(provider: ContextProvider):
    ctx = provider()
    if ctx is None:
        raise web.HTTPServiceUnavailable(
            text=json.dumps({"error": "SERVICE_UNAVAILABLE", "message": "Bot context is not ready"}),
            content_type="application/json",
        )
    return ctx


def _user(request: web.Request, ctx):
    try:
        return authenticate(request, ctx.settings.telegram_bot_token)
    except AuthError as exc:
        raise web.HTTPUnauthorized(
            text=json.dumps({"error": exc.code, "message": exc.message}, ensure_ascii=False),
            content_type="application/json",
        ) from exc


def install(app: web.Application, context_provider: ContextProvider) -> None:
    """Register API and static assets on the existing aiohttp application."""

    async def bootstrap(request: web.Request) -> web.Response:
        ctx = _context(context_provider)
        user = _user(request, ctx)
        return _json(await service.bootstrap(ctx, user))

    async def markets(request: web.Request) -> web.Response:
        ctx = _context(context_provider)
        _user(request, ctx)
        return _json(await service.markets_overview(ctx))

    async def market_detail(request: web.Request) -> web.Response:
        ctx = _context(context_provider)
        _user(request, ctx)
        key = service.market_key(request.match_info.get("market", ""))
        if key is None:
            return _json({"error": "UNKNOWN_MARKET", "message": "Unknown market"}, 404)
        try:
            payload = await service.market_snapshot(ctx, key)
        except DataUnavailable as exc:
            return _json({"error": exc.code, "message": exc.message, "detail": exc.detail}, 200)
        return _json(payload)

    async def analyse(request: web.Request) -> web.Response:
        ctx = _context(context_provider)
        user = _user(request, ctx)
        try:
            body = await request.json()
        except Exception:
            return _json({"error": "BAD_REQUEST", "message": "JSON body is required"}, 400)
        key = service.market_key(str(body.get("market", "")))
        if key is None:
            return _json({"error": "UNKNOWN_MARKET", "message": "Unknown market"}, 400)
        duration = body.get("duration")
        try:
            duration = int(duration) if duration is not None else None
        except (TypeError, ValueError):
            return _json({"error": "BAD_DURATION", "message": "duration must be seconds"}, 400)
        try:
            payload = await service.analyse(ctx, user.id, key, body.get("asset"), duration)
        except DataUnavailable as exc:
            return _json(
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
            return _json({"error": "ANALYSIS_REJECTED", "message": str(exc)}, 400)
        return _json(payload)

    async def recommendations(request: web.Request) -> web.Response:
        ctx = _context(context_provider)
        user = _user(request, ctx)
        return _json(await service.recommendations(ctx, user.id))

    async def history(request: web.Request) -> web.Response:
        ctx = _context(context_provider)
        user = _user(request, ctx)
        return _json(await service.history(ctx, user.id))

    async def get_settings(request: web.Request) -> web.Response:
        ctx = _context(context_provider)
        user = _user(request, ctx)
        settings = await ctx.repo.get_user_settings(
            user.id, defaults={"min_confidence": ctx.settings.min_confidence}
        )
        return _json({"settings": settings, "allowed": [50, 60, 70, 80, 90]})

    async def save_settings(request: web.Request) -> web.Response:
        ctx = _context(context_provider)
        user = _user(request, ctx)
        try:
            body = await request.json()
            minimum = float(body.get("min_confidence"))
        except Exception:
            return _json({"error": "BAD_REQUEST", "message": "min_confidence is required"}, 400)
        if minimum not in (50.0, 60.0, 70.0, 80.0, 90.0):
            return _json(
                {"error": "BAD_CONFIDENCE", "message": "min_confidence must be 50, 60, 70, 80 or 90"},
                400,
            )
        current = await ctx.repo.get_user_settings(
            user.id, defaults={"min_confidence": ctx.settings.min_confidence}
        )
        current["min_confidence"] = minimum
        await ctx.repo.save_user_settings(user.id, current)
        return _json({"ok": True, "settings": current})

    async def status(request: web.Request) -> web.Response:
        ctx = _context(context_provider)
        _user(request, ctx)
        return _json(
            {
                "telegram_configured": bool(ctx.settings.telegram_bot_token),
                "bridge_configured": bool(ctx.settings.eo_bridge_url and ctx.settings.eo_bridge_key),
                "ai": ctx.mistral.health(),
                "sources": ctx.registry.statuses(),
                "database": "postgresql" if "postgresql" in ctx.settings.async_database_url else "sqlite",
                "mini_app_url": ctx.settings.mini_app_url,
            }
        )

    async def index(request: web.Request) -> web.Response:
        return web.FileResponse(STATIC_DIR / "index.html", headers=INDEX_HEADERS)

    async def app_redirect(request: web.Request) -> web.Response:
        raise web.HTTPFound("/mini-app/")

    app.router.add_get("/api/mini/bootstrap", bootstrap)
    app.router.add_get("/api/mini/markets", markets)
    app.router.add_get("/api/mini/market/{market}", market_detail)
    app.router.add_post("/api/mini/analyse", analyse)
    app.router.add_get("/api/mini/recommendations", recommendations)
    app.router.add_get("/api/mini/history", history)
    app.router.add_get("/api/mini/settings", get_settings)
    app.router.add_post("/api/mini/settings", save_settings)
    app.router.add_get("/api/mini/status", status)
    app.router.add_get("/mini-app", app_redirect)
    app.router.add_get("/mini-app/", index)
    app.router.add_static("/mini-app/static/", str(STATIC_DIR), name="mini-static")
