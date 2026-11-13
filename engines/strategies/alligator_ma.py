"""Williams Alligator + EMA 200 entry filter.

Standard Alligator settings (jaw 13/8, teeth 8/5, lips 5/3) on median price,
confirmed by the system's existing EMA 200 regime. Only closed candles are
accepted; the module never looks ahead.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

import pandas as pd

from engines.technical.indicators import adx, atr, ema
from engines.strategies.models import StrategySignal

MA_PERIOD = 200
TICK_SECONDS = 5
JAW, JAW_SHIFT = 13, 8
TEETH, TEETH_SHIFT = 8, 5
LIPS, LIPS_SHIFT = 5, 3
MIN_BODY_RATIO = 0.25


def _smma(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1.0 / max(1, period), adjust=False).mean()


@dataclass(slots=True)
class AlligatorMaAssessment:
    decision: str
    ma_type: str
    ma_direction: str
    ma_value: float | None
    price: float | None
    price_time: datetime | None
    alligator_state: str
    alligator_direction: str
    trend_strength: str
    adx: float | None
    bars: int
    reasons: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    invalidation: list[str] = field(default_factory=list)
    checks: dict = field(default_factory=dict)
    signature: str | None = None

    @property
    def action(self) -> str:
        return {"BUY": "UP", "SELL": "DOWN"}.get(self.decision, "NO TRADE")

    def as_dict(self) -> dict:
        data = asdict(self)
        if isinstance(data.get("price_time"), datetime):
            data["price_time"] = data["price_time"].isoformat()
        return data

    def as_signal(self) -> StrategySignal | None:
        if self.decision == "BUY":
            return StrategySignal(
                "Alligator + EMA 200", "trend", "UP", 12,
                "EMA 200 regime is bullish and the Alligator is awake and open upward "
                "with a confirmed bullish candle",
                "lips cross below teeth or price closes back below EMA 200",
            )
        if self.decision == "SELL":
            return StrategySignal(
                "Alligator + EMA 200", "trend", "DOWN", 12,
                "EMA 200 regime is bearish and the Alligator is awake and open downward "
                "with a confirmed bearish candle",
                "lips cross above teeth or price closes back above EMA 200",
            )
        return None


def _strength(adx_value: float, distance_atr: float, separation_atr: float) -> str:
    points = 0
    if adx_value >= 30:
        points += 2
    elif adx_value >= 20:
        points += 1
    if distance_atr >= 0.75:
        points += 1
    if separation_atr >= 0.10:
        points += 1
    if points >= 3:
        return "STRONG"
    if points >= 1:
        return "MODERATE"
    return "WEAK"


def assess_alligator_ma(
    frame: pd.DataFrame,
    *,
    asset_key: str = "",
    timeframe: str = "",
    now: datetime | None = None,
) -> AlligatorMaAssessment:
    """Evaluate closed candles only. `frame` must contain no forming candle."""
    bars = len(frame)
    if bars < MA_PERIOD:
        return AlligatorMaAssessment(
            decision="NO TRADE", ma_type="EMA 200", ma_direction="UNKNOWN",
            ma_value=None, price=None, price_time=None,
            alligator_state="UNKNOWN", alligator_direction="UNKNOWN",
            trend_strength="UNKNOWN", adx=None, bars=bars,
            blockers=[f"Only {bars} closed candles; EMA 200 needs {MA_PERIOD}"],
        )

    close = frame["close"]
    median = (frame["high"] + frame["low"]) / 2.0
    ma_series = ema(close, MA_PERIOD)
    atr_series = atr(frame)
    adx_line, _, _ = adx(frame)
    jaw = _smma(median, JAW).shift(JAW_SHIFT)
    teeth = _smma(median, TEETH).shift(TEETH_SHIFT)
    lips = _smma(median, LIPS).shift(LIPS_SHIFT)

    price = float(close.iloc[-1])
    price_time = frame.index[-1]
    if now is not None and price_time.tzinfo is None:
        price_time = price_time.replace(tzinfo=now.tzinfo) if now.tzinfo else price_time
    ma_value = float(ma_series.iloc[-1])
    atr_value = float(atr_series.iloc[-1] or 0.0)
    adx_value = float(adx_line.iloc[-1] or 0.0)
    gap = max(atr_value * 0.03, price * 1e-7)
    j, t, l = float(jaw.iloc[-1]), float(teeth.iloc[-1]), float(lips.iloc[-1])
    j_prev = float(jaw.iloc[-2])
    l_prev = float(lips.iloc[-2])
    bullish_order = l > t + gap and t > j + gap
    bearish_order = l < t - gap and t < j - gap
    jaw_rising = j > j_prev
    jaw_falling = j < j_prev
    awake = (bullish_order and jaw_rising) or (bearish_order and jaw_falling)
    state = "AWAKE" if awake else "SLEEPING"
    alligator_direction = "BULLISH" if bullish_order and jaw_rising else "BEARISH" if bearish_order and jaw_falling else "NEUTRAL"
    ma_direction = "UP" if price > ma_value else "DOWN" if price < ma_value else "FLAT"

    last = frame.iloc[-1]
    prev = frame.iloc[-2]
    candle_range = max(float(last["high"] - last["low"]), 1e-12)
    body_ratio = abs(float(last["close"] - last["open"])) / candle_range
    bullish_candle = last["close"] > last["open"] and body_ratio >= MIN_BODY_RATIO
    bearish_candle = last["close"] < last["open"] and body_ratio >= MIN_BODY_RATIO
    bearish_engulf = (
        last["close"] < last["open"] and prev["close"] > prev["open"]
        and last["open"] >= prev["close"] and last["close"] <= prev["open"]
    )
    bullish_engulf = (
        last["close"] > last["open"] and prev["close"] < prev["open"]
        and last["open"] <= prev["close"] and last["close"] >= prev["open"]
    )

    distance_atr = abs(price - ma_value) / atr_value if atr_value else 0.0
    separation_atr = (max(j, t, l) - min(j, t, l)) / atr_value if atr_value else 0.0
    strength = _strength(adx_value, distance_atr, separation_atr)
    checks = {
        "ma_bars": bars >= MA_PERIOD,
        "ma_direction": ma_direction,
        "alligator_order": "UP" if bullish_order else "DOWN" if bearish_order else "FLAT",
        "jaw_slope": "UP" if jaw_rising else "DOWN" if jaw_falling else "FLAT",
        "lips_prev": l_prev,
        "body_ratio": round(body_ratio, 3),
        "adx": round(adx_value, 1),
        "distance_atr": round(distance_atr, 3),
        "separation_atr": round(separation_atr, 3),
    }

    decision = "NO TRADE"
    reasons: list[str] = []
    blockers: list[str] = []
    invalidation: list[str] = []

    if not awake:
        blockers.append("Alligator is sleeping or its lines are entangled/flat")
    elif ma_direction == "FLAT":
        blockers.append("Price is exactly at EMA 200")
    elif ma_direction == "UP" and alligator_direction != "BULLISH":
        blockers.append("EMA 200 points up but the Alligator does not confirm it")
    elif ma_direction == "DOWN" and alligator_direction != "BEARISH":
        blockers.append("EMA 200 points down but the Alligator does not confirm it")
    elif ma_direction == "UP":
        if bearish_engulf:
            blockers.append("Last closed candle is a bearish engulfing rejection")
        elif not bullish_candle:
            blockers.append("Waiting for a completed bullish confirmation candle")
        elif price < l:
            blockers.append("Price closed below the Alligator lips")
        else:
            decision = "BUY"
            reasons = [
                f"Price {price:.6f} is above EMA 200 ({ma_value:.6f})",
                "Alligator is awake: Lips > Teeth > Jaw with jaw rising",
                f"Trend strength {strength} (ADX {adx_value:.1f})",
                "Last closed candle confirms bullish momentum",
            ]
            invalidation = [
                "lips cross below teeth",
                "price closes back below EMA 200",
                "a completed bearish engulfing candle appears",
            ]
    else:
        if bullish_engulf:
            blockers.append("Last closed candle is a bullish engulfing rejection")
        elif not bearish_candle:
            blockers.append("Waiting for a completed bearish confirmation candle")
        elif price > l:
            blockers.append("Price closed above the Alligator lips")
        else:
            decision = "SELL"
            reasons = [
                f"Price {price:.6f} is below EMA 200 ({ma_value:.6f})",
                "Alligator is awake: Lips < Teeth < Jaw with jaw falling",
                f"Trend strength {strength} (ADX {adx_value:.1f})",
                "Last closed candle confirms bearish momentum",
            ]
            invalidation = [
                "lips cross above teeth",
                "price closes back above EMA 200",
                "a completed bullish engulfing candle appears",
            ]

    candle_time = frame.index[-1]
    signature = f"{asset_key}:{timeframe}:{candle_time}:{decision}" if asset_key or timeframe else None
    return AlligatorMaAssessment(
        decision=decision, ma_type="EMA 200", ma_direction=ma_direction,
        ma_value=round(ma_value, 8), price=round(price, 8), price_time=price_time,
        alligator_state=state, alligator_direction=alligator_direction,
        trend_strength=strength, adx=round(adx_value, 1), bars=bars,
        reasons=reasons, blockers=blockers, invalidation=invalidation,
        checks=checks, signature=signature,
    )


class AlligatorSignalGate:
    """Suppress an identical signal until a new body confirms it again."""

    def __init__(self) -> None:
        self._last: dict[str, str] = {}

    def should_emit(self, asset_key: str, assessment: AlligatorMaAssessment) -> bool:
        if assessment.decision not in ("BUY", "SELL"):
            return False
        key = assessment.signature or f"{asset_key}:{assessment.decision}"
        if self._last.get(asset_key) == key:
            return False
        self._last[asset_key] = key
        return True
