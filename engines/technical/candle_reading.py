"""Pure descriptions of completed candles. None is a future price."""
from math import isfinite


def candle_details(bars, seconds, limit=40):
    out = []
    for i in range(max(0, len(bars) - limit), len(bars)):
        bar = bars[i]
        prev = bars[i - 1] if i else None
        span = bar.high - bar.low
        body = abs(bar.close - bar.open)
        top = bar.high - max(bar.close, bar.open)
        bottom = min(bar.close, bar.open) - bar.low
        aligned = prev is not None and (bar.time - prev.time).total_seconds() == seconds
        if span == 0:
            label = "FLAT"
        elif body <= .1 * span:
            label = "DOJI"
        elif max(top, bottom) >= .6 * span and body < .35 * span:
            label = "WICK"
        elif aligned and bar.high <= prev.high and bar.low >= prev.low:
            label = "INSIDE"
        elif aligned and (bar.open - bar.close) * (prev.open - prev.close) < 0 and (
            max(bar.open, bar.close) >= max(prev.open, prev.close)
            and min(bar.open, bar.close) <= min(prev.open, prev.close)
        ):
            label = "ENGULFING"
        elif body >= .65 * span:
            label = "BODY"
        else:
            label = "MIXED"
        out.append({
            "at": round(bar.time.timestamp() * 1000), "close_at": round(bar.time.timestamp() * 1000) + seconds * 1000,
            "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close,
            "movement": "UP" if bar.close > bar.open else "DOWN" if bar.close < bar.open else "FLAT",
            "shape": label, "body_pct": round(100 * body / span, 1) if span else 0,
            "gap_before": prev is not None and not aligned,
        })
    return out


def valid_candle(bar):
    return (all(isfinite(x) and x > 0 for x in (bar.open, bar.high, bar.low, bar.close))
            and bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high)
