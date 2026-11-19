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
    for key in (market, market.lower(), "global"):
        table = (markets.get(key) or {}).get(timeframe)
        if table and (table.get("bins") or table.get("horizons")):
            return table, f"{key}/{timeframe}"
    return None, "none"


def enabled_frames(market: str, calibration: dict[str, Any] | None = None) -> list[str]:
    """Frames whose walk-forward edge passed the stored out-of-sample gate."""
    cal = load_calibration() if calibration is None else calibration
    tables = (cal.get("markets") or {}).get(market.lower()) or {}
    order = ("30sec", "1min", "5min", "15min", "30min", "1h")
    result = []
    for frame in order:
        root = tables.get(frame) or {}
        candidates = list((root.get("horizons") or {}).values()) or [root]
        if any(
            item.get("enabled") is True
            and item.get("horizon_bars") in (1, 2)
            and item.get("expiry_seconds")
            and item.get("wilson_95_lower_hit_rate") is not None
            and item.get("break_even_hit_rate") is not None
            and item["wilson_95_lower_hit_rate"] > item["break_even_hit_rate"]
            for item in candidates
        ):
            result.append(frame)
    return result


def forecast_frames(market: str, profile_frames: tuple[str, ...],
                    calibration: dict[str, Any] | None = None) -> tuple[str, ...]:
    enabled = [frame for frame in enabled_frames(market, calibration) if frame in profile_frames]
    return tuple(enabled[:3]) or tuple(profile_frames[:3])


def _bin_for(table: dict[str, Any], score: float,
             direction: str | None = None) -> dict[str, Any] | None:
    for bucket in table.get("bins", []):
        if bucket["low"] <= abs(score) < bucket["high"]:
            if bucket.get("n", 0) >= MIN_CALIBRATION_SAMPLES:
                if direction == "UP" and bucket.get("predicted_up_n", 0) < MIN_CALIBRATION_SAMPLES:
                    return None
                if direction == "DOWN" and bucket.get("predicted_down_n", 0) < MIN_CALIBRATION_SAMPLES:
                    return None
                return bucket
            return None
    return None


def _wilson_lower_bound(wins: int, trials: int, z: float = 1.96) -> float:
    if trials <= 0:
        return 0.0
    p = wins / trials
    z2 = z * z
    denominator = 1 + z2 / trials
    center = p + z2 / (2 * trials)
    margin = z * math.sqrt(p * (1 - p) / trials + z2 / (4 * trials * trials))
    return max(0.0, (center - margin) / denominator)


def _technical_forecast(score: float, components: dict[str, float], target: datetime,
                        timeframe_seconds: int, blockers: list[str]) -> NextCandleForecast:
    """Uncalibrated LO-mode direction from agreement among independent components."""
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


