"""ExpertOption-native strategy checks.

Every entry below corresponds to an indicator or strategy that ExpertOption
documents in its own education section.  Each function returns at most one
signal so correlated readouts are never counted twice.
"""
from __future__ import annotations

import pandas as pd

from engines.strategies.models import StrategySignal
from engines.technical.indicators import macd, rsi


def _signal(name: str, family: str, direction: str, score: float,
            reason: str, invalidation: str) -> StrategySignal:
    return StrategySignal(name, family, direction, float(score), reason, invalidation)


def _smma(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(alpha=1.0 / max(1, period), adjust=False).mean()


def alligator(frame: pd.DataFrame, atr: float) -> StrategySignal | None:
    """Bill Williams Alligator: jaw 13/8, teeth 8/5, lips 5/3."""
    if len(frame) < 40:
        return None
    median = (frame["high"] + frame["low"]) / 2.0
    jaw = _smma(median, 13).shift(8)
    teeth = _smma(median, 8).shift(5)
    lips = _smma(median, 5).shift(3)
    if not all(pd.notna(value.iloc[-1]) for value in (jaw, teeth, lips)):
        return None
    price = float(frame["close"].iloc[-1])
    j, t, l = float(jaw.iloc[-1]), float(teeth.iloc[-1]), float(lips.iloc[-1])
    gap = atr * 0.04
    if l > t + gap and t > j + gap and price > l:
        return _signal("Alligator", "trend", "UP", 9,
                       "Alligator lines open upward with price above the lips",
                       "lips cross below teeth")
    if l < t - gap and t < j - gap and price < l:
        return _signal("Alligator", "trend", "DOWN", 9,
                       "Alligator lines open downward with price below the lips",
                       "lips cross above teeth")
    return None


def parabolic_sar(frame: pd.DataFrame) -> StrategySignal | None:
    """Standard Wilder Parabolic SAR with 0.02 step and 0.2 maximum."""
    if len(frame) < 15:
        return None
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    closes = frame["close"].to_numpy(dtype=float)
    bull = closes[1] >= closes[0]
    sar = lows[0] if bull else highs[0]
    extreme = highs[0] if bull else lows[0]
    step, maximum = 0.02, 0.2
    af = step
    flips = -1
    for i in range(1, len(frame)):
        sar = sar + af * (extreme - sar)
        if bull:
            if lows[i] < sar:
                bull, sar, extreme, af = False, extreme, lows[i], step
                flips = i
            elif highs[i] > extreme:
                extreme, af = highs[i], min(maximum, af + step)
        else:
            if highs[i] > sar:
                bull, sar, extreme, af = True, extreme, highs[i], step
                flips = i
            elif lows[i] < extreme:
                extreme, af = lows[i], min(maximum, af + step)
    direction = "UP" if bull else "DOWN"
    fresh = flips >= len(frame) - 3
    reason = ("Parabolic SAR flipped bullish" if fresh and bull
              else "Parabolic SAR flipped bearish" if fresh
              else f"Parabolic SAR trend is {direction.lower()}")
    return _signal("Parabolic SAR", "trend_strength", direction, 8 if fresh else 5,
                   reason, f"SAR value {sar:.6f} reclaimed")


def aroon(frame: pd.DataFrame, period: int = 25) -> StrategySignal | None:
    if len(frame) < period + 1:
        return None
    window = frame.iloc[-period - 1:]
    high_idx = int(window["high"].to_numpy().argmax())
    low_idx = int(window["low"].to_numpy().argmin())
    up = 100.0 * (period - (len(window) - 1 - high_idx)) / period
    down = 100.0 * (period - (len(window) - 1 - low_idx)) / period
    if up >= 70 and up > down:
        return _signal("Aroon", "trend_strength", "UP", 7,
                       f"Aroon Up {up:.0f} above 70 and dominant",
                       f"Aroon Up falls below Aroon Down")
    if down >= 70 and down > up:
        return _signal("Aroon", "trend_strength", "DOWN", 7,
                       f"Aroon Down {down:.0f} above 70 and dominant",
                       f"Aroon Down falls below Aroon Up")
    return None


def fractals(frame: pd.DataFrame, atr: float) -> StrategySignal | None:
    """Bill Williams five-bar fractals; only closed, confirmed fractals."""
    if len(frame) < 10:
        return None
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    price = float(frame["close"].iloc[-1])
    up_level = down_level = None
    for i in range(len(frame) - 3, 1, -1):
        if up_level is None and highs[i] >= max(highs[i - 2:i + 3]):
            up_level = highs[i]
        if down_level is None and lows[i] <= min(lows[i - 2:i + 3]):
            down_level = lows[i]
        if up_level is not None and down_level is not None:
            break
    if up_level is not None and price > up_level and price - up_level <= atr * 1.5:
        return _signal("Fractals", "structure", "UP", 7,
                       f"price broke the confirmed fractal high {up_level:.6f}",
                       f"close back below {up_level:.6f}")
    if down_level is not None and price < down_level and down_level - price <= atr * 1.5:
        return _signal("Fractals", "structure", "DOWN", 7,
                       f"price broke the confirmed fractal low {down_level:.6f}",
                       f"close back above {down_level:.6f}")
    return None


def tweezers(frame: pd.DataFrame, atr: float) -> StrategySignal | None:
    if len(frame) < 3 or atr <= 0:
        return None
    prev, last = frame.iloc[-2], frame.iloc[-1]
    tolerance = max(atr * 0.12, abs(float(last["close"])) * 1e-5)
    prev_bear = float(prev["close"]) < float(prev["open"])
    last_bull = float(last["close"]) > float(last["open"])
    if prev_bear and last_bull and abs(float(prev["low"]) - float(last["low"])) <= tolerance:
        return _signal("Tweezers", "price_action", "UP", 6,
                       "bullish tweezers bottom at the same low",
                       f"close below {min(float(prev['low']), float(last['low'])):.6f}")
    prev_bull = float(prev["close"]) > float(prev["open"])
    last_bear = float(last["close"]) < float(last["open"])
    if prev_bull and last_bear and abs(float(prev["high"]) - float(last["high"])) <= tolerance:
        return _signal("Tweezers", "price_action", "DOWN", 6,
                       "bearish tweezers top at the same high",
                       f"close above {max(float(prev['high']), float(last['high'])):.6f}")
    return None


def three_methods(frame: pd.DataFrame, atr: float) -> StrategySignal | None:
    """Three-candle continuation: impulse, two insides, continuation close."""
    if len(frame) < 4 or atr <= 0:
        return None
    first, second, third = frame.iloc[-3], frame.iloc[-2], frame.iloc[-1]
    c1_open, c1_close = float(first["open"]), float(first["close"])
    c1_high, c1_low = float(first["high"]), float(first["low"])
    body = abs(c1_close - c1_open)
    if body < atr * 0.8:
        return None
    inside = (
        max(float(second["high"]), float(third["high"])) <= c1_high
        and min(float(second["low"]), float(third["low"])) >= c1_low
    )
    if not inside:
        return None
    if c1_close > c1_open and float(third["close"]) > (c1_open + c1_close) / 2:
        return _signal("Three Methods", "price_action", "UP", 6,
                       "bullish three-methods continuation pattern",
                       f"close below {c1_low:.6f}")
    if c1_close < c1_open and float(third["close"]) < (c1_open + c1_close) / 2:
        return _signal("Three Methods", "price_action", "DOWN", 6,
                       "bearish three-methods continuation pattern",
                       f"close above {c1_high:.6f}")
    return None


def v_bounce(frame: pd.DataFrame, ind: dict, atr: float) -> StrategySignal | None:
    """Sharp V reversal away from a nearby support/resistance level."""
    if len(frame) < 5 or atr <= 0:
        return None
    window = frame.iloc[-5:]
    last = frame.iloc[-1]
    low = float(window["low"].min())
    high = float(window["high"].max())
    close = float(last["close"])
    low_rebound = (close - low) / atr
    high_rebound = (high - close) / atr
    support = (ind.get("support") or [None])[0]
    resistance = (ind.get("resistance") or [None])[0]
    if (low_rebound >= 1.1 and close > float(last["open"])
            and support is not None and low - float(support) <= atr * 0.5):
        return _signal("V-Bounce", "price_action", "UP", 7,
                       "V-shaped rebound from support",
                       f"close below {low:.6f}")
    if (high_rebound >= 1.1 and close < float(last["open"])
            and resistance is not None and float(resistance) - high <= atr * 0.5):
        return _signal("V-Bounce", "price_action", "DOWN", 7,
                       "V-shaped rejection from resistance",
                       f"close above {high:.6f}")
    return None


def rsi_macd_reversal(frame: pd.DataFrame, rsi_series: pd.Series,
                      macd_hist: pd.Series) -> StrategySignal | None:
    """ExpertOption's RSI + MACD reversal: extreme RSI turning with MACD turn."""
    if len(frame) < 20 or len(rsi_series.dropna()) < 3:
        return None
    rsi_now, rsi_prev = float(rsi_series.iloc[-1]), float(rsi_series.iloc[-2])
    hist_now, hist_prev = float(macd_hist.iloc[-1]), float(macd_hist.iloc[-2])
    if rsi_prev <= 30 < rsi_now and hist_now > hist_prev and hist_now < 0:
        return _signal("RSI + MACD Reversal", "momentum", "UP", 8,
                       "RSI left oversold while MACD histogram turned up",
                       "RSI falls back below 30 or MACD histogram turns down")
    if rsi_prev >= 70 > rsi_now and hist_now < hist_prev and hist_now > 0:
        return _signal("RSI + MACD Reversal", "momentum", "DOWN", 8,
                       "RSI left overbought while MACD histogram turned down",
                       "RSI rises back above 70 or MACD histogram turns up")
    return None


def expertoption_signals(frame: pd.DataFrame, ind: dict) -> list[StrategySignal]:
    atr = float(ind.get("atr") or 0.0)
    if atr <= 0:
        return []
    close = frame["close"]
    _, _, hist = macd(close)
    candidates = [
        alligator(frame, atr),
        parabolic_sar(frame),
        aroon(frame),
        fractals(frame, atr),
        tweezers(frame, atr),
        three_methods(frame, atr),
        v_bounce(frame, ind, atr),
        rsi_macd_reversal(frame, rsi(close), hist),
    ]
    return [signal for signal in candidates if signal is not None]
