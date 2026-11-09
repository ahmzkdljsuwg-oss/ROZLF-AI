"""Technical indicators computed locally with pandas/numpy."""
from __future__ import annotations

import numpy as np
import pandas as pd

from providers.base import Candle


def frame_from_candles(candles: list[Candle]) -> pd.DataFrame:
    data = {
        "open": [c.open for c in candles],
        "high": [c.high for c in candles],
        "low": [c.low for c in candles],
        "close": [c.close for c in candles],
        "volume": [c.volume for c in candles],
    }
    frame = pd.DataFrame(data, index=pd.DatetimeIndex([c.time for c in candles], name="time"))
    return frame.sort_index()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    value = 100 - (100 / (1 + rs))
    return value.fillna(50.0)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(series, fast) - ema(series, slow)
    signal_line = ema(line, signal)
    return line, signal_line, line - signal_line


def bollinger(series: pd.Series, period: int = 20, deviations: float = 2.0):
    mid = sma(series, period)
    std = series.rolling(period).std(ddof=0)
    return mid, mid + deviations * std, mid - deviations * std


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False).mean()


def stochastic(frame: pd.DataFrame, k_period: int = 14, d_period: int = 3):
    lowest = frame["low"].rolling(k_period).min()
    highest = frame["high"].rolling(k_period).max()
    span = (highest - lowest).replace(0.0, np.nan)
    k = (100 * (frame["close"] - lowest) / span).fillna(50.0)
    d = k.rolling(d_period).mean().fillna(50.0)
    return k, d


def find_swings(frame: pd.DataFrame, window: int = 3) -> list[dict]:
    """Confirmed fractal swings: `window` lower/higher bars on each side."""
    highs = frame["high"].to_numpy()
    lows = frame["low"].to_numpy()
    swings: list[dict] = []
    for index in range(window, len(frame) - window):
        left_high = highs[index - window : index]
        right_high = highs[index + 1 : index + 1 + window]
        if highs[index] >= left_high.max() and highs[index] >= right_high.max():
            swings.append({"index": index, "price": float(highs[index]), "kind": "high"})
        left_low = lows[index - window : index]
        right_low = lows[index + 1 : index + 1 + window]
        if lows[index] <= left_low.min() and lows[index] <= right_low.min():
            swings.append({"index": index, "price": float(lows[index]), "kind": "low"})
    return swings


def support_resistance(frame: pd.DataFrame, atr_value: float, max_levels: int = 3) -> dict:
    swings = find_swings(frame)
    close = float(frame["close"].iloc[-1])
    tolerance = max(atr_value * 0.35, close * 1e-6)
    levels: list[dict] = []
    for swing in swings:
        merged = False
        for level in levels:
            if abs(level["price"] - swing["price"]) <= tolerance:
                level["touches"] += 1
                level["price"] = (level["price"] + swing["price"]) / 2
                merged = True
                break
        if not merged:
            levels.append({"price": swing["price"], "touches": 1})

    supports = sorted(
        (level for level in levels if level["price"] < close),
        key=lambda level: close - level["price"],
    )[:max_levels]
    resistances = sorted(
        (level for level in levels if level["price"] > close),
        key=lambda level: level["price"] - close,
    )[:max_levels]
    return {
        "support": [round(level["price"], 6) for level in supports],
        "resistance": [round(level["price"], 6) for level in resistances],
        "support_strength": [level["touches"] for level in supports],
        "resistance_strength": [level["touches"] for level in resistances],
    }


def detect_patterns(frame: pd.DataFrame) -> list[dict]:
    patterns: list[dict] = []
    if len(frame) < 3:
        return patterns
    rows = frame.iloc[-3:]
    prev, last = rows.iloc[-2], rows.iloc[-1]
    body = abs(last["close"] - last["open"])
    candle_range = max(last["high"] - last["low"], 1e-12)
    upper_wick = last["high"] - max(last["close"], last["open"])
    lower_wick = min(last["close"], last["open"]) - last["low"]

    if last["close"] > last["open"] and prev["close"] < prev["open"]:
        if last["close"] >= prev["open"] and last["open"] <= prev["close"]:
            patterns.append({"name": "Bullish Engulfing", "direction": "bullish"})
    if last["close"] < last["open"] and prev["close"] > prev["open"]:
        if last["close"] <= prev["open"] and last["open"] >= prev["close"]:
            patterns.append({"name": "Bearish Engulfing", "direction": "bearish"})
    if body / candle_range < 0.1:
        patterns.append({"name": "Doji", "direction": "neutral"})
    if lower_wick > body * 2 and upper_wick < body and last["close"] >= last["open"]:
        patterns.append({"name": "Hammer", "direction": "bullish"})
    if upper_wick > body * 2 and lower_wick < body and last["close"] <= last["open"]:
        patterns.append({"name": "Shooting Star", "direction": "bearish"})
    return patterns


