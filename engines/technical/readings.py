"""Display-only indicator readings from a contiguous tail of completed bars."""
from math import isfinite

from engines.technical.candle_reading import candle_details
from engines.technical.indicators import compute_indicators, frame_from_candles

READING_KEYS = ("trend", "ema", "momentum", "rsi", "volatility", "support", "resistance", "candle")


def read_indicators(bars, seconds):
    tail = list(bars[-300:])
    for i in range(len(tail)-1, 0, -1):
        if (tail[i].time - tail[i-1].time).total_seconds() != seconds:
            tail = tail[i:]
            break
    if not tail:
        return [{"key": k, "value": None} for k in READING_KEYS]

    n = len(tail)
    ind = compute_indicators(frame_from_candles(tail)) if n >= 15 else {}
    last = candle_details(tail, seconds, 1)[-1]
    ema50, ema200 = ind.get("ema50"), ind.get("ema200")

    def finite(v):
        return v if isinstance(v, (float, int)) and isfinite(v) else None

    def row(key, value=None, **extra):
        return {"key": key, "value": value, **extra}

    ema_state = None
    if n >= 200 and finite(ema50) is not None and finite(ema200) is not None:
        ema_state = "UP" if ema50 > ema200 else "DOWN" if ema50 < ema200 else "FLAT"
    price = tail[-1].close
    supports = [v for v in ind.get("support", []) if finite(v) is not None and v < price] if n >= 30 else []
    ceilings = [v for v in ind.get("resistance", []) if finite(v) is not None and v > price] if n >= 30 else []
    support, ceiling = max(supports, default=None), min(ceilings, default=None)
    return [
        row("trend", ind.get("trend") if n >= 50 else None),
        row("ema", ema_state, fast=ema50 if ema_state else None, slow=ema200 if ema_state else None),
        row("momentum", ind.get("momentum")),
        row("rsi", finite(ind.get("rsi"))),
        row("volatility", finite(ind.get("atr")), state=ind.get("volatility")),
        row("support", support if support and support < price else None),
        row("resistance", ceiling if ceiling and ceiling > price else None),
        row("candle", last["shape"], movement=last["movement"], body_pct=last["body_pct"]),
    ]
