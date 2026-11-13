"""Mini App service layer: every number comes from the bot's real engine."""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

from bot import formatting as fmt
from engines.signals.duration import auto_frames, choose_auto_duration
from engines.signals.generator import supported_durations
from engines.technical.analyzer import AnalysisResult, analyze_market_data
from providers.base import DataUnavailable, utc_now
from providers.catalog import Asset, Market, assets_for, get_asset, timeframe

MARKET_ORDER = (Market.SMARTY, Market.FOOTBALL, Market.LUXURY, Market.AI, Market.CRICKET, Market.FOREX)
MARKET_ICONS = {
    Market.SMARTY: "🧠",
    Market.FOOTBALL: "⚽",
    Market.LUXURY: "💎",
    Market.AI: "🤖",
    Market.CRICKET: "🏏",
    Market.FOREX: "💱",
}
MINI_LABELS = {
    Market.SMARTY: "SMARTY MARKET",
    Market.FOOTBALL: "FOOTBALL INDEX",
    Market.LUXURY: "LUXURY INDEX",
    Market.AI: "AI INDEX",
    Market.CRICKET: "CRICKET INDEX",
    Market.FOREX: "FOREX MARKET",
}
MINI_DURATIONS = (30, 60, 120, 180, 300)
RECS_TTL = 45.0
_RECS_CACHE: dict[int, tuple[float, dict]] = {}


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def market_key(value: str | Market) -> Market | None:
    if isinstance(value, Market):
        return value
    raw = str(value).strip()
    for candidate in (raw, raw.lower(), raw.upper()):
        try:
            market = Market(candidate)
        except ValueError:
            continue
        if market in MARKET_ORDER:
            return market
    return None


def analysis_frame(asset: Asset, duration_seconds: int) -> str:
    if asset.market.is_expertoption:
        if duration_seconds <= 30:
            return "30sec"
        if duration_seconds <= 180:
            return "1min"
        return "5min"
    if duration_seconds <= 60:
        return "1min"
    if duration_seconds <= 300:
        return "5min"
    if duration_seconds <= 900:
        return "15min"
    return "1h"


def chart_frame(asset: Asset) -> str:
    return "1min" if asset.market.is_expertoption else "5min"


async def market_assets(ctx, market: Market) -> list[Asset]:
    if market is Market.FOREX or ctx.inventory is None:
        return assets_for(market)
    return await ctx.inventory.assets(market, force=False)


def durations_for(asset: Asset) -> list[int]:
    try:
        allowed = set(supported_durations(asset, timeframe(analysis_frame(asset, 60))))
    except Exception:
        allowed = set(MINI_DURATIONS)
    return [seconds for seconds in MINI_DURATIONS if seconds in allowed]


def _result_payload(result: AnalysisResult, record, duration: int | None, threshold: float) -> dict[str, Any]:
    actionable = result.direction in ("UP", "DOWN") and record is not None
    direction = result.direction if actionable else "NO TRADE"
    reasons = fmt.signal_reasons(result, result.direction) if actionable else []
    if not reasons and actionable:
        reasons = [str(item) for item in result.reasons[:3]]
    if direction == "NO TRADE":
        note = result.cancellation_reason or (
            f"CONFIDENCE {result.confidence:.0f}% IS BELOW YOUR {threshold:.0f}% MINIMUM"
            if result.direction in ("UP", "DOWN") and result.confidence < threshold
            else fmt.no_trade_reason(result)
        )
    else:
        note = None
    return {
        "market": str(result.market).upper(),
        "market_label": fmt.market_label(result.market),
        "asset_key": result.asset_key,
        "asset": result.asset_display,
        "direction": direction,
        "signal_ar": "شراء" if direction == "UP" else "بيع" if direction == "DOWN" else "لا توجد فرصة تداول",
        "confidence": round(result.confidence, 1) if actionable else None,
        "raw_direction": result.direction,
        "duration": duration,
        "duration_label": fmt.duration_label(duration) if duration else "—",
        "duration_ar": fmt.arabic_duration(duration) if duration else "—",
        "price": result.price,
        "price_display": fmt.format_price(result.price, result.market),
        "timeframe": result.timeframe,
        "source": result.source,
        "data_status": "LIVE" if result.source else "UNAVAILABLE",
        "trend": result.trend_summary,
        "momentum": result.momentum_strength,
        "evidence": round(float(result.evidence_score or result.confidence), 1),
        "threshold": threshold,
        "reasons": reasons,
        "no_trade_reason": fmt.no_trade_reason(result) if direction == "NO TRADE" else None,
        "note": note,
        "signal_id": record.id if record is not None else None,
        "recorded": record is not None,
        "generated_at": iso(result.generated_at),
        "analysis_mode": result.analysis_mode,
        "five_min": result.five_min,
        "signal_at": iso(result.signal_at) if result.signal_at else None,
        "entry_at": iso(result.entry_at) if result.entry_at else None,
        "expiry_at": iso(result.expiry_at) if result.expiry_at else None,
        "trade_duration_seconds": result.trade_duration_seconds,
        "mode_blockers": (result.five_min or {}).get("blockers", []) if result.analysis_mode == "5M TREND" else [],
    }


