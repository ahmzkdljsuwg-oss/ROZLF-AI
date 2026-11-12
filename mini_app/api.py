"""Secure Mini App API + static Telegram Web App served by the bot's web service."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Callable

from aiohttp import web

from mini_app import service
from mini_app.auth import AuthError, authenticate, init_data_from_request
from mini_app.engine_client import EngineClient, EngineUnavailable
from providers.base import DataUnavailable

try:
    from config import settings
except Exception:  # pragma: no cover - import guard for isolated API tests
    settings = None

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
            text=json.dumps(
                {
                    "error": "ENGINE_NOT_READY",
                    "message": "محرك التحليل غير مهيأ على الخادم. أعد المحاولة بعد قليل.",
                },
                ensure_ascii=False,
            ),
            content_type="application/json",
            headers={"Retry-After": "15"},
        )
    if not getattr(ctx.settings, "telegram_bot_token", ""):
        raise web.HTTPServiceUnavailable(
            text=json.dumps(
                {
                    "error": "ENGINE_NOT_READY",
                    "message": "محرك التحليل غير مهيأ على الخادم. أعد المحاولة بعد قليل.",
                },
                ensure_ascii=False,
            ),
            content_type="application/json",
            headers={"Retry-After": "15"},
        )
    return ctx


def _origin_allowed(origin: str) -> bool:
    if not origin:
        return False
    origin = origin.rstrip("/")
    if origin in {"https://telegram.org", "https://web.telegram.org"}:
        return True
    if origin.endswith(".telegram.org"):
        return True
    if settings is not None and settings.mini_app_url:
        base = settings.mini_app_url.split("/mini-app", 1)[0].rstrip("/")
        if origin == base:
            return True
    return False


def _local_ready(provider: ContextProvider) -> bool:
    ctx = provider()
    return ctx is not None and bool(getattr(ctx.settings, "telegram_bot_token", ""))


def _engine_client(engine: EngineClient | None) -> EngineClient | None:
    if engine is not None:
        return engine
    if settings is not None and getattr(settings, "engine_api_url", None):
        return EngineClient(settings.engine_api_url)
    return None


def _user(request: web.Request, ctx):
    try:
        return authenticate(request, ctx.settings.telegram_bot_token)
    except AuthError as exc:
        raise web.HTTPUnauthorized(
            text=json.dumps({"error": exc.code, "message": exc.message}, ensure_ascii=False),
            content_type="application/json",
        ) from exc


def install(app: web.Application, context_provider: ContextProvider, engine: EngineClient | None = None) -> None:
    """Register API and static assets on the existing aiohttp application.

    When the local engine is not initialized (web-only service), authenticated
    API calls are proxied to the bot service that owns the real engine.
    """

    engine = _engine_client(engine)
    if engine is not None:
        app.on_cleanup.append(lambda _app: engine.close())

    @web.middleware
    async def cors(request: web.Request, handler):
        if request.method == "OPTIONS":
            response = web.Response(status=204)
        else:
            response = await handler(request)
        origin = request.headers.get("Origin")
        if _origin_allowed(origin):
            response.headers["Access-Control-Allow-Origin"] = origin.rstrip("/")
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data"
            response.headers["Access-Control-Max-Age"] = "86400"
        return response

    @web.middleware
    async def engine_proxy(request: web.Request, handler):
        if (
            engine is not None
            and request.path.startswith("/api/mini/")
            and request.path != "/api/mini/health"
            and not _local_ready(context_provider)
        ):
            body = await request.read() if request.method in {"POST", "PUT", "PATCH"} else None
            try:
                upstream = await engine.request(
                    request.method,
                    request.path,
                    init_data=init_data_from_request(request),
                    query=request.query_string,
                    body=body,
                )
            except EngineUnavailable as exc:
                return _json(
                    {
                        "error": exc.code,
                        "message": exc.message,
                        "engine_api": "unreachable",
                    },
                    503,
                )
            return web.Response(
                body=upstream.body,
                status=upstream.status,
                content_type=upstream.content_type.split(";", 1)[0],
                charset="utf-8",
                headers={**upstream.headers, "Cache-Control": "no-store"},
            )
        return await handler(request)

    app.middlewares.append(cors)
    app.middlewares.append(engine_proxy)

    async def health(request: web.Request) -> web.Response:
        ctx = context_provider()
        if _local_ready(context_provider):
            payload = {
                "engine_ready": True,
                "mode": "local",
                "telegram_configured": bool(getattr(ctx.settings, "telegram_bot_token", "")),
                "bridge_configured": bool(
                    getattr(ctx.settings, "eo_bridge_url", "") and getattr(ctx.settings, "eo_bridge_key", "")
                ),
                "ai": bool(getattr(getattr(ctx, "mistral", None), "configured", False)),
                "build": os.getenv("RAILWAY_GIT_COMMIT_SHA", ""),
            }
            return _json(payload, 200)
        if engine is not None:
            try:
                remote = await engine.health()
            except EngineUnavailable as exc:
                return _json(
                    {
                        "engine_ready": False,
                        "mode": "proxy",
                        "engine_api": "unreachable",
                        "error": exc.code,
                        "message": exc.message,
                        "build": os.getenv("RAILWAY_GIT_COMMIT_SHA", ""),
                    },
                    503,
                )
            payload = dict(remote)
            payload["mode"] = "proxy"
            payload["engine_api"] = "reachable"
            payload["web_build"] = os.getenv("RAILWAY_GIT_COMMIT_SHA", "")
            return _json(payload, 200 if payload.get("engine_ready") else 503)
        return _json(
            {
                "engine_ready": False,
                "mode": "unconfigured",
                "telegram_configured": bool(ctx and getattr(ctx.settings, "telegram_bot_token", "")),
                "bridge_configured": bool(
                    ctx and getattr(ctx.settings, "eo_bridge_url", "") and getattr(ctx.settings, "eo_bridge_key", "")
                ),
                "ai": bool(ctx and getattr(getattr(ctx, "mistral", None), "configured", False)),
                "build": os.getenv("RAILWAY_GIT_COMMIT_SHA", ""),
            },
            503,
        )

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

    app.router.add_get("/api/mini/health", health)
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
