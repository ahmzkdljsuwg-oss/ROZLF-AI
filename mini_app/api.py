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
from engines.technical.indicators import compute_indicators, frame_from_candles
from engines.validation import closed_candles
from providers.base import DataUnavailable, utc_now
from providers.catalog import Market, assets_for, timeframe
from services.market_analysis import NATIVE_FRAMES, native_frame_plan
from .auth import telegram_user

STATIC = Path(__file__).parent / "static"
MARKETS = (Market.FOOTBALL, Market.SMARTY, Market.GOLD, Market.OTC, Market.LUXURY,
           Market.AI, Market.CRICKET, Market.FOREX, Market.MT5)
ICONS = dict(zip(MARKETS, ("⚽", "🧠", "🪙", "🌙", "💎", "🤖", "🏏", "💱", "📈")))
LOG = logging.getLogger(__name__)
MIN_LEAD = 2.0
FAST_FRAMES = ("5sec", "15sec", "30sec", "1min")
FRAME_BUDGET = {"5sec": 5.0, "15sec": 6.0, "30sec": 8.0, "1min": 18.0, "2min": 18.0, "3min": 18.0, "5min": 18.0}
ANALYSIS_BUDGET = 34.0
SOURCE_ERRORS = {
    "RATE_LIMITED": "مصدر الأسعار وصل إلى حد الطلبات. أعد المحاولة بعد قليل.",
    "DISCONNECTED": "اتصال مصدر الشموع منقطع مؤقتاً. أعد المحاولة.",
    "NETWORK": "تعذّر الاتصال بمصدر الشموع. أعد المحاولة.",
    "TIMEOUT": "مصدر الشموع تأخّر. أعد المحاولة.",
    "MISSING_RECENT_CANDLE": "الشموع المتاحة قديمة أو متقطعة. ما فيه توقع حالياً.",
    "NO_CLOSED_CANDLES": "ما وصلت شموع مغلقة لهذا الأصل.",
    "INVALID_CANDLES": "المصدر أعاد شموعاً غير صالحة.",
    "DATA_UNAVAILABLE": "ما وصلت شموع موثوقة لهذا الأصل من مصدره.",
}

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


async def _owned_fetch(registry, asset, tf, *, fresh=False):
    # Let the registry finish shared work even if the Mini App stops waiting.
    task = asyncio.create_task(registry.fetch(asset, tf, with_quote=False, fresh=fresh))
    task.add_done_callback(lambda value: value.exception() if not value.cancelled() else None)
    return await asyncio.shield(task)


def _bar_window(data, tf, now):
    bars = closed_candles(data.candles, tf, min(now, data.fetched_at))
    if not bars:
        raise DataUnavailable("NO_CLOSED_CANDLES", SOURCE_ERRORS["NO_CLOSED_CANDLES"])
    if any(not math.isfinite(value) for bar in bars for value in (bar.open, bar.high, bar.low, bar.close)):
        raise DataUnavailable("INVALID_CANDLES", SOURCE_ERRORS["INVALID_CANDLES"])
    step = timedelta(seconds=tf.seconds)
    end = bars[-1].time + step
    target = end + step
    contiguous = all(b.time - a.time == step for a, b in zip(bars[-5:-1], bars[-4:]))
    return bars, end, target, contiguous