async def analyse(ctx, user_id: int, market: Market, asset_key: str | None, duration: int | None) -> dict[str, Any]:
    assets = await market_assets(ctx, market)
    asset = get_asset(asset_key) if asset_key else (assets[0] if assets else None)
    if asset is None or asset.market is not market:
        raise DataUnavailable("ASSET_UNAVAILABLE", "This asset is not available in the selected market")
    allowed = durations_for(asset)
    if not allowed:
        raise DataUnavailable("DURATION_UNAVAILABLE", "No verified expiry is supported for this asset")
    if duration is None:
        return await analyse_smart(ctx, user_id, market, asset, allowed)
    if duration not in allowed:
        raise DataUnavailable("DURATION_UNSUPPORTED", "This trade duration is not supported for the selected asset")
    settings = await ctx.repo.get_user_settings(user_id, defaults={"min_confidence": ctx.settings.min_confidence})
    threshold = float(settings["min_confidence"])
    result, record = await ctx.generator.generate(
        user_id,
        asset,
        analysis_frame(asset, duration),
        duration_seconds=duration,
        min_confidence=threshold,
    )
    payload = _result_payload(result, record, duration, threshold)
    payload["available_durations"] = allowed
    return payload


async def analyse_smart(ctx, user_id: int, market: Market, asset: Asset, allowed: list[int]) -> dict[str, Any]:
    settings = await ctx.repo.get_user_settings(user_id, defaults={"min_confidence": ctx.settings.min_confidence})
    threshold = float(settings["min_confidence"])
    best: tuple[tuple[float, float, float], int, AnalysisResult] | None = None
    data_by_frame: dict[str, Any] = {}
    errors: list[str] = []
    for duration in allowed:
        frame = analysis_frame(asset, duration)
        try:
            data = data_by_frame.get(frame)
            if data is None:
                data = await ctx.registry.fetch(asset, frame)
                data_by_frame[frame] = data
            result = analyze_market_data(data, duration_seconds=duration)
        except DataUnavailable as exc:
            errors.append(f"{fmt.duration_label(duration)}: {exc.message}")
            continue
        if result.direction not in ("UP", "DOWN"):
            continue
        rank = (float(result.evidence_score or 0.0), float(result.data_quality_score or 0.0), result.confidence)
        if best is None or rank > best[0]:
            best = (rank, duration, result)
    if best is None:
        fallback = AnalysisResult(
            asset_key=asset.key,
            asset_display=asset.display,
            market=asset.market.value,
            timeframe=analysis_frame(asset, allowed[0]),
            direction="NO TRADE",
            confidence=0.0,
            score_up=0.0,
            score_down=0.0,
            price=0.0,
            source="",
            generated_at=utc_now(),
            cancellation_reason="; ".join(errors[:2]) or "No actionable evidence across supported durations",
        )
        payload = _result_payload(fallback, None, None, threshold)
        payload["available_durations"] = allowed
        return payload
    _, duration, winner = best
    record = None
    if winner.confidence >= threshold:
        _, confirmed = await ctx.generator.fetch_and_analyse(asset, analysis_frame(asset, duration), duration)
        if confirmed.direction == winner.direction and confirmed.confidence >= threshold:
            record = await ctx.generator.create_signal(user_id, confirmed, duration)
            winner = confirmed
    payload = _result_payload(winner, record, duration, threshold)
    payload["available_durations"] = allowed
    return payload


