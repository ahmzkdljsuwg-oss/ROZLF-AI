"""Same-origin Web App, connected to the existing read-only NEXUS engine."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
import logging
import math
import time

from aiohttp import web

from engines.markets import profile_for
from engines.technical.analyzer import analyze_market_data
from engines.validation import closed_candles
from providers.base import DataUnavailable, utc_now
from providers.catalog import Market, assets_for, timeframe
from .auth import telegram_user

STATIC = Path(__file__).parent / "static"
MARKETS = (Market.FOOTBALL, Market.SMARTY, Market.GOLD, Market.OTC, Market.LUXURY,
           Market.AI, Market.CRICKET, Market.FOREX, Market.MT5)
ICONS = dict(zip(MARKETS, ("⚽", "🧠", "🪙", "🌙", "💎", "🤖", "🏏", "💱", "📈")))
LOG = logging.getLogger(__name__)
MIN_LEAD = 2.0
FAST_FRAMES = ("5sec", "15sec", "30sec", "1min")

_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self' https://telegram.org; "
        "style-src 'self'; img-src 'self' data:; connect-src 'self'; "
        "base-uri 'none'; object-src 'none'"
    ),
}


def _response(payload, status=200):
    return web.json_response(payload, status=status, headers=_SECURITY_HEADERS)


def _error(code, message, status):
    return _response({"code": code, "message": message}, status)


def _ms(stamp):
    return int(stamp.timestamp() * 1000)


async def _owned_fetch(registry, asset, tf):
    # Registry coalesces work with Telegram /lo. A Mini App timeout must not
    # cancel another user's in-flight Telegram candle request.
    task = asyncio.create_task(registry.fetch(asset, tf, with_quote=False))
    task.add_done_callback(lambda value: value.exception() if not value.cancelled() else None)
    return await asyncio.wait_for(asyncio.shield(task), timeout=6.0)


async def _analyze_frame(registry, asset, frame, mode):
    tf = timeframe(frame)
    data = await _owned_fetch(registry, asset, tf)
    now = utc_now()
    bars = closed_candles(data.candles, tf, now)
    if any(not math.isfinite(value) for bar in bars for value in (bar.open, bar.high, bar.low, bar.close)):
        raise DataUnavailable("INVALID_CANDLES", "المصدر رجع قيماً غير صالحة")
    if len(bars) < 200:
        raise DataUnavailable("INSUFFICIENT_BARS", "شموع مغلقة غير كافية")
    # Forecast the next actual slot, not an arbitrary slot after a stale feed.
    target = bars[-1].time + timedelta(seconds=2 * tf.seconds)
    if target <= now or any(
        b.time - a.time != timedelta(seconds=tf.seconds)
        for a, b in zip(bars[-5:-1], bars[-4:])
    ):
        raise DataUnavailable("MISSING_RECENT_CANDLE", "لم تصل شموع حديثة ومتتابعة لهذا الأصل")
    result = await asyncio.to_thread(analyze_market_data, data, now, None, "lo" if mode == "fast" else "strong")
    direction = result.direction
    reasons = result.reasons
    if direction in ("UP", "DOWN") and (
        result.target_open_at != target or (target - utc_now()).total_seconds() < MIN_LEAD
    ):
        direction = "NO TRADE"
        reasons = ["نافذة الشمعة قصيرة، أعد الفحص للشمعة التالية."]
    # Avoid presenting a high-volatility range as a reliable next-candle entry.
    # Only affects the Mini App; Telegram /lo remains unchanged.
    if (mode == "fast" and direction in ("UP", "DOWN")
            and result.indicators.get("trend") == "RANGE"
            and result.indicators.get("volatility") == "HIGH"):
        direction = "NO TRADE"
        reasons = ["السوق عرضي ومتذبذب بقوة؛ لا توجد أفضلية واضحة للشمعة القادمة."]
    if mode == "minute" and not result.confidence_verified and direction in ("UP", "DOWN"):
        direction = "NO TRADE"
        reasons = ["لا توجد معايرة صالحة لهذا الفريم."]
    candles = [
        {"at": _ms(c.time), "open": c.open, "high": c.high, "low": c.low, "close": c.close}
        for c in bars[-40:]
    ]
    return {
        "asset": asset.display, "symbol": asset.symbol, "market": asset.market.value, "source": data.source,
        "mode": mode, "frame": frame, "seconds": tf.seconds, "direction": direction,
        "trend": result.indicators.get("trend"), "volatility": result.indicators.get("volatility"),
        "confidence": result.confidence if mode == "minute" and direction != "NO TRADE" and result.confidence_verified else None,
        "reasons": reasons[:3], "candles": candles, "closed_count": len(bars),
        "target_ms": _ms(target) if direction != "NO TRADE" else None,
        "end_ms": _ms(target + timedelta(seconds=tf.seconds)) if direction != "NO TRADE" else None,
    }


async def _inventory(ctx, market):
    try:
        if market.is_expertoption:
            if not ctx.inventory:
                return []
            rows = await asyncio.wait_for(ctx.inventory.assets(market), 4)
        elif market is Market.MT5:
            from providers.mt5 import discovered_assets
            provider = next((p for p in ctx.registry.providers if p.id == "mt5" and p.configured), None)
            rows = discovered_assets(await asyncio.wait_for(provider.list_fx_symbols(), 4)) if provider else []
        else:
            rows = assets_for(market)
    except (DataUnavailable, TimeoutError):
        return []
    return [a for a in rows if a.market is market and any(p.configured for p in ctx.registry.providers_for(a))]


def install(app, settings, get_context):
    slots = asyncio.Semaphore(3)
    catalogue_lock = asyncio.Lock()
    cache = (0.0, {})
    user_busy: set[int] = set()

    async def catalogue(ctx):
        nonlocal cache
        async with catalogue_lock:
            if cache[0] > time.monotonic():
                return cache[1]
            rows = await asyncio.gather(*(_inventory(ctx, market) for market in MARKETS))
            result = dict(zip(MARKETS, rows))
            cache = (time.monotonic() + 20, result)
            return result

    def protected(handler):
        async def route(request):
            request["mini_received"] = time.monotonic()
            try:
                user_id = telegram_user(request.headers.get("X-Telegram-Init-Data", ""), settings.telegram_bot_token)
            except (ValueError, TypeError, UnicodeError):
                return _error("TELEGRAM_REQUIRED", "افتح التطبيق من زر Mini App في محادثة البوت.", 401)
            ctx = get_context()
            if ctx is None:
                return _error("ENGINE_NOT_READY", "المحرك يبدأ الآن. حاول بعد لحظات.", 503)
            try:
                if settings.subscriptions_enabled:
                    if user_id not in settings.owner_ids and not await ctx.repo.is_subscribed(user_id):
                        return _error("NOT_AUTHORIZED", "هذا الحساب غير مفعل في البوت.", 403)
                elif settings.allowed_chat_ids and user_id not in settings.allowed_chat_ids:
                    return _error("NOT_AUTHORIZED", "هذا الحساب غير مخول باستخدام البوت.", 403)
                return await handler(request, ctx, user_id)
            except web.HTTPException:
                raise
            except Exception:
                LOG.exception("Mini App request failed on %s", request.path)
                return _error("SERVER_ERROR", "تعذر إكمال الطلب الآن.", 500)
        return route

    @protected
    async def markets(_request, ctx, _user):
        return _response({"markets": [
            {"key": market.value, "label": market.label, "icon": ICONS[market],
             "assets": [{"key": a.key, "label": a.name or a.symbol, "symbol": a.symbol} for a in rows]}
            for market, rows in (await catalogue(ctx)).items() if rows
        ]})

    @protected
    async def analyze(request, ctx, user_id):
        try:
            if request.content_length is not None and request.content_length > 2048:
                return _error("BAD_REQUEST", "حجم الطلب أكبر من المسموح.", 413)
            body = await request.json()
            market = Market(body["market"])
            asset_key = body["asset"]
            mode = body["mode"]
            if not isinstance(asset_key, str) or mode not in ("fast", "minute"):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            return _error("BAD_REQUEST", "اختر سوقاً وأصلاً ونوع التحليل.", 400)
        if user_id in user_busy or slots.locked():
            return _error("BUSY", "التحليل مشغول الآن. أعد المحاولة بعد لحظات.", 429)
        user_busy.add(user_id)
        try:
            async with slots:
                rows = (await catalogue(ctx)).get(market, ())
                asset = next((a for a in rows if a.key == asset_key), None)
                if asset is None:
                    return _error("MARKET_UNAVAILABLE", "الأصل غير متاح من مصدر هذا السوق الآن.", 404)
                supported = profile_for(market).frames
                plan = ("1min",) if mode == "minute" else tuple(f for f in FAST_FRAMES if f in supported)
                best = None
                deadline = time.monotonic() + 15
                for frame in plan:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        result = await asyncio.wait_for(_analyze_frame(ctx.registry, asset, frame, mode), remaining)
                    except (DataUnavailable, TimeoutError):
                        continue
                    best = result
                    if best["direction"] != "NO TRADE":
                        break
                if best is None:
                    return _error("DATA_UNAVAILABLE", "المصدر لم يرجع شموعاً حديثة وكافية لهذا الأصل.", 503)
                now = _ms(utc_now())
                if best["target_ms"] is not None and best["target_ms"] - now < MIN_LEAD * 1000:
                    best.update(direction="NO TRADE", target_ms=None, end_ms=None, confidence=None,
                                reasons=["انتهت نافذة النشر، أعد الفحص للشمعة التالية."])
                return _response({**best, "server_ms": now,
                                  "processing_ms": int((time.monotonic() - request["mini_received"]) * 1000)})
        finally:
            user_busy.discard(user_id)

    def document(name):
        async def serve(_request):
            return web.FileResponse(STATIC / name, headers=_SECURITY_HEADERS)
        return serve

    app.router.add_get("/mini-app", document("index.html"))
    app.router.add_get("/mini-app/", document("index.html"))
    app.router.add_get("/mini-app/app.css", document("app.css"))
    app.router.add_get("/mini-app/app.js", document("app.js"))
    app.router.add_get("/api/nexus-mini/v1/markets", markets)
    app.router.add_post("/api/nexus-mini/v1/analyze", analyze)
