"""Next-candle forecast built only from information available before the bar opens.

The score is a sum of independent, inspectable components (trend, structure,
momentum, location, volatility, price action). Direction is never taken from a
future bar: every feature at index ``i`` uses rows ``0..i`` only.

Confidence is not the raw score. It is the empirical hit rate of the same score
bucket measured by a walk-forward backtest (``scripts/backtest_next_candle.py``)
and stored in ``calibration.json``. When no calibrated bucket exists the module
returns NO TRADE instead of an invented percentage.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

CALIBRATION_PATH = Path(__file__).with_name("calibration.json")
MIN_CALIBRATION_SAMPLES = 30
DEFAULT_BINS = (0.0, 4.0, 8.0, 12.0, 16.0, 20.0, 26.0, 34.0, 46.0, 64.0, 100.0)


@dataclass(slots=True)
class NextCandleForecast:
    direction: str
    raw_score: float
    probability_up: float | None
    confidence: float | None
    reasons: list[str]
    components: dict[str, float]
    target_open_at: datetime
    horizon_seconds: int
    calibration: str
    blockers: list[str] = field(default_factory=list)
    verified: bool = False

    @property
    def actionable(self) -> bool:
        return self.direction in ("UP", "DOWN") and self.confidence is not None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["target_open_at"] = self.target_open_at.isoformat()
        return data


def _sigmoid(value: float, scale: float = 9.0) -> float:
    return 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, value / scale))))


def _series(frame: pd.DataFrame) -> dict[str, pd.Series]:
    close = frame["close"]
    high = frame["high"]
    low = frame["low"]
    open_ = frame["open"]
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0.0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0.0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = 100 - (100 / (1 + gain / loss.replace(0.0, np.nan)))
    rsi = rsi.fillna(50.0)
    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_hist = macd_line - macd_line.ewm(span=9, adjust=False).mean()
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean()
    mid = close.rolling(20).mean()
    std = close.rolling(20).std(ddof=0)
    bb_upper, bb_lower = mid + 2 * std, mid - 2 * std
    lowest = low.rolling(14).min()
    highest = high.rolling(14).max()
    stoch_k = (100 * (close - lowest) / (highest - lowest).replace(0.0, np.nan)).fillna(50.0)
    stoch_d = stoch_k.rolling(3).mean().fillna(50.0)
    rolling_high = high.rolling(20).max().shift(1)
    rolling_low = low.rolling(20).min().shift(1)
    body = close - open_
    candle_range = (high - low).replace(0.0, np.nan)
    return {
        "close": close, "open": open_, "high": high, "low": low,
        "ema9": ema9, "ema21": ema21, "ema50": ema50, "ema200": ema200,
        "rsi": rsi, "macd_hist": macd_hist, "atr": atr,
        "bb_upper": bb_upper, "bb_lower": bb_lower, "stoch_k": stoch_k,
        "stoch_d": stoch_d, "rolling_high": rolling_high, "rolling_low": rolling_low,
        "body": body, "range": candle_range,
    }


def score_at(frame: pd.DataFrame, arrays: dict[str, pd.Series] | None = None,
             index: int | None = None) -> tuple[float, dict[str, float]]:
    """Return the signed next-candle score and its components at ``index``."""
    index = -1 if index is None else index
    a = arrays or _series(frame)

    def at(name: str, offset: int = 0) -> float:
        value = a[name].iloc[index - offset]
        return float(value) if pd.notna(value) else 0.0

    price = at("close")
    atr = max(at("atr"), price * 1e-8)
    ema9, ema21, ema50, ema200 = at("ema9"), at("ema21"), at("ema50"), at("ema200")
    ema9_prev = at("ema9", 1)
    ema21_prev = at("ema21", 1)
    rsi = at("rsi")
    macd_hist = at("macd_hist") / atr
    stoch_k, stoch_d = at("stoch_k"), at("stoch_d")
    high, low = at("high"), at("low")
    open_ = at("open")
    range_ = max(at("range"), price * 1e-8)
    body = at("body")
    close_pos = (price - low) / range_ * 2 - 1
    upper, lower = at("bb_upper"), at("bb_lower")
    bb_pos = (price - lower) / max(upper - lower, 1e-12) * 2 - 1
    roll_high, roll_low = at("rolling_high"), at("rolling_low")

    trend = 0.0
    if ema9 > ema21 > ema50 and price > ema200:
        trend += 6.0
    elif ema9 < ema21 < ema50 and price < ema200:
        trend -= 6.0
    trend += max(-4.0, min(4.0, ((ema9 - ema9_prev) + (ema21 - ema21_prev)) / atr * 5))
    momentum = max(-3.0, min(3.0, (rsi - 50) / 12))
    momentum += max(-3.0, min(3.0, macd_hist * 6))
    momentum += 1.5 if stoch_k > stoch_d + 4 else -1.5 if stoch_k < stoch_d - 4 else 0.0
    price_action = max(-4.0, min(4.0, (body / range_) * 4))
    price_action += 1.5 if high > roll_high else -1.5 if low < roll_low else 0.0
    location = -max(-3.0, min(3.0, bb_pos * 2))
    if rsi >= 72:
        location -= 2.0
    elif rsi <= 28:
        location += 2.0
    if bb_pos > 1.1:
        location -= 2.0
    elif bb_pos < -1.1:
        location += 2.0
    close_pressure = max(-2.0, min(2.0, close_pos * 2))
    volatility = 0.0
    if atr / price > 0.002 and abs(momentum) > 2:
        volatility = 1.0 if momentum > 0 else -1.0

    components = {
        "trend": round(trend, 3),
        "momentum": round(momentum, 3),
        "price_action": round(price_action, 3),
        "location": round(location, 3),
        "close_pressure": round(close_pressure, 3),
        "volatility": round(volatility, 3),
    }
    return round(sum(components.values()), 4), components


def load_calibration(path: Path | str | None = None) -> dict[str, Any]:
    path = Path(path) if path is not None else CALIBRATION_PATH
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _table_for(cal: dict[str, Any], market: str, timeframe: str) -> tuple[dict[str, Any] | None, str]:
    markets = cal.get("markets") or {}
    for key in (market, market.lower()):
        table = (markets.get(key) or {}).get(timeframe)
        if table and table.get("bins"):
            return table, f"{key}/{timeframe}"
    return None, "none"


def enabled_frames(market: str, calibration: dict[str, Any] | None = None) -> list[str]:
    """Frames whose walk-forward edge passed the stored out-of-sample gate."""
    cal = calibration or load_calibration()
    tables = (cal.get("markets") or {}).get(market.lower()) or {}
    order = ("5sec", "15sec", "30sec", "1min", "2min", "3min", "5min", "15min", "30min", "1h")
    return [frame for frame in order if (tables.get(frame) or {}).get("enabled")]


def forecast_frames(market: str, profile_frames: tuple[str, ...],
                    calibration: dict[str, Any] | None = None) -> tuple[str, ...]:
    enabled = [frame for frame in enabled_frames(market, calibration) if frame in profile_frames]
    return tuple(enabled[:3]) or tuple(profile_frames[:3])


def _bin_for(table: dict[str, Any], score: float) -> dict[str, Any] | None:
    for bucket in table.get("bins", []):
        if bucket["low"] <= abs(score) < bucket["high"]:
            if bucket.get("n", 0) >= MIN_CALIBRATION_SAMPLES:
                return bucket
            return None
    return None


def _technical_forecast(score: float, components: dict[str, float], target: datetime,
                        timeframe_seconds: int, blockers: list[str]) -> NextCandleForecast:
    """Legacy raw-score baseline retained only for historical comparisons."""
    directional = {name: value for name, value in components.items() if name != "volatility"}
    agreeing = sum(1 for value in directional.values() if value * score > 0)
    direction = "UP" if score > 0 else "DOWN" if score < 0 else "NO TRADE"
    if direction == "NO TRADE" or abs(score) < 6.0 or agreeing < 2:
        return NextCandleForecast(
            "NO TRADE", score, None, None, [], components, target, timeframe_seconds,
            "unverified", blockers or ["technical components are too balanced"], verified=False,
        )
    ranked = sorted(directional.items(), key=lambda item: -abs(item[1]))
    reasons = [f"{name} {value:+.1f}" for name, value in ranked[:3]]
    return NextCandleForecast(
        direction, score, None, None, reasons, components, target, timeframe_seconds,
        "unverified", [], verified=False,
    )


def _lo_reading(frame: pd.DataFrame, arrays: dict[str, pd.Series],
                target: datetime, seconds: int) -> NextCandleForecast:
    """Describe agreement among trend, recent movement and completed candles.

    This is an evidence filter, not a fitted probability or a trade signal.
    Correlated indicator subtotals do not vote and the legacy score is unused.
    """
    def reading(direction, reasons=None, blocker=None):
        return NextCandleForecast(
            direction, 0.0, None, None, reasons or [], {}, target, seconds,
            "unverified", [blocker] if blocker else [],
        )

    atr = arrays["atr"]
    scale = float(atr.iloc[-1])
    previous_scale = float(atr.iloc[-2])
    reference = float(atr.iloc[-97:-1].median())
    close = arrays["close"]
    last_range = max(float(arrays["high"].iloc[-1] - arrays["low"].iloc[-1]),
                     abs(float(arrays["high"].iloc[-1] - close.iloc[-2])),
                     abs(float(arrays["low"].iloc[-1] - close.iloc[-2])))
    if (not (reference > 0 and previous_scale > 0 and .65 * reference <= scale <= 1.60 * reference)
            or last_range > 2.5 * previous_scale):
        return reading("NO TRADE", blocker="التذبذب خارج النطاق المعتاد؛ القراءة محايدة.")

    recent = close.iloc[-21:]
    travel = float(recent.diff().abs().sum())
    efficiency = abs(float(recent.iloc[-1] - recent.iloc[0])) / travel if travel else 0.0
    if efficiency < .30:
        return reading("NO TRADE", blocker="السوق عرضي؛ ما فيه ميل واضح.")

    ema21, ema50 = arrays["ema21"], arrays["ema50"]
    separation = float(ema21.iloc[-1] - ema50.iloc[-1])
    slope = float(ema21.iloc[-1] - ema21.iloc[-6])
    movement = float(close.iloc[-1] - close.iloc[-6])
    bodies = (close - frame["open"]).iloc[-3:]
    for sign, direction in ((1, "UP"), (-1, "DOWN")):
        if (separation * sign >= .20 * scale and slope * sign >= .15 * scale
                and movement * sign >= .75 * scale and bodies.iloc[-1] * sign > 0
                and (bodies * sign > 0).sum() >= 2):
            return reading(direction, ["الترند والزخم وآخر الشموع المغلقة متوافقة."])
    return reading("NO TRADE", blocker="الترند والزخم وآخر الشموع مو متوافقين؛ القراءة محايدة.")


def forecast_from_frame(
    frame: pd.DataFrame,
    *,
    market: str,
    timeframe_code: str,
    timeframe_seconds: int,
    now: datetime,
    target_open_at: datetime | None = None,
    calibration: dict[str, Any] | None = None,
    require_calibration: bool = True,
    required_target_offset: int | None = None,
) -> NextCandleForecast:
    """Predict the next candle. Must be called before that candle opens.

    ``require_calibration=False`` is LO mode. It describes technical bias
    without a probability or trade signal.
    """
    target = target_open_at or (now + timedelta(seconds=timeframe_seconds))
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    if now >= target:
        return NextCandleForecast(
            "NO TRADE", 0.0, None, None, [], {}, target, timeframe_seconds,
            "none", ["target candle already opened; refusing a late prediction"],
        )
    if not require_calibration:
        # The caller already supplies a closed, contiguous tail on the live
        # route; enforce that independently for direct/replay consumers.
        index = frame.index
        if (timeframe_seconds <= 0 or not isinstance(index, pd.DatetimeIndex)
                or index.tz is None or index.hasnans
                or index.has_duplicates or not index.is_monotonic_increasing):
            return NextCandleForecast(
                "NO TRADE", 0.0, None, None, [], {}, target, timeframe_seconds,
                "unverified", ["توقيت بيانات الشموع غير صالح للقراءة."],
            )
        step = pd.Timedelta(seconds=timeframe_seconds)
        frame = frame.loc[index + step <= now]
        if not frame.empty:
            discontinuities = np.flatnonzero(frame.index.to_series().diff().ne(step).to_numpy())
            frame = frame.iloc[discontinuities[-1]:].tail(200)
            if frame.index[-1] + 2 * step <= now:
                return NextCandleForecast(
                    "NO TRADE", 0.0, None, None, [], {}, target, timeframe_seconds,
                    "unverified", ["آخر شمعة مغلقة متأخرة عن توقيت السوق."],
                )
        prices = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
        op, hi, lo, cl = prices.T
        if not (np.isfinite(prices).all() and (prices > 0).all()
                and (hi >= np.maximum(op, cl)).all() and (lo <= np.minimum(op, cl)).all()):
            return NextCandleForecast(
                "NO TRADE", 0.0, None, None, [], {}, target, timeframe_seconds,
                "unverified", ["بيانات الشموع غير صالحة للقراءة."],
            )
    if len(frame) < 200:
        return NextCandleForecast(
            "NO TRADE", 0.0, None, None, [], {}, target, timeframe_seconds,
            "none", [f"متاح {len(frame)} شمعة مغلقة متتالية؛ القراءة تحتاج 200."
                     if not require_calibration else f"only {len(frame)} candles; 200 are needed"],
        )

    if require_calibration:
        calibration = calibration if calibration is not None else load_calibration()
        if required_target_offset is not None and calibration.get("target_offset") != required_target_offset:
            return NextCandleForecast(
                "NO TRADE", 0.0, None, None, [], {}, target, timeframe_seconds, "none",
                ["لا توجد معايرة مطابقة لتوقيت الشمعة المستهدفة"],
            )

    arrays = _series(frame)
    if not require_calibration:
        return _lo_reading(frame, arrays, target, timeframe_seconds)
    score, components = score_at(frame, arrays)
    table, label = _table_for(calibration, market, timeframe_code)
    if table is None:
        return NextCandleForecast(
            "NO TRADE", score, None, None, [], components, target, timeframe_seconds,
            label, [f"no calibrated walk-forward table for {market}/{timeframe_code}"],
        )
    if not table.get("enabled", False):
        walk = table.get("walk_forward") or {}
        return NextCandleForecast(
            "NO TRADE", score, None, None, [], components, target, timeframe_seconds,
            label,
            [
                "walk-forward edge is not proven for "
                f"{market}/{timeframe_code} (hit rate {walk.get('hit_rate', 0):.1f}%, "
                f"{walk.get('signals', 0)} signals)"
            ],
        )
    bucket = _bin_for(table, score)
    if bucket is None:
        return NextCandleForecast(
            "NO TRADE", score, None, None, [], components, target, timeframe_seconds,
            label, ["score falls outside a bucket with enough verified samples"],
        )

    predicted = "UP" if score > 0 else "DOWN" if score < 0 else "NO TRADE"
    up_rate = float(bucket["up_wins"] + 0.5 * bucket.get("draws", 0)) / max(bucket["n"], 1)
    probability_up = up_rate * 100
    confidence = up_rate * 100 if predicted == "UP" else (1 - up_rate) * 100
    components_sorted = sorted(components.items(), key=lambda item: -abs(item[1]))
    reasons = [f"{name} {value:+.1f}" for name, value in components_sorted[:3]]
    if not predicted == "NO TRADE" and confidence < 52.0:
        return NextCandleForecast(
            "NO TRADE", score, round(probability_up, 1), round(confidence, 1),
            reasons, components, target, timeframe_seconds, label,
            ["calibrated edge is below 52%; no trade"],
        )
    return NextCandleForecast(
        predicted, score, round(probability_up, 1), round(confidence, 1),
        reasons, components, target, timeframe_seconds, label, verified=True,
    )


def target_open_for(frame: pd.DataFrame, timeframe_seconds: int, now: datetime) -> datetime:
    """Open time of the next candle after the forming/last bar."""
    if frame.empty:
        return now
    last_open = frame.index[-1]
    if last_open.tzinfo is None:
        last_open = last_open.replace(tzinfo=timezone.utc)
    close_time = last_open + timedelta(seconds=timeframe_seconds)
    while close_time <= now:
        close_time += timedelta(seconds=timeframe_seconds)
    return close_time