async def market_snapshot(ctx, market: Market, include_candles: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "key": market.value.upper(),
        "label": MINI_LABELS.get(market, market.label),
        "icon": MARKET_ICONS[market],
        "available": False,
        "assets": [],
        "source": None,
        "status": "UNAVAILABLE",
        "price": None,
        "candles": [],
        "durations": [],
        "error": None,
    }
    try:
        assets = await market_assets(ctx, market)
    except DataUnavailable as exc:
        payload["error"] = exc.message
        return payload
    except Exception as exc:  # noqa: BLE001 - status must render for every market
        payload["error"] = f"market discovery failed: {exc}"
        return payload
    payload["assets"] = [
        {"key": asset.key, "display": asset.display, "symbol": asset.symbol}
        for asset in assets[:24]
    ]
    if not assets:
        payload["error"] = "No active asset was returned by this market's real source"
        return payload
    asset = assets[0]
    payload["durations"] = durations_for(asset)
    if not include_candles:
        payload["available"] = bool(payload["durations"])
        return payload
    try:
        data = await ctx.registry.fetch(asset, chart_frame(asset))
    except DataUnavailable as exc:
        payload["error"] = exc.message
        payload["source"] = ctx.registry.source_summary(asset)
        return payload
    except Exception as exc:  # noqa: BLE001
        payload["error"] = f"chart fetch failed: {exc}"
        return payload
    candles = data.candles[-80:]
    price = data.quote.mid if data.quote is not None else data.last_close
    payload.update(
        {
            "available": True,
            "status": "LIVE",
            "source": data.source,
            "price": price,
            "price_display": fmt.format_price(price, market.value),
            "last_time": iso(data.last_time),
            "timeframe": data.timeframe.label,
            "bars": data.validation.bar_count,
            "candles": [
                {
                    "t": iso(candle.time),
                    "o": candle.open,
                    "h": candle.high,
                    "l": candle.low,
                    "c": candle.close,
                }
                for candle in candles
            ],
        }
    )
    return payload


async def _health_snapshot(ctx) -> dict[str, Any]:
    """Probe each market for real. The scanner cache alone is not evidence."""
    if ctx.health is None:
        return {}
    try:
        return await asyncio.wait_for(ctx.health.snapshot(), timeout=12.0)
    except Exception:  # noqa: BLE001 - status must render even when probing fails
        return ctx.health.cached()


async def markets_overview(ctx) -> dict[str, Any]:
    health = await _health_snapshot(ctx)
    rows: list[dict[str, Any]] = []
    for market in MARKET_ORDER:
        entry = health.get(market.value)
        row: dict[str, Any] = {
            "key": market.value.upper(),
            "label": MINI_LABELS.get(market, market.label),
            "icon": MARKET_ICONS[market],
            "status": "LIVE" if entry is not None and entry.ok else "UNAVAILABLE",
            "data_state": "LIVE" if entry is not None and entry.ok else "UNAVAILABLE",
            "source": entry.source if entry is not None and entry.ok else None,
            "last_time": iso(entry.last_time) if entry is not None and entry.ok else None,
            "error": None if entry is None or entry.ok else (entry.error or "source unavailable"),
        }
        try:
            assets = await market_assets(ctx, market)
            row["assets"] = len(assets)
            row["asset_preview"] = assets[0].display if assets else None
        except Exception as exc:  # noqa: BLE001
            row["assets"] = 0
            row["error"] = str(exc)
        rows.append(row)
    available = sum(1 for row in rows if row["status"] == "LIVE")
    times = [row["last_time"] for row in rows if row.get("last_time")]
    return {
        "markets": rows,
        "available_markets": available,
        "total_markets": len(rows),
        "last_update": max(times) if times else None,
    }


