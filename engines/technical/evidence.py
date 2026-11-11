"""Evidence engine: independent technical families produce a signal score.

The score is confidence in the quality of the evidence, never a claim about
the probability of winning. Win probability is only reported when a calibrated
out-of-sample study exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from engines.strategies.models import StrategyReport
from providers.base import MarketData

# Maximum points each independent family can add. Correlated readouts are
# capped inside their family so stacking RSI + MACD + Stochastic cannot
# inflate the score.
FAMILY_MAX = {
    "trend": 20,
    "structure": 16,
    "location": 14,
    "liquidity": 10,
    "momentum": 12,
    "price_action": 12,
    "data": 12,
}
TOTAL_MAX = sum(FAMILY_MAX.values())

STRATEGY_LABELS = {
    "structure": "SMC",
    "liquidity": "SMC",
    "location": "PRICE ACTION",
    "confirmation": "PRICE ACTION",
    "impulse": "PRICE ACTION",
    "trend": "EMA",
    "trend_strength": "EMA",
    "mtf": "MTF",
    "momentum": "MOMENTUM",
    "macd": "MOMENTUM",
    "stochastic": "MOMENTUM",
    "divergence": "MOMENTUM",
    "mean_reversion": "MEAN REVERSION",
    "vwap": "VWAP",
    "swing": "SMC",
    "ict": "ICT",
}


@dataclass(slots=True)
class EvidenceResult:
    direction: str
    confidence: float
    components: dict
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    independent_support: int = 0
    independent_opposition: int = 0
    data_quality: dict = field(default_factory=dict)
    win_probability: float | None = None
    strategy_labels: list[str] = field(default_factory=list)
    raw_points: float = 0.0

    @property
    def confidence_label(self) -> str:
        if self.confidence >= 80:
            return "HIGH"
        if self.confidence >= 68:
            return "MEDIUM"
        return "LOW"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _family_scores(report: StrategyReport) -> dict[tuple[str, str], float]:
    scores: dict[tuple[str, str], float] = {}
    for signal in report.signals:
        if signal.direction not in ("UP", "DOWN"):
            continue
        key = (signal.family, signal.direction)
        scores[key] = max(scores.get(key, 0.0), float(signal.score))
    return scores


def _data_quality(market_data: MarketData, now: datetime) -> tuple[int, dict, list[str]]:
    issues: list[str] = []
    bars = len(market_data.candles)
    if bars >= 200:
        bar_points = 6
    elif bars >= 120:
        bar_points = 5
    elif bars >= 60:
        bar_points = 3
    else:
        bar_points = 0
    if bar_points == 0:
        issues.append(f"only {bars} closed candles, minimum is 60")

    age = (now - market_data.candles[-1].time).total_seconds()
    tf = market_data.timeframe.seconds
    if age <= tf * 0.6:
        fresh_points = 4
    elif age <= tf * 1.1:
        fresh_points = 3
    elif age <= tf * 2.0:
        fresh_points = 1
    else:
        fresh_points = 0
        issues.append(f"last closed candle is {int(age)}s old")

    gap = market_data.validation.max_gap_seconds or 0.0
    gap_points = 2 if gap <= tf * 2.5 else 1 if gap <= tf * 5 else 0
    if gap_points == 0:
        issues.append(f"gaps up to {int(gap)}s between candles")

    score = bar_points + fresh_points + gap_points
    level = "HIGH" if score >= 9 else "MEDIUM" if score >= 6 else "LOW"
    return score, {"score": score, "max": FAMILY_MAX["data"], "level": level, "bars": bars,
                   "age_seconds": round(age, 1), "issues": issues}, issues


def evaluate_evidence(
    frame: pd.DataFrame,
    ind: dict,
    smc: dict,
    report: StrategyReport,
    market_data: MarketData,
    now: datetime,
) -> EvidenceResult:
    price = float(ind["price"])
    atr = float(ind["atr"] or price * 1e-5)
    components = {name: 0.0 for name in FAMILY_MAX}
    blockers: list[str] = []
    warnings: list[str] = []

    family_scores = _family_scores(report)
    score_up = sum(value for (family, direction), value in family_scores.items() if direction == "UP")
    score_down = sum(value for (family, direction), value in family_scores.items() if direction == "DOWN")
    total = score_up + score_down
    if total <= 0:
        return EvidenceResult(
            direction="NO TRADE",
            confidence=0.0,
            components=components,
            blockers=["No independent strategy produced a valid entry condition"],
            data_quality={"score": 0, "max": FAMILY_MAX["data"], "level": "LOW"},
        )

    direction = "UP" if score_up > score_down else "DOWN"
    opposite = "DOWN" if direction == "UP" else "UP"
    best = max(score_up, score_down)
    separation = best / total
    if separation < 0.56:
        blockers.append("Signals conflict: no clear directional edge")

    support_families = {family for (family, side) in family_scores if side == direction}
    oppose_families = {family for (family, side) in family_scores if side == opposite}

    bullish = direction == "UP"
    ema_fields = ("ema9", "ema21", "ema50")
    ema_aligned = (
        ind["ema9"] > ind["ema21"] > ind["ema50"] if bullish
        else ind["ema9"] < ind["ema21"] < ind["ema50"]
    )
    if ind.get("trend") == direction:
        components["trend"] += 7
    elif ema_aligned:
        components["trend"] += 5
    else:
        warnings.append("EMA stack is not aligned with the signal")

    mtf = report.mtf or {}
    if mtf.get("aligned") and mtf.get("direction") == direction:
        components["trend"] += 8
    elif mtf.get("direction") == "MIXED":
        warnings.append("Timeframes conflict")
    elif mtf.get("direction") not in (None, "MIXED", direction):
        blockers.append("Higher timeframes disagree with the setup")

    adx_value = float(report.context.get("adx", 0.0))
    di_up = float(report.context.get("plus_di", 0.0))
    di_down = float(report.context.get("minus_di", 0.0))
    di_match = (di_up > di_down) if bullish else (di_down > di_up)
    if adx_value >= 25 and di_match:
        components["trend"] += 5
    elif adx_value >= 20 and di_match:
        components["trend"] += 3
    elif adx_value < 18:
        blockers.append(f"Weak trend: ADX {adx_value:.1f} below 18")

    last_event = smc.get("last_event")
    if last_event and (len(frame) - 1 - last_event["index"]) <= 12:
        event_bullish = last_event["direction"] == "bullish"
        if event_bullish == bullish:
            components["structure"] += 10 if last_event["event"] == "CHoCH" else 9
        else:
            warnings.append(f"Last structure event is {last_event['event']} against the signal")
    if smc.get("trend") == ("BULLISH" if bullish else "BEARISH"):
        components["structure"] += 6
    elif smc.get("trend") in ("BULLISH", "BEARISH"):
        blockers.append("Market structure disagrees with the setup")

    for gap in smc.get("fair_value_gaps", [])[-2:]:
        if gap["direction"] == ("bullish" if bullish else "bearish"):
            near = gap["top"] <= price + atr * 0.8 if bullish else gap["bottom"] >= price - atr * 0.8
            if near:
                components["location"] += 4
                break
    zones = smc.get("demand_zones" if bullish else "supply_zones", [])
    for block in zones[-1:]:
        if block["bottom"] - atr * 0.3 <= price <= block["top"] + atr * 0.3:
            components["location"] += 5
            break
    zone = smc.get("premium_discount", {}).get("zone")
    if (bullish and zone == "DISCOUNT") or (not bullish and zone == "PREMIUM"):
        components["location"] += 3

    supports = ind.get("support") or []
    resistances = ind.get("resistance") or []
    if bullish and resistances and (resistances[0] - price) <= atr * 0.35:
        blockers.append("Price is too close to resistance for a long entry")
    elif not bullish and supports and (price - supports[0]) <= atr * 0.35:
        blockers.append("Price is too close to support for a short entry")
    elif (bullish and supports) or (not bullish and resistances):
        components["location"] += 2

    for sweep in smc.get("liquidity_sweeps", [])[-2:]:
        if len(frame) - 1 - sweep["index"] <= 6:
            sweep_bullish = sweep["direction"] == "bullish"
            if sweep_bullish == bullish:
                components["liquidity"] += 7
                break
    equal_levels = smc.get("equal_lows") if bullish else smc.get("equal_highs")
    if equal_levels:
        components["liquidity"] += 3

    if (ind["macd_hist"] > 0) == bullish:
        components["momentum"] += 5
    if (ind["rsi"] > 50) == bullish:
        components["momentum"] += 4
    stoch = ind.get("stoch_cross")
    if (bullish and stoch == "BULLISH") or (not bullish and stoch == "BEARISH"):
        components["momentum"] += 3

    names = {signal.name for signal in report.confirmed(direction)}
    if "Breakout & Retest" in names:
        components["price_action"] += 6
    if "Candlestick Pattern" in names:
        components["price_action"] += 3
    if "ICT Displacement" in names:
        components["price_action"] += 3

    prior_high = float(frame["high"].iloc[-21:-1].max()) if len(frame) > 21 else price
    prior_low = float(frame["low"].iloc[-21:-1].min()) if len(frame) > 21 else price
    last = frame.iloc[-1]
    if bullish and float(last["high"]) > prior_high and float(last["close"]) < prior_high:
        blockers.append("Fake breakout: upside break was rejected")
    if not bullish and float(last["low"]) < prior_low and float(last["close"]) > prior_low:
        blockers.append("Fake breakout: downside break was rejected")

    if ind.get("ema21") and abs(price - ind["ema21"]) > atr * 2.2:
        blockers.append("Price is extended from EMA21; late entry refused")
    recent_move = abs(price - float(frame["close"].iloc[-6])) if len(frame) >= 6 else 0.0
    if recent_move > atr * 3.0:
        blockers.append("Price moved too far in the last bars; entry is late")

    if adx_value < 18 and float(ind.get("atr_percentile") or 0.0) < 0.3:
        blockers.append("Sideways market: trend and volatility are both weak")

    data_score, data_quality, data_issues = _data_quality(market_data, now)
    components["data"] = float(data_score)
    if data_score < 6:
        blockers.extend(data_issues)

    if len(support_families) < 2:
        blockers.append("Insufficient independent confirmation")

    against_points = sum(
        min(FAMILY_MAX.get(family, 0), value * 1.2)
        for (family, side), value in family_scores.items()
        if side == opposite
    )
    conflict_penalty = min(18.0, against_points * 0.8)
    if pair_conflict := (score_up > 0 and score_down > 0 and min(score_up, score_down) / total > 0.35):
        warnings.append("Meaningful opposing evidence was deducted")

    earned = sum(components.values()) - conflict_penalty
    quality_pct = _clamp(earned / TOTAL_MAX * 100, 0.0, 100.0)
    confidence = round(_clamp(45.0 + quality_pct * 0.52, 0.0, 92.0), 1)
    if confidence < 58.0:
        blockers.append("Confidence below the trading threshold")

    labels: list[str] = []
    for signal in report.confirmed(direction):
        label = STRATEGY_LABELS.get(signal.family)
        if label and label not in labels:
            labels.append(label)

    if blockers:
        direction = "NO TRADE"

    return EvidenceResult(
        direction=direction,
        confidence=confidence,
        components={key: round(value, 1) for key, value in components.items()},
        blockers=blockers,
        warnings=warnings,
        independent_support=len(support_families),
        independent_opposition=len(oppose_families),
        data_quality=data_quality,
        win_probability=None,
        strategy_labels=labels[:3],
        raw_points=round(earned, 1),
    )
