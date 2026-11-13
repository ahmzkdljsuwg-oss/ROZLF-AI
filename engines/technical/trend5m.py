"""Strict confirmation layer for five-minute trend trades.

This module never creates a direction of its own. It validates an existing
candidate against trend, structure, volatility and the last closed candle, and
returns blockers when the evidence is mixed or the entry candle is stale.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from engines.markets import MarketProfile
from engines.strategies.models import StrategyReport
from engines.technical.indicators import bollinger, find_swings
from providers.base import MarketData

MODE_SECONDS = 300
_MAX_SIGNAL_DELAY = 45.0


@dataclass(slots=True)
class Trend5mAssessment:
    trend_direction: str = "RANGE"
    trend_strength: str = "WEAK"
    structure: str = "MIXED"
    volatility: str = "NORMAL"
    volatility_state: str = "NORMAL"
    candle: dict = field(default_factory=dict)
    checks: dict = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    @property
    def entry_ok(self) -> bool:
        return not self.blockers

    def as_dict(self) -> dict:
        return {
            "mode": "5M TREND",
            "trend": self.trend_direction,
            "trend_strength": self.trend_strength,
            "structure": self.structure,
            "volatility": self.volatility,
            "volatility_state": self.volatility_state,
            "candle": self.candle,
            "checks": self.checks,
            "blockers": self.blockers,
            "entry_ok": self.entry_ok,
        }


def _bb_width_percentile(frame: pd.DataFrame) -> float:
    close = frame["close"]
    _, upper, lower = bollinger(close)
    widths = ((upper - lower) / close.replace(0.0, float("nan"))).dropna()
    if widths.empty:
        return 0.5
    last = float(widths.iloc[-1])
    return float((widths < last).mean())


def _volatility_shape(frame: pd.DataFrame) -> tuple[float, float]:
    """Recent range and band width versus their own recent baseline.

    A steady trend lifts both measures, so a multiple (not a percentile) is used
    to separate routine trend expansion from genuinely abnormal volatility.
    """
    ranges = (frame["high"] - frame["low"]).astype(float)
    recent_range = float(ranges.iloc[-14:].mean())
    baseline_range = float(ranges.iloc[-74:-14].median()) if len(ranges) > 74 else float(ranges.median())
    range_ratio = recent_range / baseline_range if baseline_range > 0 else 1.0

    close = frame["close"]
    _, upper, lower = bollinger(close)
    widths = ((upper - lower) / close.replace(0.0, float("nan"))).dropna()
    if len(widths) > 74:
        recent_width = float(widths.iloc[-14:].mean())
        baseline_width = float(widths.iloc[-74:-14].median())
    else:
        recent_width = float(widths.iloc[-14:].mean()) if len(widths) else 0.0
        baseline_width = float(widths.median()) if len(widths) else 0.0
    width_ratio = recent_width / baseline_width if baseline_width > 0 else 1.0
    return range_ratio, width_ratio


def _market_structure(frame: pd.DataFrame, fallback: str) -> tuple[str, str]:
    swings = find_swings(frame, window=2)
    highs = [swing for swing in swings if swing["kind"] == "high"][-2:]
    lows = [swing for swing in swings if swing["kind"] == "low"][-2:]
    if len(highs) == 2 and len(lows) == 2:
        higher_high = highs[-1]["price"] > highs[-2]["price"]
        higher_low = lows[-1]["price"] > lows[-2]["price"]
        lower_high = highs[-1]["price"] < highs[-2]["price"]
        lower_low = lows[-1]["price"] < lows[-2]["price"]
        if higher_high and higher_low:
            return "HH/HL", "UP"
        if lower_high and lower_low:
            return "LH/LL", "DOWN"
        if higher_high or higher_low:
            return "MIXED (higher highs/lows)", "MIXED"
        if lower_high or lower_low:
            return "MIXED (lower highs/lows)", "MIXED"
    if fallback == "BULLISH":
        return "BULLISH (swings sparse)", "UP"
    if fallback == "BEARISH":
        return "BEARISH (swings sparse)", "DOWN"
    return "MIXED", "MIXED"


def _candle_confirmation(frame: pd.DataFrame, direction: str) -> tuple[dict, str | None]:
    if len(frame) < 2:
        return {"name": "NONE"}, "No closed candle is available for confirmation"
    last = frame.iloc[-1]
    previous = frame.iloc[-2]
    open_price = float(last["open"])
    close = float(last["close"])
    high = float(last["high"])
    low = float(last["low"])
    span = max(high - low, 1e-12)
    body = abs(close - open_price)
    upper_wick = high - max(open_price, close)
    lower_wick = min(open_price, close) - low
    bullish = close > open_price
    body_ratio = body / span
    candle_direction = "UP" if bullish else "DOWN" if close < open_price else "RANGE"

    previous_open = float(previous["open"])
    previous_close = float(previous["close"])
    bullish_engulfing = (
        bullish
        and previous_close < previous_open
        and close >= previous_open
        and open_price <= previous_close
    )
    bearish_engulfing = (
        not bullish
        and previous_close > previous_open
        and close <= previous_open
        and open_price >= previous_close
    )
    bullish_pin = lower_wick >= body * 2.0 and upper_wick <= body and body_ratio <= 0.38
    bearish_pin = upper_wick >= body * 2.0 and lower_wick <= body and body_ratio <= 0.38
    rejection = (
        (lower_wick / span >= 0.45 and body_ratio <= 0.45)
        if direction == "UP"
        else (upper_wick / span >= 0.45 and body_ratio <= 0.45)
    )
    prior_high = float(frame["high"].iloc[-21:-1].max()) if len(frame) > 21 else high
    prior_low = float(frame["low"].iloc[-21:-1].min()) if len(frame) > 21 else low
    breakout = (direction == "UP" and close > prior_high) or (
        direction == "DOWN" and close < prior_low
    )
    false_breakout = (
        direction == "UP" and high > prior_high and close < prior_high
    ) or (
        direction == "DOWN" and low < prior_low and close > prior_low
    )
    strong_body = body_ratio >= 0.5 and candle_direction == direction
    aligned_pattern = (
        (direction == "UP" and (bullish_engulfing or bullish_pin or rejection))
        or (direction == "DOWN" and (bearish_engulfing or bearish_pin or rejection))
    )
    confirmation = strong_body or aligned_pattern or breakout

    details = {
        "name": "NONE",
        "direction": candle_direction,
        "body_ratio": round(body_ratio, 3),
        "upper_wick_ratio": round(upper_wick / span, 3),
        "lower_wick_ratio": round(lower_wick / span, 3),
        "engulfing": bullish_engulfing or bearish_engulfing,
        "pin_bar": bullish_pin or bearish_pin,
        "rejection": rejection,
        "breakout": breakout,
        "false_breakout": false_breakout,
        "strong_body": strong_body,
        "confirmation": confirmation,
    }
    names = []
    if bullish_engulfing or bearish_engulfing:
        names.append("Engulfing")
    if bullish_pin or bearish_pin:
        names.append("Pin Bar")
    if rejection:
        names.append("Wick Rejection")
    if breakout:
        names.append("Breakout")
    if strong_body and not names:
        names.append("Strong Body")
    details["name"] = " + ".join(names) if names else "NONE"

    if false_breakout:
        return details, "The last closed candle rejected a breakout"
    if candle_direction not in (direction, "RANGE") and body_ratio >= 0.55:
        return details, f"The last closed candle closed {candle_direction} against the setup"
    if not confirmation:
        return details, "No aligned candle confirmation (body, rejection, engulfing or breakout)"
    return details, None


def assess_trend_5m(
    frame: pd.DataFrame,
    ind: dict,
    smc: dict,
    report: StrategyReport,
    market_data: MarketData,
    now: datetime,
    profile: MarketProfile,
    direction: str,
) -> Trend5mAssessment:
    """Validate a UP/DOWN candidate for a fixed five-minute expiry."""
    assessment = Trend5mAssessment()
    if direction not in ("UP", "DOWN"):
        assessment.blockers.append("No directional candidate exists to validate")
        return assessment

    price = float(ind["price"])
    atr = float(ind.get("atr") or price * 1e-5)
    tf_seconds = market_data.timeframe.seconds
    last_close = frame.index[-1].to_pydatetime() + pd.Timedelta(seconds=tf_seconds)
    candle_age = (now - last_close).total_seconds()
    max_delay = max(_MAX_SIGNAL_DELAY, tf_seconds * 0.75)
    if candle_age > max_delay:
        assessment.blockers.append(
            f"Signal candle is stale ({int(candle_age)}s old); a late entry is refused"
        )

    ema9 = float(ind["ema9"])
    ema21 = float(ind["ema21"])
    ema50 = float(ind["ema50"])
    ema200 = ind.get("ema200")
    bullish = direction == "UP"
    stack_up = ema9 > ema21 > ema50 and price > ema50 and (
        ema200 in (None, 0) or ema50 > float(ema200)
    )
    stack_down = ema9 < ema21 < ema50 and price < ema50 and (
        ema200 in (None, 0) or ema50 < float(ema200)
    )
    ema_aligned = stack_up if bullish else stack_down
    if not ema_aligned:
        assessment.blockers.append("EMA 9/21/50 stack does not confirm the direction")
    assessment.checks["ema_aligned"] = ema_aligned
    assessment.checks["ema200_available"] = ema200 not in (None, 0)

    structure_label, structure_direction = _market_structure(frame, smc.get("trend", "MIXED"))
    assessment.structure = structure_label
    structure_supports = structure_direction == direction
    structure_opposes = structure_direction in ("UP", "DOWN") and structure_direction != direction
    assessment.checks["structure_supports"] = structure_supports

    adx_value = float(report.context.get("adx", 0.0))
    plus_di = float(report.context.get("plus_di", 0.0))
    minus_di = float(report.context.get("minus_di", 0.0))
    di_match = (plus_di > minus_di) if bullish else (minus_di > plus_di)
    if adx_value >= 30 and di_match:
        assessment.trend_strength = "STRONG"
    elif adx_value >= 22 and di_match:
        assessment.trend_strength = "MODERATE"
    else:
        assessment.trend_strength = "WEAK"
    strong_trend = assessment.trend_strength == "STRONG"
    assessment.checks["adx"] = round(adx_value, 1)
    assessment.checks["di_match"] = di_match

    if structure_opposes:
        assessment.blockers.append(f"Market structure {structure_label} opposes the setup")
    elif not structure_supports and not (strong_trend and di_match):
        assessment.blockers.append(
            "Market structure is mixed and the trend is not strong enough to override it"
        )

    if adx_value < 18 or not di_match:
        assessment.blockers.append(
            f"ADX {adx_value:.1f} does not confirm a directional trend"
        )

    macd_hist = float(ind.get("macd_hist") or 0.0)
    macd_prev = float(ind.get("macd_hist_prev") or 0.0)
    macd_matches = (macd_hist > 0) if bullish else (macd_hist < 0)
    macd_rising = macd_hist > macd_prev if bullish else macd_hist < macd_prev
    assessment.checks["macd_momentum"] = macd_matches
    if not macd_matches:
        assessment.blockers.append("MACD momentum does not confirm the direction")

    rsi = float(ind.get("rsi") or 50.0)
    rsi_ok = (50.0 < rsi < 78.0) if bullish else (22.0 < rsi < 50.0)
    assessment.checks["rsi_confirmation"] = rsi_ok
    if not rsi_ok:
        assessment.blockers.append(
            f"RSI {rsi:.1f} is not a safe confirmation for a five-minute entry"
        )

    atr_percentile = float(ind.get("atr_percentile") or 0.5)
    bb_percentile = _bb_width_percentile(frame)
    range_ratio, width_ratio = _volatility_shape(frame)
    if range_ratio >= 2.5 or width_ratio >= 2.5:
        assessment.volatility = "EXTREME"
        assessment.volatility_state = "EXPANSION"
        assessment.blockers.append("Volatility is extreme; a five-minute entry is unsafe")
    elif range_ratio <= 0.55 and width_ratio <= 0.6:
        assessment.volatility = "LOW"
        assessment.volatility_state = "COMPRESSION"
    elif range_ratio >= 1.5 or width_ratio >= 1.5:
        assessment.volatility = "HIGH"
        assessment.volatility_state = "EXPANSION"
    else:
        assessment.volatility = "NORMAL"
        assessment.volatility_state = "NORMAL"

    if adx_value < 16 and width_ratio < 0.9:
        assessment.volatility = "CHOPPY"
        assessment.blockers.append("Random chop: ADX and band width show no usable trend")

    candle, candle_blocker = _candle_confirmation(frame, direction)
    assessment.candle = candle
    assessment.checks["candle_confirmed"] = bool(candle.get("confirmation"))
    if candle_blocker:
        assessment.blockers.append(candle_blocker)

    resistances = ind.get("resistance") or []
    supports = ind.get("support") or []
    level = resistances[0] if bullish and resistances else supports[0] if not bullish and supports else None
    if level is not None and not candle.get("breakout"):
        distance = abs(float(level) - price) / atr
        assessment.checks["distance_to_level_atr"] = round(distance, 2)
        if distance < 0.30:
            assessment.blockers.append(
                "Price is pressed against the opposing level without a breakout"
            )

    if not assessment.blockers:
        assessment.reasons = [
            f"EMA 9/21/50 aligned {'upward' if bullish else 'downward'}"
            + (" with EMA200" if assessment.checks["ema200_available"] else ""),
            f"Market structure {structure_label}",
            f"ADX {adx_value:.1f} ({assessment.trend_strength}) with "
            f"{'bullish' if bullish else 'bearish'} DI",
            f"MACD momentum {'positive' if bullish else 'negative'}"
            + (" and expanding" if macd_rising else ""),
            f"Candle confirmation: {candle['name']}",
        ]
    assessment.trend_direction = direction if not assessment.blockers else "RANGE"
    assessment.checks["volatility_percentile"] = round(atr_percentile, 2)
    assessment.checks["bb_width_percentile"] = round(bb_percentile, 2)
    assessment.checks["range_ratio"] = round(range_ratio, 2)
    assessment.checks["width_ratio"] = round(width_ratio, 2)
    return assessment