async def recommendations(ctx, user_id: int) -> dict[str, Any]:
    cached = _RECS_CACHE.get(user_id)
    if cached and time.monotonic() - cached[0] < RECS_TTL:
        return cached[1]
    settings = await ctx.repo.get_user_settings(user_id, defaults={"min_confidence": ctx.settings.min_confidence})
    threshold = float(settings["min_confidence"])

    async def scan(market: Market) -> dict[str, Any] | None:
        try:
            assets = await market_assets(ctx, market)
            if not assets:
                return None
            asset = assets[0]
            best: tuple[tuple[float, float, float], dict[str, Any]] | None = None
            for frame_code in auto_frames(asset)[:2]:
                try:
                    _, result = await ctx.generator.fetch_and_analyse(asset, frame_code)
                except DataUnavailable:
                    continue
                if result.direction not in ("UP", "DOWN") or result.confidence < threshold:
                    continue
                duration, reason = choose_auto_duration(result, asset)
                if duration is None or duration not in durations_for(asset):
                    continue
                try:
                    _, confirmation = await ctx.generator.fetch_and_analyse(
                        asset, frame_code, duration
                    )
                except DataUnavailable:
                    continue
                if confirmation.direction != result.direction or confirmation.confidence < threshold:
                    continue
                result = confirmation
                item = {
                    "market": market.value.upper(),
                    "market_label": MINI_LABELS.get(market, market.label),
                    "icon": MARKET_ICONS[market],
                    "asset": asset.display,
                    "direction": result.direction,
                    "signal_ar": "شراء" if result.direction == "UP" else "بيع",
                    "confidence": round(result.confidence, 1),
                    "duration": duration,
                    "duration_label": fmt.duration_label(duration),
                    "price": result.price,
                    "price_display": fmt.format_price(result.price, market.value),
                    "source": result.source,
                    "reason": reason,
                    "rank": (float(result.evidence_score or 0.0), float(result.data_quality_score or 0.0), result.confidence),
                }
                if best is None or item["rank"] > best[0]:
                    best = (item["rank"], item)
            return best[1] if best else None
        except Exception:  # noqa: BLE001 - one market must not break the list
            return None

    results = await asyncio.gather(*(scan(market) for market in MARKET_ORDER))
    items = [item for item in results if item is not None]
    items.sort(key=lambda item: item["rank"], reverse=True)
    for item in items:
        item.pop("rank", None)
    payload = {"items": items[:4], "threshold": threshold, "empty": not items}
    _RECS_CACHE[user_id] = (time.monotonic(), payload)
    return payload


async def history(ctx, user_id: int) -> dict[str, Any]:
    records = await ctx.repo.recent_signals(limit=50, user_id=user_id)
    stats = await ctx.repo.statistics(user_id=user_id)
    return {
        "signals": [
            {
                "id": record.id,
                "market": record.market,
                "market_label": fmt.market_label(record.market),
                "asset": record.asset_display,
                "direction": record.direction,
                "signal_ar": "شراء" if record.direction == "UP" else "بيع",
                "confidence": record.confidence,
                "duration": record.expiry_seconds,
                "duration_label": fmt.duration_label(record.expiry_seconds),
                "entry": record.entry_price,
                "entry_display": fmt.format_price(record.entry_price, record.market),
                "created_at": iso(record.created_at),
                "entry_at": iso(getattr(record, "entry_at", None) or record.created_at),
                "expires_at": iso(record.expires_at),
                "status": record.status,
                "close_price": record.close_price,
                "result_reason": record.result_reason,
                "source": record.source,
            }
            for record in records
        ],
        "stats": stats,
    }


async def bootstrap(ctx, user) -> dict[str, Any]:
    settings = await ctx.repo.get_user_settings(user.id, defaults={"min_confidence": ctx.settings.min_confidence})
    overview = await markets_overview(ctx)
    sources = ctx.registry.statuses()
    ai = ctx.mistral.health()
    return {
        "user": {"id": user.id, "name": user.display_name},
        "brand": {"name": "ROZLF AI", "tagline": "THE BOT BY LO AND Q8"},
        "api": {
            "telegram": bool(ctx.settings.telegram_bot_token),
            "ai": bool(ai.get("configured") and ai.get("online", False)),
            "ai_detail": ai,
            "sources": sources,
            "bridge": bool(ctx.settings.eo_bridge_url and ctx.settings.eo_bridge_key),
        },
        "markets": overview["markets"],
        "available_markets": overview["available_markets"],
        "total_markets": overview["total_markets"],
        "last_update": overview.get("last_update"),
        "settings": settings,
        "durations": list(MINI_DURATIONS),
        "connection": {
            "service": "ONLINE",
            "engine": "ONLINE" if ctx.generator is not None else "OFFLINE",
            "api": "ONLINE",
            "checked_at": iso(utc_now()),
        },
    }
