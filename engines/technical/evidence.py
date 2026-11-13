"""Evidence engine: independent technical families produce a signal score.

The score is confidence in the quality of the evidence, never a claim about
the probability of winning. Win probability is only reported when a calibrated
out-of-sample study exists.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from engines.markets import MarketProfile, profile_for
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

FAMILY_ALIASES = {
    "confirmation": "price_action",
    "impulse": "price_action",
    "macd": "momentum",
    "stochastic": "momentum",
    "divergence": "momentum",
    "mean_reversion": "price_action",
    "vwap": "location",
    "swing": "structure",
    "mtf": "trend",
    "trend_strength": "trend",
    "ict": "liquidity",
}

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


TRIGGER_STRATEGIES = {
    "BOS / CHoCH",
    "Liquidity Sweep / Raid",
    "Breakout & Retest",
    "Momentum Breakout",
    "Trendline Break",
    "ICT Displacement",
    "Reversal Confirmation",
    "Candlestick Pattern",
    "Parabolic SAR",
    "Alligator",
    "Alligator + EMA 200",
    "Aroon",
    "Fractals",
    "Tweezers",
    "Three Methods",
    "V-Bounce",
    "RSI + MACD Reversal",
}


def _duration_weights(profile: MarketProfile, duration_seconds: int | None) -> dict[str, float]:
    """Short expiries need a momentum trigger; long expiries value the trend."""
    weights = {family: profile.weight(family) for family in FAMILY_MAX}
    if duration_seconds is None:
        return weights
    if duration_seconds <= 60:
        weights["momentum"] *= 1.10
        weights["structure"] *= 0.95
        weights["location"] *= 0.90
    elif duration_seconds <= 180:
        weights["momentum"] *= 1.04
        weights["location"] *= 0.96
    else:
        weights["trend"] *= 1.10
        weights["structure"] *= 1.06
        weights["momentum"] *= 0.92
    return weights


def _family_scores(
    report: StrategyReport,
    profile: MarketProfile,
    duration_seconds: int | None = None,
) -> dict[tuple[str, str], float]:
    scores: dict[tuple[str, str], float] = {}
    weights = _duration_weights(profile, duration_seconds)
    for signal in report.signals:
        if signal.direction not in ("UP", "DOWN"):
            continue
        family = FAMILY_ALIASES.get(signal.family, signal.family)
        if family not in FAMILY_MAX:
            continue
        if family == "price_action" and signal.family == "mean_reversion" and not profile.allow_mean_reversion:
            continue
        score = min(FAMILY_MAX[family], float(signal.score) * weights[family])
        key = (family, signal.direction)
        scores[key] = max(scores.get(key, 0.0), score)
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
    profile: MarketProfile | None = None,
    duration_seconds: int | None = None,
) -> EvidenceResult:
    profile = profile or profile_for(market_data.asset.market)
    price = float(ind["price"])
    atr = float(ind["atr"] or price * 1e-5)
    components = {name: 0.0 for name in FAMILY_MAX}
    blockers: list[str] = []
    warnings: list[str] = []

    family_scores = _family_scores(report, profile, duration_seconds)
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
    confirmed_names = {signal.name for signal in report.confirmed(direction)}
    trigger_names = confirmed_names & TRIGGER_STRATEGIES
    if separation < 0.53:
        blockers.append(
            f"{profile.name}: signals conflict, directional edge {separation:.0%} "
            f"is too close to call"
        )
    elif separation < profile.min_separation:
        warnings.append(
            f"{profile.name}: directional edge {separation:.0%} is modest; "
            "confidence is reduced"
        )

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
    mtf_short = mtf.get("short")
    mtf_medium = mtf.get("medium")
    mtf_long = mtf.get("long")
    higher_opposes = (
        mtf_medium not in (None, direction, "RANGE", "UNKNOWN")
        and mtf_long not in (None, direction, "RANGE", "UNKNOWN")
    )
    if mtf.get("aligned") and mtf.get("direction") == direction:
        components["trend"] += 8
    elif higher_opposes:
        # A 30-60s expiry is decided on the base frame; higher timeframes are
        # context and cannot veto a fresh short-term trigger on their own.
        if (duration_seconds is not None and duration_seconds <= 60) or trigger_names:
            warnings.append("Higher timeframes disagree; the short-term trigger carries the entry")
        else:
            blockers.append(f"{profile.name}: medium and higher timeframes disagree with the setup")
    elif mtf.get("direction") == "MIXED":
        higher_supports = mtf_medium == direction and mtf_long == direction
        if higher_supports:
            components["trend"] += 4
            warnings.append("Base timeframe is pulling back inside the higher-timeframe trend")
        else:
            warnings.append("Timeframes are mixed; confidence is reduced")

    adx_value = float(report.context.get("adx", 0.0))
    di_up = float(report.context.get("plus_di", 0.0))
    di_down = float(report.context.get("minus_di", 0.0))
    di_match = (di_up > di_down) if bullish else (di_down > di_up)
    if adx_value >= 25 and di_match:
        components["trend"] += 5
    elif adx_value >= 20 and di_match:
        components["trend"] += 3
    elif adx_value < 13:
        if di_match and trigger_names:
            warnings.append(
                f"ADX {adx_value:.1f} is very low; the {', '.join(sorted(trigger_names))} "
                "trigger carries the setup"
            )
        else:
            blockers.append(
                f"{profile.name}: weak trend, ADX {adx_value:.1f} below 13 "
                "with no momentum or structure trigger"
            )
    elif adx_value < profile.adx_floor:
        warnings.append(
            f"Trend strength is modest (ADX {adx_value:.1f} below {profile.adx_floor:.0f}); "
            "confidence is reduced"
        )

    last_event = smc.get("last_event")
    recent_event_age = len(frame) - 1 - last_event["index"] if last_event else 999
    if last_event and recent_event_age <= 12:
        event_bullish = last_event["direction"] == "bullish"
        if event_bullish == bullish:
            components["structure"] += 10 if last_event["event"] == "CHoCH" else 9
        else:
            warnings.append(f"Last structure event is {last_event['event']} against the signal")
            if last_event["event"] == "CHoCH" and recent_event_age <= 5:
                blockers.append("A fresh CHoCH reverses the setup")
    if smc.get("trend") == ("BULLISH" if bullish else "BEARISH"):
        components["structure"] += 6
    elif smc.get("trend") in ("BULLISH", "BEARISH"):
        if trigger_names:
            warnings.append("Older market structure disagrees, but a fresh trigger supports the entry")
        else:
            blockers.append("Market structure disagrees with the setup and no trigger confirms a reversal")

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
    nearest_level = resistances[0] if bullish and resistances else supports[0] if not bullish and supports else None
    breakout_confirmed = bool({"Breakout & Retest", "Momentum Breakout"} & confirmed_names)
    if nearest_level is not None:
        distance_atr = abs(nearest_level - price) / atr
        pressed_limit = max(0.08, profile.level_distance_atr * 0.25)
        if distance_atr <= pressed_limit and not breakout_confirmed:
            blockers.append(
                f"{profile.name}: price is pressed against the opposing level "
                f"({distance_atr:.2f} ATR) without a breakout"
            )
        elif distance_atr <= profile.level_distance_atr:
            warnings.append(
                f"Price is close to the opposing level ({distance_atr:.2f} ATR); "
                "target room is limited"
            )
            if distance_atr <= 1.6:
                components["location"] += 2
        elif distance_atr <= 1.6:
            components["location"] += 4
        else:
            components["location"] += 1
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

    names = confirmed_names
    if "Breakout & Retest" in names:
        components["price_action"] += 6
    if "Candlestick Pattern" in names:
        components["price_action"] += 3
    if "ICT Displacement" in names:
        components["price_action"] += 3

    prior_high = float(frame["high"].iloc[-21:-1].max()) if len(frame) > 21 else price
    prior_low = float(frame["low"].iloc[-21:-1].min()) if len(frame) > 21 else price
    last = frame.iloc[-1]
    fake_break = (
        bullish and float(last["high"]) > prior_high and float(last["close"]) < prior_high and not breakout_confirmed
    ) or (
        not bullish and float(last["low"]) < prior_low and float(last["close"]) > prior_low and not breakout_confirmed
    )
    if fake_break:
        if trigger_names:
            components["price_action"] -= 3
            warnings.append("Last bar rejected a break; the fresh trigger must prove itself")
        else:
            blockers.append("Fake breakout: the last bar broke and closed back inside")

    # Low timeframes carry several ATR of noise, so the late-entry band widens
    # there; a 3-ATR stretch on a 1-minute chart is normal, not a chase.
    short_frame = market_data.timeframe.seconds <= 60
    extension_hard = profile.max_extension_atr * (1.6 if short_frame else 1.35)
    extension_warn = profile.max_extension_atr * (1.15 if short_frame else 1.0)
    extension_atr = abs(price - ind["ema21"]) / atr if ind.get("ema21") and atr else 0.0
    if extension_atr > max(extension_hard, 6.0 if short_frame else 0.0):
        blockers.append(f"{profile.name}: price is extended from EMA21; late entry refused")
    elif extension_atr > extension_warn:
        components["location"] -= 2
        warnings.append("Price is stretched from EMA21; confidence is reduced")
    recent_move = abs(price - float(frame["close"].iloc[-6])) if len(frame) >= 6 else 0.0
    move_hard = max(profile.max_extension_atr + 1.3, 6.5 if short_frame else 0.0)
    move_warn = max(profile.max_extension_atr + 0.8, 4.5 if short_frame else 0.0)
    if recent_move > atr * move_hard:
        blockers.append(f"{profile.name}: price moved too far in the last bars; entry is late")
    elif recent_move > atr * move_warn:
        warnings.append("A fast move already happened; late-entry risk is higher")

    if adx_value < 13 and float(ind.get("atr_percentile") or 0.0) < 0.15 and not trigger_names:
        blockers.append("Sideways market: trend and volatility are both weak")

    data_score, data_quality, data_issues = _data_quality(market_data, now)
    components["data"] = float(data_score)
    if data_score < profile.data_quality_floor:
        blockers.extend(data_issues)
        blockers.append(
            f"{profile.name}: data quality {data_score}/{FAMILY_MAX['data']} "
            f"below the required {profile.data_quality_floor}"
        )

    if len(support_families) < profile.min_families:
        blockers.append(
            f"{profile.name}: {len(support_families)} independent families support "
            f"the setup, {profile.min_families} are required"
        )
    if profile.required_families and not (support_families & profile.required_families):
        blockers.append(
            f"{profile.name}: none of the required evidence families "
            f"({', '.join(sorted(profile.required_families))}) confirmed"
        )
    if duration_seconds is not None and duration_seconds <= 60 and not trigger_names:
        warnings.append("Short expiry without a fresh trigger; evidence must carry the entry")

    against_points = sum(
        min(FAMILY_MAX.get(family, 0), value * 1.2)
        for (family, side), value in family_scores.items()
        if side == opposite
    )
    conflict_penalty = min(18.0, against_points * 0.8)
    separation_penalty = min(4.0, max(0.0, profile.min_separation - separation) * 30.0)
    if score_up > 0 and score_down > 0 and min(score_up, score_down) / total > 0.35:
        warnings.append("Meaningful opposing evidence was deducted")

    earned = (
        sum(min(FAMILY_MAX[key], value) for key, value in components.items())
        - conflict_penalty
        - separation_penalty
    )
    # Calibration: the evidence total is a quality measure, so a setup that
    # earns a third of the available points is already a real, filtered trade.
    # The old 46 + 0.55 slope put most valid setups under the default 65%
    # threshold, which is why the app returned NO TRADE on genuine evidence.
    quality_pct = _clamp(earned / TOTAL_MAX * 100, 0.0, 100.0)
    confidence = round(_clamp(50.0 + quality_pct * 0.62, 0.0, 92.0), 1)
    if confidence < max(52.0, profile.min_confidence - 8.0):
        blockers.append(
            f"{profile.name}: evidence confidence is below the market threshold"
        )

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
