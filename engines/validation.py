"""Candle integrity checks. Nothing trades unless these pass."""
from __future__ import annotations

from datetime import datetime

from providers.base import Candle, ValidationReport, utc_now
from providers.catalog import Timeframe


def closed_candles(candles: list[Candle], tf: Timeframe, now: datetime) -> list[Candle]:
    """ExpertOption candle timestamps are bar-open times.

    A bar is only usable once ``open_time + tf.seconds`` has passed. This is
    enforced in live analysis and in the backtester so an unfinished bar can
    never leak into a decision.
    """
    return [candle for candle in candles if candle.time.timestamp() + tf.seconds <= now.timestamp()]


def validate_candles(
    candles: list[Candle],
    tf: Timeframe,
    now: datetime | None = None,
    min_bars: int = 60,
) -> ValidationReport:
    now = now or utc_now()
    if not candles:
        return ValidationReport(ok=False, bar_count=0, issues=("no candles returned",))

    issues: list[str] = []
    timestamps = [candle.time for candle in candles]
    if len(set(timestamps)) != len(timestamps):
        issues.append("duplicate candle timestamps")
    if timestamps != sorted(timestamps):
        issues.append("candles are not chronological")

    bad_ohlc = 0
    for candle in candles:
        values = (candle.open, candle.high, candle.low, candle.close)
        if any(value <= 0 for value in values):
            bad_ohlc += 1
            continue
        if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close):
            bad_ohlc += 1
        elif candle.high < candle.low:
            bad_ohlc += 1
    if bad_ohlc:
        issues.append(f"{bad_ohlc} candle(s) with invalid OHLC")

    last_time = max(timestamps)
    first_time = min(timestamps)
    age_seconds = (now - last_time).total_seconds()
    if age_seconds < -120:
        issues.append("candle timestamp is in the future")

    ordered = sorted(timestamps)
    gaps = [(later - earlier).total_seconds() for earlier, later in zip(ordered, ordered[1:])]
    max_gap = max(gaps) if gaps else 0.0
    # Weekend gaps are legitimate for forex, so gaps are reported, not fatal.
    if max_gap > tf.seconds * 6:
        issues.append(f"gap of {int(max_gap // 60)} min between candles")

    stale_after = max(tf.seconds * 3, 180)
    stale = age_seconds > stale_after

    if len(candles) < min_bars:
        issues.append(f"only {len(candles)} bars, need {min_bars}")
    if (last_time - first_time).total_seconds() < tf.seconds * (min_bars - 1) * 0.5:
        issues.append("insufficient history span")

    critical = [issue for issue in issues if not issue.startswith("gap of")]
    ok = not critical

    return ValidationReport(
        ok=ok,
        bar_count=len(candles),
        issues=tuple(issues),
        stale=stale,
        age_seconds=round(age_seconds, 1),
        last_candle_time=last_time,
        max_gap_seconds=max_gap,
    )
