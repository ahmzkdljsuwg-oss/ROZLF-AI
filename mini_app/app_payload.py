"""Read-only payload shaping for the native ROZLF iOS app.

Every field is derived from a real `AnalysisResult` and the market data that
produced it. Nothing here invents a price, a candle or a signal.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from bot import formatting as fmt
from engines.validation import closed_candles
from providers.base import MarketData, utc_now
from engines.technical.analyzer import AnalysisResult


def _pct(value: float, total: float) -> float:
    return round(100 * value / total, 1) if total else 0.0


def candle_rows(data: MarketData, count: int = 8) -> dict[str, Any]:
    now = utc_now()
    closed = closed_candles(data.candles, data.timeframe, now)
    rows: list[dict[str, Any]] = []
    for candle in closed[-count:]:
        span = candle.high - candle.low
        body = abs(candle.close - candle.open)
        bullish = candle.close >= candle.open
        rows.append(
            {
                "time": candle.time.isoformat(),
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "direction": "UP" if bullish else "DOWN",
                "body_pct": _pct(body, span),
                "upper_wick_pct": _pct(candle.high - max(candle.open, candle.close), span),
                "lower_wick_pct": _pct(min(candle.open, candle.close) - candle.low, span),
                "close_position_pct": _pct(candle.close - candle.low, span),
                "closed": True,
            }
        )
    forming = None
    if data.candles and len(closed) < len(data.candles):
        candle = data.candles[-1]
        span = candle.high - candle.low
        forming = {
            "time": candle.time.isoformat(),
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "direction": "UP" if candle.close >= candle.open else "DOWN",
            "body_pct": _pct(abs(candle.close - candle.open), span),
            "closed": False,
        }
    last = rows[-1] if rows else None
    summary = "No closed candle is available yet"
    if last is not None:
        bias = "buyers" if last["direction"] == "UP" else "sellers"
        strength = "strong" if last["body_pct"] >= 60 else "moderate" if last["body_pct"] >= 35 else "weak"
        rejection = ""
        if last["upper_wick_pct"] >= 45:
            rejection = " with upper-wick rejection"
        elif last["lower_wick_pct"] >= 45:
            rejection = " with lower-wick rejection"
        summary = f"Last closed candle is {last['direction'].lower()} with a {strength} body controlled by {bias}{rejection}"
    return {
        "candles": rows,
        "forming_candle": forming,
        "summary": summary,
        "note": "The forming candle is shown for context only and is excluded from the decision.",
    }


def entry_plan(result: AnalysisResult, duration: int | None, threshold: float) -> dict[str, Any]:
    actionable = result.direction in ("UP", "DOWN") and result.confidence >= threshold
    now = result.generated_at
    window = max(30, min(duration or 60, 300))
    invalidation = list(result.invalidation)
    if result.alligator_ma:
        jaw = result.alligator_ma.get("jaw")
        if jaw is not None:
            relation = "above" if result.price > float(jaw) else "below"
            invalidation.append(f"Alligator jaw at {jaw} — price closing on the wrong side invalidates the setup ({relation} now)")
    invalidation.append("A closed candle against the trade direction before entry cancels the signal")
    if result.cancellation_reason:
        invalidation.insert(0, result.cancellation_reason)
    return {
        "ready": actionable,
        "condition": (
            "Enter at the current market price when the next candle opens in the signal direction"
            if actionable
            else "No entry: the evidence is not sufficient"
        ),
        "price": result.price,
        "price_display": fmt.format_price(result.price, result.market),
        "window_seconds": window,
        "valid_until": (now + timedelta(seconds=window)).isoformat() if actionable else None,
        "invalidation": invalidation[:5],
    }


def details(data: MarketData, result: AnalysisResult, duration: int | None, threshold: float) -> dict[str, Any]:
    return {
        "candle_analysis": candle_rows(data),
        "entry": entry_plan(result, duration, threshold),
        "evidence": round(float(result.evidence_score or 0.0), 1),
        "data_quality": result.data_confidence,
        "alligator": result.alligator_ma,
        "indicators": result.indicators,
        "smc": result.smc,
        "invalidation": result.invalidation[:5],
        "warnings": result.warnings[:5],
        "status": "READY" if result.direction in ("UP", "DOWN") and result.confidence >= threshold else "NO_TRADE",
    }
