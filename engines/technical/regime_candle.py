"""Experimental next-candle rules shared by live analysis and chronological replay."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

WARMUP = 220
# Scored after candle i closes, while i+1 is forming, for the future open of i+2.
TARGET_OFFSET = 2
RULE_VERSION = "smarty-regime-v1"


@dataclass(frozen=True)
class RegimeDecision:
    regime: str
    direction: str
    reason: str


def _smoothed(series: pd.Series, period: int) -> pd.Series:
    """A bounded Wilder smoother makes the live and replay windows equivalent."""
    weights = (1 - 1 / period) ** np.arange(period * 5 - 1, -1, -1, dtype=float)
    return series.rolling(len(weights)).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


def regime_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Every row only uses information through the close of that row."""
    close, open_, high, low = (frame[k] for k in ("close", "open", "high", "low"))
    prev = close.shift()
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().replace(0, np.nan)
    atr_ref = atr.shift().rolling(96).median().replace(0, np.nan)
    net = close.diff(20)
    travel = close.diff().abs().rolling(20).sum().replace(0, np.nan)
    mid = (high + low) / 2
    lower = low.shift().rolling(20).min()
    upper = high.shift().rolling(20).max()
    ma = close.rolling(200).mean()
    candle_range = (high - low).replace(0, np.nan)
    return pd.DataFrame({
        "volatility": atr / atr_ref,
        "shock": tr / atr.shift(),
        "efficiency": (net / travel).abs(),
        "bias": (close - ma) / atr,
        "ma_slope": ma.diff(5) / atr,
        "jaw": _smoothed(mid, 13).shift(8),
        "teeth": _smoothed(mid, 8).shift(5),
        "lips": _smoothed(mid, 5).shift(3),
        "body": (close - open_) / atr,
        "placement": (close - low) / candle_range,
        "short_momentum": close.diff(3) / atr,
        "sweep_low": (low < lower) & (close > lower),
        "sweep_high": (high > upper) & (close < upper),
        "extension_up": (close - upper) / atr,
        "extension_down": (lower - close) / atr,
    }, index=frame.index)


def decide_regime(row: Mapping) -> RegimeDecision:
    if not np.isfinite([row[k] for k in ("volatility", "shock", "efficiency", "bias", "ma_slope",
                                          "jaw", "teeth", "lips", "body", "placement",
                                          "short_momentum", "extension_up", "extension_down")]).all():
        return RegimeDecision("UNREADY", "NO TRADE", "غير كافية لتصنيف السوق")
    if row["volatility"] > 1.6 or row["shock"] > 2.6:
        return RegimeDecision("VOLATILE", "NO TRADE", "التذبذب أو حجم الشمعة أعلى من المعتاد")
    if row["efficiency"] >= 0.28:
        up = (row["lips"] > row["teeth"] > row["jaw"] and row["bias"] > 0
              and row["ma_slope"] > 0 and row["short_momentum"] > 0
              and row["body"] >= 0.18 and row["placement"] >= 0.65
              and row["extension_up"] <= 0.8 and not row["sweep_high"])
        down = (row["lips"] < row["teeth"] < row["jaw"] and row["bias"] < 0
                and row["ma_slope"] < 0 and row["short_momentum"] < 0
                and row["body"] <= -0.18 and row["placement"] <= 0.35
                and row["extension_down"] <= 0.8 and not row["sweep_low"])
        return RegimeDecision("TREND", "UP" if up else "DOWN" if down else "NO TRADE",
                              "استمرار الترند مع المتوسط 200 والتمساح والزخم"
                              if up or down else "الترند ما اتفق مع حركة آخر شمعة")
    if row["efficiency"] <= 0.20:
        up = row["sweep_low"] and not row["sweep_high"] and row["placement"] >= 0.65 and row["body"] > 0
        down = row["sweep_high"] and not row["sweep_low"] and row["placement"] <= 0.35 and row["body"] < 0
        return RegimeDecision("RANGE", "UP" if up else "DOWN" if down else "NO TRADE",
                              "رفض اختراق طرف النطاق" if up or down else "حركة عرضية بدون ارتداد مؤكد")
    return RegimeDecision("MIXED", "NO TRADE", "ما فيه اتجاه أو نطاق واضح")


def contiguous_tail(frame: pd.DataFrame, seconds: int) -> bool:
    """The feature window may not jump across missing candle intervals."""
    if len(frame) < WARMUP:
        return False
    tail = frame.index[-WARMUP:]
    return bool((tail[1:] - tail[:-1] == pd.Timedelta(seconds=seconds)).all())


def diagnose_regime(frame: pd.DataFrame, seconds: int) -> RegimeDecision:
    if not contiguous_tail(frame, seconds):
        return RegimeDecision("UNREADY", "NO TRADE", "الشموع المتتالية غير كافية لتصنيف السوق")
    return decide_regime(regime_features(frame.tail(WARMUP)).iloc[-1])
