"""Smart Money Concepts computed from candle structure (no hand-waving)."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from engines.technical.indicators import find_swings


@dataclass(frozen=True, slots=True)
class StructureEvent:
    index: int
    price: float
    event: str  # BOS | CHoCH
    direction: str  # bullish | bearish

    def as_dict(self) -> dict:
        return asdict(self)


def market_structure(swings: list[dict]) -> dict:
    """Compare consecutive confirmed swings to classify BOS vs CHoCH."""
    trend = "NEUTRAL"
    events: list[StructureEvent] = []
    last_high: dict | None = None
    last_low: dict | None = None
    last_labels: list[str] = []

    for swing in swings:
        if swing["kind"] == "high":
            if last_high is not None:
                if swing["price"] > last_high["price"]:
                    event = "BOS" if trend == "BULLISH" else "CHoCH"
                    events.append(StructureEvent(swing["index"], round(last_high["price"], 8), event, "bullish"))
                    trend = "BULLISH"
                    last_labels.append("HH")
                else:
                    last_labels.append("LH")
            last_high = swing
        else:
            if last_low is not None:
                if swing["price"] < last_low["price"]:
                    event = "BOS" if trend == "BEARISH" else "CHoCH"
                    events.append(StructureEvent(swing["index"], round(last_low["price"], 8), event, "bearish"))
                    trend = "BEARISH"
                    last_labels.append("LL")
                else:
                    last_labels.append("HL")
            last_low = swing

    return {
        "trend": trend,
        "events": [event.as_dict() for event in events[-6:]],
        "last_event": events[-1].as_dict() if events else None,
        "labels": last_labels[-6:],
    }


def fair_value_gaps(frame: pd.DataFrame, atr_value: float, max_items: int = 5) -> list[dict]:
    gaps: list[dict] = []
    highs = frame["high"].to_numpy()
    lows = frame["low"].to_numpy()
    closes = frame["close"].to_numpy()
    minimum_gap = atr_value * 0.05
    for index in range(2, len(frame)):
        bullish = lows[index] > highs[index - 2] and (lows[index] - highs[index - 2]) >= minimum_gap
        bearish = highs[index] < lows[index - 2] and (lows[index - 2] - highs[index]) >= minimum_gap
        if not (bullish or bearish):
            continue
        top = float(lows[index] if bullish else lows[index - 2])
        bottom = float(highs[index - 2] if bullish else highs[index])
        future = slice(index + 1, None)
        if bullish:
            filled = bool((lows[future] <= bottom).any()) if index + 1 < len(frame) else False
        else:
            filled = bool((highs[future] >= top).any()) if index + 1 < len(frame) else False
        gaps.append(
            {
                "index": index,
                "direction": "bullish" if bullish else "bearish",
                "top": round(top, 8),
                "bottom": round(bottom, 8),
                "filled": filled,
                "filled_pct": round(
                    max(0.0, min(1.0, (top - closes[-1]) / (top - bottom))) if bullish else
                    max(0.0, min(1.0, (closes[-1] - bottom) / (top - bottom))),
                    2,
                ),
            }
        )
    return gaps[-max_items:]


def order_blocks(frame: pd.DataFrame, structure_events: list[dict], atr_value: float, max_items: int = 4) -> list[dict]:
    blocks: list[dict] = []
    opens = frame["open"].to_numpy()
    highs = frame["high"].to_numpy()
    lows = frame["low"].to_numpy()
    closes = frame["close"].to_numpy()
    for event in structure_events:
        index = event["index"]
        bullish = event["direction"] == "bullish"
        for back in range(index - 1, max(index - 12, -1), -1):
            opposite = closes[back] < opens[back] if bullish else closes[back] > opens[back]
            if not opposite:
                continue
            top, bottom = float(highs[back]), float(lows[back])
            future_low = lows[index + 1 :]
            future_high = highs[index + 1 :]
            if bullish:
                mitigated = bool((future_low <= bottom).any()) if len(future_low) else False
            else:
                mitigated = bool((future_high >= top).any()) if len(future_high) else False
            blocks.append(
                {
                    "index": back,
                    "direction": "bullish" if bullish else "bearish",
                    "top": round(top, 8),
                    "bottom": round(bottom, 8),
                    "mitigated": mitigated,
                    "kind": "DEMAND" if bullish else "SUPPLY",
                }
            )
            break
    return blocks[-max_items:]


def liquidity_sweeps(frame: pd.DataFrame, swings: list[dict], atr_value: float, max_items: int = 5) -> list[dict]:
    highs = frame["high"].to_numpy()
    lows = frame["low"].to_numpy()
    closes = frame["close"].to_numpy()
    sweeps: list[dict] = []
    for swing in swings:
        start = swing["index"] + 1
        end = min(start + 8, len(frame))
        for index in range(start, end):
            if swing["kind"] == "high":
                pierced = highs[index] > swing["price"] + atr_value * 0.05
                rejected = closes[index] < swing["price"]
                if pierced and rejected:
                    sweeps.append(
                        {
                            "index": index,
                            "level": round(swing["price"], 8),
                            "direction": "bearish",
                            "type": "liquidity sweep above equal highs",
                        }
                    )
                    break
            else:
                pierced = lows[index] < swing["price"] - atr_value * 0.05
                rejected = closes[index] > swing["price"]
                if pierced and rejected:
                    sweeps.append(
                        {
                            "index": index,
                            "level": round(swing["price"], 8),
                            "direction": "bullish",
                            "type": "liquidity sweep below equal lows",
                        }
                    )
                    break
    return sweeps[-max_items:]


def equal_levels(swings: list[dict], atr_value: float) -> dict:
    tolerance = max(atr_value * 0.12, 1e-9)
    result: dict[str, list[float]] = {"equal_highs": [], "equal_lows": []}
    for kind, key in (("high", "equal_highs"), ("low", "equal_lows")):
        points = [swing for swing in swings if swing["kind"] == kind]
        for i in range(len(points) - 1):
            if abs(points[i]["price"] - points[i + 1]["price"]) <= tolerance:
                if points[i + 1]["index"] - points[i]["index"] >= 4:
                    result[key].append(round((points[i]["price"] + points[i + 1]["price"]) / 2, 8))
    return result


def premium_discount(frame: pd.DataFrame, swings: list[dict]) -> dict:
    if len(frame) < 10:
        return {"zone": "UNKNOWN", "position": 0.5, "range_high": None, "range_low": None}
    window_swings = swings[-12:] or swings
    highs = [swing["price"] for swing in window_swings if swing["kind"] == "high"]
    lows = [swing["price"] for swing in window_swings if swing["kind"] == "low"]
    range_high = max(highs) if highs else float(frame["high"].iloc[-50:].max())
    range_low = min(lows) if lows else float(frame["low"].iloc[-50:].min())
    if range_high <= range_low:
        position = 0.5
    else:
        position = (float(frame["close"].iloc[-1]) - range_low) / (range_high - range_low)
    zone = "PREMIUM" if position > 0.62 else "DISCOUNT" if position < 0.38 else "EQUILIBRIUM"
    return {
        "zone": zone,
        "position": round(max(0.0, min(1.0, position)), 3),
        "range_high": round(range_high, 8),
        "range_low": round(range_low, 8),
    }


def analyze_smc(frame: pd.DataFrame, atr_value: float) -> dict:
    swings = find_swings(frame)
    structure = market_structure(swings)
    gaps = fair_value_gaps(frame, atr_value)
    blocks = order_blocks(frame, structure["events"], atr_value)
    sweeps = liquidity_sweeps(frame, swings, atr_value)
    levels = equal_levels(swings, atr_value)
    equilibrium = premium_discount(frame, swings)
    near = atr_value * 1.5
    price = float(frame["close"].iloc[-1])
    return {
        **structure,
        "swing_count": len(swings),
        "fair_value_gaps": [gap for gap in gaps if not gap["filled"]],
        "order_blocks": [block for block in blocks if not block["mitigated"]],
        "liquidity_sweeps": sweeps,
        "equal_highs": levels["equal_highs"],
        "equal_lows": levels["equal_lows"],
        "premium_discount": equilibrium,
        "demand_zones": [
            block for block in blocks if block["direction"] == "bullish" and block["bottom"] <= price + near
        ],
        "supply_zones": [
            block for block in blocks if block["direction"] == "bearish" and block["top"] >= price - near
        ],
    }