def forecast_from_frame(
    frame: pd.DataFrame,
    *,
    market: str,
    timeframe_code: str,
    timeframe_seconds: int,
    now: datetime,
    target_open_at: datetime | None = None,
    horizon_bars: int = 1,
    expiry_seconds: int | None = None,
    calibration: dict[str, Any] | None = None,
    require_calibration: bool = True,
) -> NextCandleForecast:
    """Predict the next candle. Must be called before that candle opens.

    ``require_calibration=False`` is the LO mode: raw technical components may
    produce a direction, but confidence stays ``None`` (reported as UNVERIFIED)
    because no walk-forward hit rate backs it.
    """
    target = target_open_at or (now + timedelta(seconds=timeframe_seconds))
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    if horizon_bars < 1:
        raise ValueError("horizon_bars must be at least 1")
    if now > target:
        return NextCandleForecast(
            "NO TRADE", 0.0, None, None, [], {}, target, timeframe_seconds,
            "none", ["target candle already opened; refusing a late prediction"],
        )
    if len(frame) < 200:
        return NextCandleForecast(
            "NO TRADE", 0.0, None, None, [], {}, target, timeframe_seconds,
            "none", [f"only {len(frame)} candles; 200 are needed"],
        )

    arrays = _series(frame)
    score, components = score_at(frame, arrays)
    cal = load_calibration() if calibration is None else calibration
    table, label = _table_for(cal, market, timeframe_code)
    if not require_calibration:
        return _technical_forecast(score, components, target, timeframe_seconds, [])
    if table is None:
        return NextCandleForecast(
            "NO TRADE", score, None, None, [], components, target, timeframe_seconds,
            label, [f"no calibrated walk-forward table for {market}/{timeframe_code}"],
        )
    horizon_table = (table.get("horizons") or {}).get(str(horizon_bars))
    if horizon_table is not None:
        table = horizon_table
    calibrated_horizon = table.get("horizon_bars")
    if calibrated_horizon != horizon_bars:
        return NextCandleForecast(
            "NO TRADE", score, None, None, [], components, target, timeframe_seconds,
            label,
            [f"walk-forward calibration horizon mismatch: need {horizon_bars} bars, "
             f"available table is for {calibrated_horizon or 'unspecified'} bars"],
        )
    requested_expiry = timeframe_seconds if expiry_seconds is None else expiry_seconds
    calibrated_expiry = table.get("expiry_seconds")
    if calibrated_expiry != requested_expiry:
        return NextCandleForecast(
            "NO TRADE", score, None, None, [], components, target, timeframe_seconds,
            label,
            [f"walk-forward calibration expiry mismatch: need {requested_expiry}s, "
             f"available table is for {calibrated_expiry or 'unspecified'}s"],
        )
    lower_bound = table.get("wilson_95_lower_hit_rate")
    break_even = table.get("break_even_hit_rate")
    edge_proven = (
        lower_bound is not None and break_even is not None
        and float(lower_bound) > float(break_even)
    )
    if not table.get("enabled", False) or not edge_proven:
        walk = table.get("walk_forward") or {}
        hit_rate = walk.get("hit_rate")
        hit_rate_text = f"{hit_rate:.1f}%" if isinstance(hit_rate, (int, float)) else "unavailable"
        return NextCandleForecast(
            "NO TRADE", score, None, None, [], components, target, timeframe_seconds,
            label,
            [
                "payout-adjusted walk-forward edge is not proven for "
                f"{market}/{timeframe_code} (hit rate {hit_rate_text}, "
                f"{walk.get('signals', 0)} signals; 95% lower bound "
                f"{lower_bound if lower_bound is not None else 'missing'}%, "
                f"break-even {break_even if break_even is not None else 'missing'}%)"
            ],
        )
    predicted = "UP" if score > 0 else "DOWN" if score < 0 else "NO TRADE"
    if predicted == "NO TRADE":
        return NextCandleForecast(
            predicted, score, None, None, [], components, target, timeframe_seconds,
            label, ["forecast score is neutral"],
        )
    bucket = _bin_for(table, score, predicted)
    if bucket is None:
        return NextCandleForecast(
            "NO TRADE", score, None, None, [], components, target, timeframe_seconds,
            label, ["score falls outside a bucket with enough verified samples"],
        )

    count_key, wins_key = (
        ("predicted_up_n", "predicted_up_wins") if predicted == "UP"
        else ("predicted_down_n", "predicted_down_wins")
    )
    side_count = int(bucket.get(count_key, 0))
    side_wins = int(bucket.get(wins_key, 0))
    confidence = side_wins / max(side_count, 1) * 100
    probability_up = confidence if predicted == "UP" else 100 - confidence
    components_sorted = sorted(components.items(), key=lambda item: -abs(item[1]))
    reasons = [f"{name} {value:+.1f}" for name, value in components_sorted[:3]]
    break_even = table.get("break_even_hit_rate")
    lower_bound = _wilson_lower_bound(side_wins, side_count) * 100
    if break_even is None or lower_bound <= float(break_even):
        return NextCandleForecast(
            "NO TRADE", score, round(probability_up, 1), round(confidence, 1),
            reasons, components, target, timeframe_seconds, label,
            [f"score bucket 95% lower bound {lower_bound:.1f}% does not exceed "
             f"payout break-even {break_even if break_even is not None else 'missing'}%; no trade"],
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
    while close_time < now:
        close_time += timedelta(seconds=timeframe_seconds)
    return close_time
