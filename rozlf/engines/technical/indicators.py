"""Deterministic technical indicators (no external TA dependency)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...providers.base import Candle


def to_frame(candles: list[Candle]) -> pd.DataFrame:
    df = pd.DataFrame([c.as_dict() for c in candles])
    df = df.drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    return df


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(100.0).where(avg_loss != 0, 100.0)


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": hist})


def bollinger(series: pd.Series, period: int = 20, mult: float = 2.0) -> pd.DataFrame:
    mid = sma(series, period)
    std = series.rolling(period, min_periods=period).std(ddof=0)
    return pd.DataFrame({"mid": mid, "upper": mid + mult * std, "lower": mid - mult * std, "width": (2 * mult * std) / mid})


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def stochastic(df: pd.DataFrame, k: int = 14, d: int = 3, smooth: int = 3) -> pd.DataFrame:
    low_min = df["low"].rolling(k, min_periods=k).min()
    high_max = df["high"].rolling(k, min_periods=k).max()
    raw = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.nan)
    k_line = raw.rolling(smooth, min_periods=smooth).mean()
    d_line = k_line.rolling(d, min_periods=d).mean()
    return pd.DataFrame({"k": k_line, "d": d_line})


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - df["close"].shift(1)).abs(), (df["low"] - df["close"].shift(1)).abs()],
        axis=1,
    ).max(axis=1)
    atr_s = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_s
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr_s
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def support_resistance(df: pd.DataFrame, lookback: int = 3, max_levels: int = 4) -> tuple[list[float], list[float]]:
    """Fractal pivots aggregated into the nearest support and resistance levels."""
    highs, lows = df["high"].tolist(), df["low"].tolist()
    piv_high: list[float] = []
    piv_low: list[float] = []
    for i in range(lookback, len(df) - lookback):
        window_h = highs[i - lookback : i + lookback + 1]
        window_l = lows[i - lookback : i + lookback + 1]
        if highs[i] == max(window_h):
            piv_high.append(highs[i])
        if lows[i] == min(window_l):
            piv_low.append(lows[i])

    price = float(df["close"].iloc[-1])
    resistance = sorted({round(v, 6) for v in piv_high if v > price})[:max_levels]
    support = sorted({round(v, 6) for v in piv_low if v < price}, reverse=True)[:max_levels]
    return support, resistance


def snapshot(candles: list[Candle]) -> dict:
    """One-shot indicator snapshot used by the analyzer and the bot UI."""
    df = to_frame(candles)
    if len(df) < 30:
        return {"ok": False, "reason": "شموع غير كافية لحساب المؤشرات."}
    close = df["close"]
    ind_rsi = rsi(close)
    macd_df = macd(close)
    bb = bollinger(close)
    atr_s = atr(df)
    stoch = stochastic(df)
    adx_s = adx(df)
    e9, e21, e50, e200 = ema(close, 9), ema(close, 21), ema(close, 50), ema(close, 200)
    s50 = sma(close, 50)
    support, resistance = support_resistance(df)

    last = -1
    price = float(close.iloc[last])
    atr_val = float(atr_s.iloc[last]) if not np.isnan(atr_s.iloc[last]) else 0.0
    return {
        "ok": True,
        "price": price,
        "bars": len(df),
        "time": int(df["time"].iloc[last]),
        "rsi": _f(ind_rsi.iloc[last]),
        "rsi_prev": _f(ind_rsi.iloc[last - 1]) if len(df) > 1 else None,
        "macd": _f(macd_df["macd"].iloc[last]),
        "macd_signal": _f(macd_df["signal"].iloc[last]),
        "macd_hist": _f(macd_df["hist"].iloc[last]),
        "macd_hist_prev": _f(macd_df["hist"].iloc[last - 1]) if len(df) > 1 else None,
        "bb_mid": _f(bb["mid"].iloc[last]),
        "bb_upper": _f(bb["upper"].iloc[last]),
        "bb_lower": _f(bb["lower"].iloc[last]),
        "bb_width": _f(bb["width"].iloc[last]),
        "atr": _f(atr_val),
        "atr_pct": _f(atr_val / price * 100 if price else None),
        "stoch_k": _f(stoch["k"].iloc[last]),
        "stoch_d": _f(stoch["d"].iloc[last]),
        "adx": _f(adx_s.iloc[last]),
        "ema9": _f(e9.iloc[last]),
        "ema21": _f(e21.iloc[last]),
        "ema50": _f(e50.iloc[last]),
        "ema200": _f(e200.iloc[last]),
        "sma50": _f(s50.iloc[last]),
        "support": support,
        "resistance": resistance,
        "volume": _f(df["volume"].iloc[last]),
        "volume_mean20": _f(df["volume"].tail(20).mean()),
        "has_volume": bool(df["volume"].abs().sum() > 0),
        "high": float(df["high"].iloc[last]),
        "low": float(df["low"].iloc[last]),
        "open": float(df["open"].iloc[last]),
    }


def _f(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if np.isnan(out) or np.isinf(out):
        return None
    return round(out, 6)