async def _analyze_frame(registry, asset, frame, mode, *, budget=None):
    tf = timeframe(frame)
    budget = FRAME_BUDGET[frame] if budget is None else min(budget, FRAME_BUDGET[frame])
    deadline = time.monotonic() + budget
    data = await asyncio.wait_for(_owned_fetch(registry, asset, tf), budget)
    now = utc_now()
    bars, end, target, contiguous = _bar_window(data, tf, now)
    if target <= now or not contiguous:
        # A six-second cache lease can outlive a five-second candle. Refresh
        # once without changing the market, provider, symbol or frame.
        remaining = deadline - time.monotonic()
        if remaining > 0.3:
            try:
                updated = await asyncio.wait_for(_owned_fetch(registry, asset, tf, fresh=True), remaining)
                updated_now = utc_now()
                window = _bar_window(updated, tf, updated_now)
                if window[1] >= end:
                    data, now = updated, updated_now
                    bars, end, target, contiguous = window
            except (DataUnavailable, TimeoutError) as exc:
                LOG.info("Mini chart refresh %s %s: %s", asset.key, frame, getattr(exc, "code", "TIMEOUT"))
        now = utc_now()

    # Keep the real chart when there is a recent snapshot, but do not run the
    # forecast on incomplete history or late/gapped bars.
    if now - end > timedelta(seconds=2 * tf.seconds):
        raise DataUnavailable("MISSING_RECENT_CANDLE", SOURCE_ERRORS["MISSING_RECENT_CANDLE"])
    issue = ("SHORT_HISTORY" if len(bars) < 200 else
             "MISSING_RECENT_CANDLE" if target <= now or not contiguous else None)
    direction = "NO TRADE"
    confidence = None
    if issue:
        indicators = await asyncio.to_thread(lambda: compute_indicators(frame_from_candles(bars)))
        reasons = [f"وصلت {len(bars)} شمعة مغلقة. نحتاج 200 لتوقع الاتجاه."
                   if issue == "SHORT_HISTORY" else
                   "هذا آخر شارت متاح. لم تصل شموع متتابعة في الوقت المناسب للتوقع."]
    else:
        result = await asyncio.to_thread(analyze_market_data, data, now, None, {"fast": "lo", "fast_v2": "fast", "pro": "pro", "minute": "strong"}[mode])
        indicators = result.indicators
        direction = result.direction
        reasons = result.reasons
        if direction in ("UP", "DOWN") and (
            result.target_open_at != target or (target - utc_now()).total_seconds() < MIN_LEAD
        ):
            direction = "NO TRADE"
            reasons = ["نافذة الشمعة قصيرة، أعد الفحص للشمعة التالية."]
        if (mode == "fast" and direction in ("UP", "DOWN")
                and indicators.get("trend") == "RANGE" and indicators.get("volatility") == "HIGH"):
            direction = "NO TRADE"
            reasons = ["السوق عرضي ومتذبذب بقوة؛ ما فيه اتجاه واضح للشمعة القادمة."]
        if mode in {"minute", "pro"}:
            if not result.confidence_verified and direction != "NO TRADE":
                direction = "NO TRADE"
                reasons = ["لا توجد معايرة صالحة لهذا الأصل على الدقيقة."]
            elif direction != "NO TRADE":
                confidence = result.confidence

    candles = [
        {"at": _ms(c.time), "open": c.open, "high": c.high, "low": c.low, "close": c.close}
        for c in bars[-40:]
    ]
    return {
        "asset": asset.display, "symbol": asset.symbol, "market": asset.market.value, "source": data.source,
        "mode": mode, "frame": frame, "seconds": tf.seconds, "direction": direction,
        "trend": indicators.get("trend"), "volatility": indicators.get("volatility"), "confidence": confidence,
        "reasons": reasons[:3], "candles": candles, "closed_count": len(bars),
        "data_issue": issue, "last_closed_ms": _ms(end),
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

    def packed_signal(record):
        return {"id": record.id, "market": record.market, "asset": record.asset_display,
                "frame": record.timeframe, "seconds": record.expiry_seconds,
                "direction": record.direction, "mode": record.analysis_mode,
                "status": record.status, "target_ms": _ms(record.target_open_at),
                "end_ms": _ms(record.expires_at), "reason": record.result_reason,
                "open": record.entry_price if record.close_price is not None else None,
                "close": record.close_price}

    @protected
    async def dashboard(_request, ctx, user):
        rows, recent, results, enabled, mode = await asyncio.gather(
            catalogue(ctx), ctx.repo.recent_signals(50, user), ctx.repo.candle_statistics(user),
            ctx.repo.scanner_opt_in(user), ctx.repo.get_analysis_mode(user))
        scanner = getattr(ctx, "scanner", None)
        return _response({
            "server_ms": _ms(utc_now()),
            "scanner": {"enabled": enabled, "running": bool(scanner and scanner.running),
                        "last_scan_ms": _ms(scanner.last_run) if scanner and scanner.last_run else None},
            "mode": mode,
            "markets": [{"key": market.value, "label": market.label, "icon": ICONS[market],
                         **ctx.registry.market_readiness(market),
                         "frames": [f for f in NATIVE_FRAMES if f in profile_for(market).frames],
                         "assets": [{"key": a.key, "label": a.name or a.symbol, "symbol": a.symbol}
                                    for a in assets]} for market, assets in rows.items()],
            "signals": [packed_signal(r) for r in recent if r.target_open_at and r.delivered_at
                        and r.delivered_at < r.target_open_at],
            "performance": results, "latency": ctx.registry.latency(),
        })

    @protected
    async def preferences(request, ctx, user):
        if request.content_length is not None and request.content_length > 1024:
            return _error("BAD_REQUEST", "حجم الطلب أكبر من المسموح.", 413)
        try:
            body = await request.json()
            if not isinstance(body, dict) or not body or set(body) - {"scanner", "mode"}:
                raise ValueError
            if "scanner" in body and not isinstance(body["scanner"], bool):
                raise ValueError
            if "mode" in body and body["mode"] not in ("fast", "pro", "lo", "strong"):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            return _error("BAD_REQUEST", "الإعداد غير صالح.", 400)
        if "scanner" in body:
            await ctx.repo.set_scanner_opt_in(user, body["scanner"])
        if "mode" in body:
            await ctx.repo.set_analysis_mode(user, body["mode"])
        return _response({"scanner": await ctx.repo.scanner_opt_in(user),
                          "mode": await ctx.repo.get_analysis_mode(user)})

    @protected
    async def analyze(request, ctx, user_id):
        try:
            if request.content_length is not None and request.content_length > 2048:
                return _error("BAD_REQUEST", "حجم الطلب أكبر من المسموح.", 413)
            body = await request.json()
            market = Market(body["market"])
            asset_key = body["asset"]
            mode = body["mode"]
            selected = body.get("frame")
            if (not isinstance(asset_key, str) or mode not in ("fast", "minute", "pro")
                    or (selected is not None and not isinstance(selected, str))):
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
                revised = mode == "pro" or selected is not None
                effective = "fast_v2" if revised and mode == "fast" else mode
                if revised:
                    if selected is not None and selected != "auto":
                        if selected not in NATIVE_FRAMES or selected not in supported:
                            return _error("FRAME_UNSUPPORTED", "الفريم غير متاح من المصدر الأصلي لهذا السوق.", 400)
                        plan = (selected,)
                    else:
                        plan = native_frame_plan(asset, mode)
                else:
                    plan = ("1min",) if mode == "minute" else tuple(f for f in FAST_FRAMES if f in supported)
                best = None
                failures = []
                deadline = time.monotonic() + (12.0 if effective == "fast_v2" else ANALYSIS_BUDGET)

                async def sample(frame):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None, "TIMEOUT"
                    try:
                        return await _analyze_frame(ctx.registry, asset, frame, effective, budget=remaining), None
                    except (DataUnavailable, TimeoutError) as exc:
                        code = getattr(exc, "code", "TIMEOUT")
                        LOG.info("Mini candles %s %s failed: %s", asset.key, frame, code)
                        return None, code

                def choose(current, result):
                    if current is None:
                        return result
                    if result["direction"] != "NO TRADE" and (
                        current["direction"] == "NO TRADE" or
                        (result["confidence"] or 0) > (current["confidence"] or 0)):
                        return result
                    if (current["direction"] == "NO TRADE" and current["data_issue"] and not result["data_issue"]):
                        return result
                    return current

                if revised:
                    tasks = [asyncio.create_task(sample(frame)) for frame in plan]
                    try:
                        for task in asyncio.as_completed(tasks, timeout=max(0.1, deadline - time.monotonic())):
                            result, code = await task
                            if result:
                                best = choose(best, result)
                                if effective == "fast_v2" and result["direction"] != "NO TRADE":
                                    break
                            elif code:
                                failures.append(code)
                    except TimeoutError:
                        failures.append("TIMEOUT")
                    finally:
                        for task in tasks:
                            task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                else:
                    for frame in plan:
                        result, code = await sample(frame)
                        if result:
                            best = choose(best, result)
                            if result["direction"] != "NO TRADE":
                                break
                        elif code:
                            failures.append(code)
                            if code in {"RATE_LIMITED", "INVALID_KEY", "EO_BRIDGE_UNAUTHORIZED", "INACTIVE_ASSET"}:
                                break
                if best is None:
                    reason = next((code for code in reversed(failures) if code in SOURCE_ERRORS), "DATA_UNAVAILABLE")
                    return _response({"code": "DATA_UNAVAILABLE", "reason": reason,
                                      "message": SOURCE_ERRORS[reason]}, 503)
                now = _ms(utc_now())
                if mode == "pro" and best["direction"] in ("UP", "DOWN") and (
                        best["confidence"] is None or best["confidence"] < settings.min_confidence):
                    best.update(direction="NO TRADE", target_ms=None, end_ms=None, confidence=None,
                                reasons=["القراءة المعايرة لم تتجاوز حد الثقة المفعّل لهذا الوضع."])
                if best["target_ms"] is not None and best["target_ms"] - now < MIN_LEAD * 1000:
                    best.update(direction="NO TRADE", target_ms=None, end_ms=None, confidence=None,
                                reasons=["انتهت نافذة النشر، أعد الفحص للشمعة التالية."])
                return _response({**best, "mode": mode, "server_ms": now,
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
    app.router.add_get("/api/nexus-mini/v1/dashboard", dashboard)
    app.router.add_post("/api/nexus-mini/v1/preferences", preferences)
