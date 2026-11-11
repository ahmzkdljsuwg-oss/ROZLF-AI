"""Deterministic scoring: indicators + SMC produce UP / DOWN / NO TRADE."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime

from engines.technical.evidence import evaluate_evidence
from engines.technical.indicators import compute_indicators, frame_from_candles
from engines.technical.smc import analyze_smc
from engines.strategies.engine import evaluate_strategies
from engines.validation import closed_candles
from providers.base import DataUnavailable, MarketData, utc_now
from providers.catalog import Market


@dataclass
class AnalysisResult:
    asset_key: str
    asset_display: str
    market: str
    timeframe: str
    direction: str
    confidence: float
    score_up: float
    score_down: float
    price: float
    source: str
    generated_at: datetime
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    indicators: dict = field(default_factory=dict)
    smc: dict = field(default_factory=dict)
    suggested_expiry_seconds: int = 60
    trend_summary: str = "RANGE"
    mtf: dict = field(default_factory=dict)
    evidence_score: float = 0.0
    momentum_strength: str = "WEAK"
    data_confidence: dict = field(default_factory=dict)
    confirmed_strategies: list[dict] = field(default_factory=list)
    opposing_strategies: list[dict] = field(default_factory=list)
    invalidation: list[str] = field(default_factory=list)
    cancellation_reason: str | None = None
    session: str = "NONE"
    confidence_components: dict = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    data_quality_score: float = 0.0
    win_probability: float | None = None
    strategy_labels: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["generated_at"] = self.generated_at.isoformat()
        return data


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def analyze_market_data(market_data: MarketData, now: datetime | None = None) -> AnalysisResult:
    if not market_data.validation.ok:
        raise DataUnavailable("INVALID_DATA", f"Refusing to analyse invalid candles: {market_data.validation.summary}")
    if market_data.validation.stale:
        raise DataUnavailable("STALE_DATA", "Refusing to analyse stale candles")

    now = now or utc_now()
    usable = closed_candles(market_data.candles, market_data.timeframe, now)
    if not usable:
        raise DataUnavailable("NO_CLOSED_CANDLES", "No closed candles are available yet")
    min_bars = 60
    if len(usable) < min_bars:
        raise DataUnavailable(
            "INSUFFICIENT_BARS",
            f"Only {len(usable)} closed candles; {min_bars} are required",
        )
    analysis_data = replace(
        market_data,
        candles=usable,
        validation=replace(market_data.validation, bar_count=len(usable)),
    )
    frame = frame_from_candles(usable)
    ind = compute_indicators(frame)
    smc = analyze_smc(frame, ind["atr"])
    report = evaluate_strategies(frame, ind, smc, market_data.asset.market, market_data.timeframe.seconds, now)
    price = ind["price"]
    atr = ind["atr"] or price * 1e-5

    warnings: list[str] = []
    if ind["trend"] == "RANGE":
        warnings.append("EMA stack is compressed (range conditions)")
    rsi = ind["rsi"]
    if rsi >= 70:
        warnings.append(f"RSI overbought ({rsi:.1f})")
    elif rsi <= 30:
        warnings.append(f"RSI oversold ({rsi:.1f})")
    if price > ind["bb_upper"]:
        warnings.append("Price above upper Bollinger band")
    elif price < ind["bb_lower"]:
        warnings.append("Price below lower Bollinger band")
    if ind["volatility"] == "HIGH":
        warnings.append("High volatility: expiry risk increases")
    if market_data.quote is not None:
        spread_pct = market_data.quote.spread_pct
        if spread_pct > 0.02:
            warnings.append(f"Wide spread ({spread_pct:.3f}%)")

    evidence = evaluate_evidence(frame, ind, smc, report, analysis_data, now)
    direction = evidence.direction
    confidence = evidence.confidence
    cancellation_reason = evidence.blockers[0] if evidence.blockers else None
    warnings.extend(evidence.warnings)
    if cancellation_reason:
        warnings.append(cancellation_reason)
    score_up = sum(
        max(0.0, signal.score) for signal in report.signals if signal.direction == "UP"
    )
    score_down = sum(
        max(0.0, signal.score) for signal in report.signals if signal.direction == "DOWN"
    )
    confirmed = report.confirmed(direction) if direction in ("UP", "DOWN") else []
    opposed = report.opposed(direction) if direction in ("UP", "DOWN") else []
    reasons = [signal.reason for signal in confirmed][:6]
    if not reasons and evidence.blockers:
        reasons = evidence.blockers[:4]
    invalidation = [signal.invalidation for signal in confirmed[:3]]

    if market_data.asset.market in (Market.SMARTY, Market.AI, Market.FOOTBALL, Market.LUXURY):
        # Expiry follows measured volatility, not the candle frame: quiet
        # conditions need room to move, choppy ones need a shorter window.
        expiry_seconds = {"LOW": 300, "NORMAL": 60, "HIGH": 30}.get(ind["volatility"], 60)
    else:
        expiry_seconds = max(30, market_data.timeframe.seconds)

    total_score = score_up + score_down
    if total_score > 0:
        buyers = round(100 * score_up / total_score)
        sellers = 100 - buyers
    else:
        buyers = sellers = 50

    bars = len(frame)
    quality_points = 100 if bars >= 200 else 85 if bars >= 120 else 70 if bars >= 60 else 55
    if market_data.quote is not None and market_data.quote.spread_pct > 0.02:
        quality_points -= 10
    quality_label = "HIGH" if quality_points >= 85 else "MEDIUM" if quality_points >= 65 else "LOW"
    data_confidence = dict(evidence.data_quality)
    data_confidence["level"] = evidence.data_quality.get("level", quality_label)

    adx_value = float(report.context.get("adx", 0.0))
    if adx_value >= 30 and (ind["trend"] in ("UP", "DOWN")):
        momentum_strength = "STRONG"
    elif adx_value >= 20:
        momentum_strength = "MODERATE"
    else:
        momentum_strength = "WEAK"

    trend_summary = report.mtf.get("direction", "MIXED")
    if trend_summary == "MIXED":
        trend_summary = ind["trend"]

    return AnalysisResult(
        asset_key=market_data.asset.key,
        asset_display=market_data.asset.display,
        market=market_data.asset.market.value,
        timeframe=market_data.timeframe.code,
        direction=direction,
        confidence=round(confidence, 1),
        score_up=round(score_up, 1),
        score_down=round(score_down, 1),
        price=price,
        source=market_data.source,
        generated_at=now,
        reasons=reasons,
        warnings=warnings[:4],
        indicators={
            "rsi": ind["rsi"],
            "macd_hist": ind["macd_hist"],
            "ema9": ind["ema9"],
            "ema21": ind["ema21"],
            "ema50": ind["ema50"],
            "atr": ind["atr"],
            "atr_pct": ind["atr_pct"],
            "trend": ind["trend"],
            "momentum": ind["momentum"],
            "volatility": ind["volatility"],
            "patterns": ind["patterns"],
            "support": ind["support"],
            "resistance": ind["resistance"],
            "ema200": ind["ema200"],
            "stoch_k": ind.get("stoch_k"),
            "stoch_d": ind.get("stoch_d"),
            "buyers": buyers,
            "sellers": sellers,
            "last_candle_at": usable[-1].time.isoformat(),
        },
        smc={
            "trend": smc["trend"],
            "last_event": smc["last_event"],
            "fair_value_gaps": smc["fair_value_gaps"],
            "order_blocks": smc["order_blocks"],
            "sweeps": smc["liquidity_sweeps"],
            "premium_discount": smc["premium_discount"],
            "equal_highs": smc["equal_highs"],
            "equal_lows": smc["equal_lows"],
        },
        suggested_expiry_seconds=expiry_seconds,
        trend_summary=trend_summary,
        mtf=report.mtf,
        evidence_score=round(max(score_up, score_down), 1),
        momentum_strength=momentum_strength,
        data_confidence=data_confidence,
        confirmed_strategies=[signal.as_dict() for signal in confirmed[:6]],
        opposing_strategies=[signal.as_dict() for signal in opposed[:4]],
        invalidation=invalidation,
        cancellation_reason=cancellation_reason,
        session=report.session,
        confidence_components=evidence.components,
        blockers=evidence.blockers,
        data_quality_score=float(evidence.data_quality.get("score", 0)),
        win_probability=evidence.win_probability,
        strategy_labels=evidence.strategy_labels,
    )
