"""Smart Money Concepts: market structure, BOS, CHoCH, FVG, order blocks, sweeps."""

from __future__ import annotations

import pandas as pd

from .indicators import to_frame


def swings(df: pd.DataFrame, k: int = 2) -> tuple[list[int], list[int]]:
    highs, lows = df["high"].tolist(), df["low"].tolist()
    hi_idx: list[int] = []
    lo_idx: list[int] = []
    for i in range(k, len(df) - k):
        if highs[i] == max(highs[i - k : i + k + 1]):
            hi_idx.append(i)
        if lows[i] == min(lows[i - k : i + k + 1]):
            lo_idx.append(i)
    return hi_idx, lo_idx


def market_structure(df: pd.DataFrame, k: int = 2) -> dict:
    hi_idx, lo_idx = swings(df, k)
    if len(hi_idx) < 2 or len(lo_idx) < 2:
        return {"ok": False, "reason": "لا توجد قمم وقيعان كافية لبناء الهيكل."}

    highs = [(i, float(df["high"].iat[i])) for i in hi_idx]
    lows = [(i, float(df["low"].iat[i])) for i in lo_idx]
    last_close = float(df["close"].iloc[-1])

    last_highs = highs[-3:]
    last_lows = lows[-3:]
    higher_highs = all(b[1] > a[1] for a, b in zip(last_highs, last_highs[1:]))
    higher_lows = all(b[1] > a[1] for a, b in zip(last_lows, last_lows[1:]))
    lower_highs = all(b[1] < a[1] for a, b in zip(last_highs, last_highs[1:]))
    lower_lows = all(b[1] < a[1] for a, b in zip(last_lows, last_lows[1:]))

    if higher_highs and higher_lows:
        trend = "BULLISH"
    elif lower_highs and lower_lows:
        trend = "BEARISH"
    else:
        trend = "RANGE"

    last_swing_high = highs[-1]
    last_swing_low = lows[-1]

    bos = "NONE"
    choch = "NONE"
    if last_close > last_swing_high[1]:
        bos = "BULLISH" if trend in ("BULLISH", "RANGE") else "BEARISH"
        if trend == "BEARISH":
            choch = "BULLISH"
    elif last_close < last_swing_low[1]:
        bos = "BEARISH" if trend in ("BEARISH", "RANGE") else "BULLISH"
        if trend == "BULLISH":
            choch = "BEARISH"

    window = df.tail(120)
    range_high = float(window["high"].max())
    range_low = float(window["low"].min())
    span = range_high - range_low
    position = (last_close - range_low) / span if span > 0 else 0.5
    zone = "PREMIUM" if position > 0.618 else ("DISCOUNT" if position < 0.382 else "EQUILIBRIUM")

    return {
        "ok": True,
        "trend": trend,
        "bos": bos,
        "choch": choch,
        "swing_high": last_swing_high[1],
        "swing_low": last_swing_low[1],
        "range_high": round(range_high, 6),
        "range_low": round(range_low, 6),
        "position": round(position, 4),
        "zone": zone,
        "equal_highs": _equal_levels([h[1] for h in highs[-6:]]),
        "equal_lows": _equal_levels([l[1] for l in lows[-6:]]),
    }


def fair_value_gaps(df: pd.DataFrame, lookback: int = 40) -> list[dict]:
    """Unfilled 3-candle imbalances near the current price."""
    out: list[dict] = []
    start = max(2, len(df) - lookback)
    highs, lows, closes = df["high"].tolist(), df["low"].tolist(), df["close"].tolist()
    last_close = closes[-1]
    for i in range(start, len(df)):
        if lows[i] > highs[i - 2]:
            low_edge, high_edge = highs[i - 2], lows[i]
            filled = any(lows[j] <= low_edge for j in range(i + 1, len(df)))
            if not filled and low_edge < last_close:
                out.append({"kind": "BULLISH", "from": round(low_edge, 6), "to": round(high_edge, 6), "index": i})
        elif highs[i] < lows[i - 2]:
            low_edge, high_edge = highs[i], lows[i - 2]
            filled = any(highs[j] >= high_edge for j in range(i + 1, len(df)))
            if not filled and high_edge > last_close:
                out.append({"kind": "BEARISH", "from": round(low_edge, 6), "to": round(high_edge, 6), "index": i})
    return out[-4:]


def order_blocks(df: pd.DataFrame, lookback: int = 60) -> list[dict]:
    """Last opposing candle before an impulsive displacement candle."""
    out: list[dict] = []
    start = max(1, len(df) - lookback)
    opens, closes, highs, lows = df["open"].tolist(), df["close"].tolist(), df["high"].tolist(), df["low"].tolist()
    bodies = [abs(closes[i] - opens[i]) for i in range(len(df))]
    for i in range(start, len(df) - 1):
        avg = sum(bodies[max(0, i - 10) : i + 1]) / max(1, len(bodies[max(0, i - 10) : i + 1]))
        nxt = bodies[i + 1]
        if avg <= 0 or nxt < avg * 1.5:
            continue
        if closes[i] < opens[i] and closes[i + 1] > opens[i + 1]:
            out.append({"kind": "BULLISH", "from": round(lows[i], 6), "to": round(highs[i], 6), "index": i})
        elif closes[i] > opens[i] and closes[i + 1] < opens[i + 1]:
            out.append({"kind": "BEARISH", "from": round(lows[i], 6), "to": round(highs[i], 6), "index": i})
    return out[-4:]


def liquidity_sweeps(df: pd.DataFrame, lookback: int = 60) -> list[dict]:
    """Wick through a prior swing extreme that closes back inside."""
    hi_idx, lo_idx = swings(df, 2)
    out: list[dict] = []
    highs, lows, closes = df["high"].tolist(), df["low"].tolist(), df["close"].tolist()
    start = max(3, len(df) - lookback)
    for i in range(start, len(df)):
        for idx in hi_idx:
            if idx < i - 1 and highs[i] > highs[idx] and closes[i] < highs[idx]:
                out.append({"kind": "BEARISH", "level": round(highs[idx], 6), "index": i})
                break
        for idx in lo_idx:
            if idx < i - 1 and lows[i] < lows[idx] and closes[i] > lows[idx]:
                out.append({"kind": "BULLISH", "level": round(lows[idx], 6), "index": i})
                break
    return out[-4:]


def analyze(candles) -> dict:
    df = to_frame(candles)
    if len(df) < 30:
        return {"ok": False, "reason": "شموع غير كافية لتحليل الهيكل السعري."}
    structure = market_structure(df)
    result = {
        "ok": structure.get("ok", False),
        "structure": structure,
        "fvg": fair_value_gaps(df),
        "order_blocks": order_blocks(df),
        "sweeps": liquidity_sweeps(df),
    }
    if not result["ok"]:
        result["reason"] = structure.get("reason", "هيكل غير مكتمل.")
    return result


def _equal_levels(values: list[float], tolerance: float = 0.0008) -> list[float]:
    out: list[float] = []
    for i, a in enumerate(values):
        for b in values[i + 1 :]:
            if a and abs(a - b) / a <= tolerance:
                out.append(round(b, 6))
                break
    return sorted(set(out))
