"""Application service for the native iOS client.

The public app endpoints are read-only, share one non-Telegram analysis
identity (`APP_USER_ID`), and never bypass the engine's data validation.
"""
from __future__ import annotations

from typing import Any

from bot import formatting as fmt
from engines.technical.analyzer import AnalysisResult, analyze_market_data
from mini_app import service
from mini_app.app_payload import details
from providers.base import DataUnavailable, utc_now
from providers.catalog import Asset, Market, get_asset

APP_USER_ID = -880001
APP_MARKETS = (Market.SMARTY, Market.FOOTBALL, Market.LUXURY, Market.AI, Market.CRICKET, Market.FOREX)


async def _threshold(ctx) -> float:
    settings = await ctx.repo.get_user_settings(
        APP_USER_ID, defaults={"min_confidence": ctx.settings.min_confidence}
    )
    return float(settings["min_confidence"])


def _fallback(asset: Asset, reason: str, allowed: list[int], threshold: float, mode: str) -> dict[str, Any]:
    result = AnalysisResult(
        asset_key=asset.key,
        asset_display=asset.display,
        market=asset.market.value,
        timeframe=service.analysis_frame(asset, allowed[0] if allowed else 60),
        direction="NO TRADE",
        confidence=0.0,
        score_up=0.0,
        score_down=0.0,
        price=0.0,
        source="",
        generated_at=utc_now(),
        cancellation_reason=reason,
    )
    payload = service._result_payload(result, None, None, threshold)
    payload["available_durations"] = allowed
    payload["entry"] = {
        "ready": False,
        "condition": "No entry: the evidence is not sufficient",
        "price": None,
        "price_display": "—",
        "window_seconds": 0,
        "valid_until": None,
        "invalidation": [reason],
    }
    payload["candle_analysis"] = {"candles": [], "forming_candle": None, "summary": reason}
    payload["status"] = "NO_TRADE"
    payload["duration_mode"] = mode
    payload["duration_reason"] = reason
    return payload


async def analyse(ctx, market: Market, asset_key: str | None, duration: int | None) -> dict[str, Any]:
    assets = await service.market_assets(ctx, market)
    asset = get_asset(asset_key) if asset_key else (assets[0] if assets else None)
    if asset is None or asset.market is not market:
        raise DataUnavailable("ASSET_UNAVAILABLE", "This asset is not available in the selected market")
    allowed = service.durations_for(asset)
    if not allowed:
        raise DataUnavailable("DURATION_UNAVAILABLE", "No verified expiry is supported for this asset")
    threshold = await _threshold(ctx)

    if duration is not None:
        if duration not in allowed:
            raise DataUnavailable("DURATION_UNSUPPORTED", "This trade duration is not supported for the selected asset")
        frame = service.analysis_frame(asset, duration)
        try:
            data, result = await ctx.generator.fetch_and_analyse(asset, frame, duration)
        except DataUnavailable as exc:
            return _fallback(asset, exc.message, allowed, threshold, "manual")
        record = None
        if result.direction in ("UP", "DOWN") and result.confidence >= threshold:
            record = await ctx.generator.create_signal(APP_USER_ID, result, duration)
        payload = service._result_payload(result, record, duration, threshold)
        payload.update(details(data, result, duration, threshold))
        payload["available_durations"] = allowed
        payload["duration_mode"] = "manual"
        payload["duration_reason"] = "The duration was selected manually and is not changed by the engine"
        return payload

    best: tuple[tuple[float, float, float], int, AnalysisResult, Any] | None = None
    errors: list[str] = []
    data_by_frame: dict[str, Any] = {}
    for candidate in allowed:
        frame = service.analysis_frame(asset, candidate)
        try:
            data = data_by_frame.get(frame)
            if data is None:
                data = await ctx.registry.fetch(asset, frame)
                data_by_frame[frame] = data
            result = analyze_market_data(data, duration_seconds=candidate)
        except DataUnavailable as exc:
            errors.append(f"{fmt.duration_label(candidate)}: {exc.message}")
            continue
        if result.direction not in ("UP", "DOWN"):
            continue
        rank = (float(result.evidence_score or 0.0), float(result.data_quality_score or 0.0), result.confidence)
        if best is None or rank > best[0]:
            best = (rank, candidate, result, data)
    if best is None:
        return _fallback(asset, "; ".join(errors[:2]) or "No actionable evidence across supported durations", allowed, threshold, "auto")

    _, duration, result, data = best
    record = None
    if result.confidence >= threshold:
        record = await ctx.generator.create_signal(APP_USER_ID, result, duration)
    payload = service._result_payload(result, record, duration, threshold)
    payload.update(details(data, result, duration, threshold))
    payload["available_durations"] = allowed
    payload["duration_mode"] = "auto"
    payload["duration_reason"] = _auto_reason(result, asset, duration)
    return payload


def _auto_reason(result: AnalysisResult, asset: Asset, duration: int) -> str:
    volatility = str(result.indicators.get("volatility") or "NORMAL").upper()
    return (
        f"Chosen from the actual candle structure: {result.timeframe} trend {result.trend_summary}, "
        f"{volatility.lower()} volatility, momentum {result.momentum_strength.lower()}. "
        f"{fmt.duration_label(duration)} is the nearest verified expiry for this asset and market session."
    )


async def recommendations(ctx) -> dict[str, Any]:
    payload = await service.recommendations(ctx, APP_USER_ID)
    for item in payload.get("items", []):
        item.setdefault("status", "READY")
        item.setdefault("data_status", "LIVE")
    payload["generated_at"] = utc_now().isoformat()
    return payload


async def markets(ctx) -> dict[str, Any]:
    payload = await service.markets_overview(ctx)
    allowed = [market.value for market in APP_MARKETS]
    payload["markets"] = [row for row in payload["markets"] if row.get("key", "").lower() in allowed]
    payload["total_markets"] = len(payload["markets"])
    payload["available_markets"] = sum(1 for row in payload["markets"] if row.get("status") == "LIVE")
    return payload


async def history(ctx) -> dict[str, Any]:
    payload = await service.history(ctx, APP_USER_ID)
    payload["stats"] = payload.get("stats", {})
    return payload


async def settings(ctx) -> dict[str, Any]:
    current = await ctx.repo.get_user_settings(
        APP_USER_ID, defaults={"min_confidence": ctx.settings.min_confidence}
    )
    return {"settings": current, "allowed": [50, 60, 70, 80, 90]}


async def save_settings(ctx, minimum: float) -> dict[str, Any]:
    current = await ctx.repo.get_user_settings(
        APP_USER_ID, defaults={"min_confidence": ctx.settings.min_confidence}
    )
    current["min_confidence"] = minimum
    await ctx.repo.save_user_settings(APP_USER_ID, current)
    return {"ok": True, "settings": current}
