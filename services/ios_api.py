"""Private, read-only market analysis for the native NEXUS iPhone app."""
from __future__ import annotations

import asyncio
import hmac
import logging
import time
from datetime import timedelta

from aiohttp import web

from ai.vision import ImageRejected, VisionUnavailable, prepare_image
from engines.markets import profile_for
from engines.technical.analyzer import analyze_market_data
from engines.validation import closed_candles
from providers.base import DataUnavailable, utc_now
from providers.catalog import Market, assets_for, timeframe

LOG = logging.getLogger(__name__)
FRAMES = {"smarty": "15sec", "football": "1min", "luxury": "1min",
          "ai": "1min", "cricket": "1min", "otc": "1min",
          "forex": "1min", "gold": "1min", "mt5": "1min"}
LABELS = {Market.SMARTY: "🧠", Market.FOOTBALL: "⚽", Market.LUXURY: "💎",
          Market.AI: "🤖", Market.CRICKET: "🏏", Market.OTC: "🌙",
          Market.FOREX: "💱", Market.GOLD: "🪙", Market.MT5: "📈"}
MODES = {"strong", "lo"}


def install(app: web.Application, context, token: str) -> None:
    if not token:
        return

    async def guard(handler, request):
        auth = request.headers.get("Authorization", "").encode()
        if not hmac.compare_digest(auth, ("Bearer " + token).encode()):
            return web.json_response({"message": "رمز الاتصال غير صحيح"}, status=401)
        ctx = context()
        if ctx is None:
            return web.json_response({"message": "محرك التحليل قيد التشغيل"}, status=503)
        return await handler(ctx, request)

    def route(method, path, handler):
        async def wrapped(request):
            try:
                return await guard(handler, request)
            except (ValueError, TypeError):
                return web.json_response({"message": "طلب غير صالح"}, status=400)
            except Exception:
                LOG.exception("iOS API operation failed: %s", path)
                return web.json_response({"message": "تعذر إكمال الطلب"}, status=500)
        app.router.add_route(method, "/api/nexus/v1/" + path, wrapped)

    slots = asyncio.Semaphore(3)
    lock = asyncio.Lock()
    image_lock = asyncio.Lock()
    scan_cache = {}
    inventory_cache = (0.0, [])

    async def configured(ctx, market):
        try:
            if market.is_expertoption:
                assets = await asyncio.wait_for(ctx.inventory.assets(market), timeout=4)
            elif market is Market.MT5:
                from providers.mt5 import discovered_assets
                mt5 = next((p for p in ctx.registry.providers if p.id == "mt5" and p.configured), None)
                assets = discovered_assets(await asyncio.wait_for(mt5.list_fx_symbols(), timeout=4)) if mt5 else []
            else:
                assets = assets_for(market)
            return [a for a in assets if a.market is market and ctx.registry.source_summary(a) != "NONE"]
        except (DataUnavailable, TimeoutError):
            return []

    async def catalogue(ctx):
        nonlocal inventory_cache
        if inventory_cache[0] > time.monotonic():
            return inventory_cache[1]
        pairs = await asyncio.gather(*(configured(ctx, market) for market in Market))
        rows = [(market, assets) for market, assets in zip(Market, pairs) if assets]
        inventory_cache = (time.monotonic() + 25, rows)
        return rows

    def market_json(market, assets):
        return {"key": market.value, "label": market.label, "icon": LABELS[market], "assets": [
            {"key": a.key, "symbol": a.symbol, "display": a.display} for a in assets]}

    async def health(ctx, _):
        return web.json_response({"status": "ok", "vision": bool(ctx.vision and ctx.vision.configured)})

    async def markets(ctx, _):
        return web.json_response({"markets": [market_json(m, a) for m, a in await catalogue(ctx)]})

    async def analyze(ctx, asset, mode, frame_code):
        async with slots:
            try:
                tf = timeframe(frame_code)
                data = await asyncio.wait_for(ctx.registry.fetch(asset, tf, with_quote=False), timeout=12)
                now = utc_now()
                result = await asyncio.wait_for(asyncio.to_thread(analyze_market_data, data, now, None, mode), timeout=4)
            except (DataUnavailable, TimeoutError):
                return None
        now = utc_now()
        target = result.target_open_at
        valid = target is not None and target > now and result.direction in {"UP", "DOWN"}
        direction = result.direction if valid else "NO TRADE"
        reasons = result.reasons if valid or result.direction == "NO TRADE" else ["انتهت نافذة الشمعة قبل اكتمال التحليل."]
        closed = closed_candles(data.candles, tf, now)
        candles = [{"time": c.time.isoformat(), "open": c.open, "high": c.high, "low": c.low,
                    "close": c.close} for c in closed[-48:]]
        return {"market": asset.market.value, "market_label": asset.market.label,
                "asset": asset.display, "asset_key": asset.key, "source": data.source,
                "direction": direction, "mode": mode, "frame": tf.code,
                "price": closed[-1].close if closed else None, "candles": candles,
                "trend": result.indicators.get("trend"), "volatility": result.indicators.get("volatility"),
                "confidence": result.confidence if valid and result.confidence_verified else None,
                "reasons": reasons, "generated_at": now.isoformat(),
                "target_at": target.isoformat() if target is not None and target > now else None,
                "ends_at": (target + timedelta(seconds=tf.seconds)).isoformat() if valid else None}

    async def analyze_asset(ctx, request):
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError
        mode = body.get("mode", "strong")
        if mode not in MODES:
            raise ValueError
        try:
            market = Market(body.get("market"))
        except ValueError:
            return web.json_response({"message": "السوق غير معروف"}, status=404)
        assets = await configured(ctx, market)
        asset = next((a for a in assets if a.key == body.get("asset")), None)
        if asset is None:
            return web.json_response({"message": "الأصل ليس متاحاً من مصدر السوق"}, status=404)
        code = body.get("frame") or FRAMES[market.value]
        if code not in profile_for(market).frames:
            raise ValueError
        result = await analyze(ctx, asset, mode, code)
        if not result:
            return web.json_response({"message": "الشموع الحديثة غير متاحة لهذا الأصل"}, status=503)
        return web.json_response(result)

    async def scan(ctx, request):
        mode = request.query.get("mode", "strong")
        if mode not in MODES:
            raise ValueError
        if lock.locked():
            return web.json_response({"message": "الفحص السابق جارٍ. أعد المحاولة بعد لحظات."}, status=429)
        async with lock:
            cached = scan_cache.get(mode)
            if cached and cached[0] > time.monotonic():
                return web.json_response(cached[1])
            rows = await catalogue(ctx)
            by_market = dict(rows)

            async def one(market, assets):
                # Deep scans would exhaust providers. Test a second available asset if
                # the first has no candles. Manual analysis can select any active asset.
                for asset in assets[:2]:
                    result = await analyze(ctx, asset, mode, FRAMES[market.value])
                    if result is not None:
                        return result
                return None

            results = await asyncio.gather(*(one(m, a) for m, a in rows))
            now = utc_now().isoformat()
            items = []
            for result in results:
                if result is None:
                    continue
                if result["target_at"] is not None and result["target_at"] <= now:
                    result = {**result, "target_at": None, "ends_at": None, "confidence": None,
                              "direction": "NO TRADE", "reasons": ["افتتحت الشمعة أثناء فحص الأسواق."]}
                items.append(result)
            ready = {r["market"] for r in items}
            payload = {"items": items, "checked": len(rows), "generated_at": now,
                       "unavailable": [m.label for m in Market if m not in by_market or m.value not in ready]}
            scan_cache[mode] = (time.monotonic() + 4, payload)
            return web.json_response(payload)

    async def image(ctx, request):
        if not ctx.vision or not ctx.vision.configured:
            return web.json_response({"message": "خدمة تحليل الصور غير مفعّلة في الخادم"}, status=503)
        if image_lock.locked():
            return web.json_response({"message": "تحليل صورة جارٍ"}, status=429)
        async with image_lock:
            try:
                prepared = await asyncio.to_thread(prepare_image, await request.read())
                result = await ctx.vision.analyse(prepared)
            except ImageRejected as exc:
                return web.json_response({"message": exc.message}, status=400)
            except VisionUnavailable as exc:
                return web.json_response({"message": exc.message}, status=503)
        return web.json_response({"text": result})

    route("GET", "health", health)
    route("GET", "markets", markets)
    route("POST", "analyze", analyze_asset)
    route("POST", "scan", scan)
    route("POST", "image", image)