def compute_indicators(frame: pd.DataFrame) -> dict:
    close = frame["close"]
    ema9 = ema(close, 9)
    ema21 = ema(close, 21)
    ema50 = ema(close, 50)
    ema200 = ema(close, 200)
    sma20 = sma(close, 20)
    rsi14 = rsi(close, 14)
    macd_line, macd_signal, macd_hist = macd(close)
    bb_mid, bb_upper, bb_lower = bollinger(close)
    atr14 = atr(frame, 14)
    stoch_k, stoch_d = stochastic(frame)
    sr = support_resistance(frame, float(atr14.iloc[-1] or 0.0))
    patterns = detect_patterns(frame)

    price = float(close.iloc[-1])
    atr_value = float(atr14.iloc[-1] or 0.0)
    atr_pct = (atr_value / price) * 100 if price else 0.0
    atr_series = (atr14 / close) * 100
    atr_percentile = float((atr_series < atr_pct).mean()) if atr_pct else 0.0

    if ema9.iloc[-1] > ema21.iloc[-1] > ema50.iloc[-1] and price > ema50.iloc[-1]:
        trend = "UP"
    elif ema9.iloc[-1] < ema21.iloc[-1] < ema50.iloc[-1] and price < ema50.iloc[-1]:
        trend = "DOWN"
    else:
        trend = "RANGE"
    trend_strength = min(1.0, abs(float(ema9.iloc[-1] - ema50.iloc[-1])) / atr_value) if atr_value else 0.0

    if atr_percentile >= 0.75:
        volatility = "HIGH"
    elif atr_percentile <= 0.25:
        volatility = "LOW"
    else:
        volatility = "NORMAL"

    rsi_value = float(rsi14.iloc[-1])
    if rsi_value > 55:
        momentum = "BULLISH"
    elif rsi_value < 45:
        momentum = "BEARISH"
    else:
        momentum = "NEUTRAL"

    return {
        "price": round(price, 8),
        "ema9": round(float(ema9.iloc[-1]), 8),
        "ema21": round(float(ema21.iloc[-1]), 8),
        "ema50": round(float(ema50.iloc[-1]), 8),
        "ema200": round(float(ema200.iloc[-1]), 8),
        "sma20": round(float(sma20.iloc[-1]), 8),
        "rsi": round(rsi_value, 2),
        "macd": round(float(macd_line.iloc[-1]), 8),
        "macd_signal": round(float(macd_signal.iloc[-1]), 8),
        "macd_hist": round(float(macd_hist.iloc[-1]), 8),
        "macd_hist_prev": round(float(macd_hist.iloc[-2]), 8),
        "bb_mid": round(float(bb_mid.iloc[-1]), 8),
        "bb_upper": round(float(bb_upper.iloc[-1]), 8),
        "bb_lower": round(float(bb_lower.iloc[-1]), 8),
        "bb_width_pct": round(
            ((float(bb_upper.iloc[-1]) - float(bb_lower.iloc[-1])) / price) * 100, 3
        ) if price else 0.0,
        "atr": round(atr_value, 8),
        "atr_pct": round(atr_pct, 3),
        "atr_percentile": round(atr_percentile, 2),
        "stoch_k": round(float(stoch_k.iloc[-1]), 2),
        "stoch_d": round(float(stoch_d.iloc[-1]), 2),
        "stoch_cross": (
            "BULLISH"
            if stoch_k.iloc[-1] > stoch_d.iloc[-1] and stoch_k.iloc[-2] <= stoch_d.iloc[-2]
            else "BEARISH"
            if stoch_k.iloc[-1] < stoch_d.iloc[-1] and stoch_k.iloc[-2] >= stoch_d.iloc[-2]
            else "NONE"
        ),
        "support": sr["support"],
        "resistance": sr["resistance"],
        "support_strength": sr["support_strength"],
        "resistance_strength": sr["resistance_strength"],
        "patterns": patterns,
        "trend": trend,
        "trend_strength": round(trend_strength, 3),
        "volatility": volatility,
        "momentum": momentum,
    }
