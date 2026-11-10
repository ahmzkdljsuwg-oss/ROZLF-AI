"""Deterministic scoring: indicators + SMC produce UP / DOWN / NO TRADE."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from engines.technical.indicators import compute_indicators, frame_from_candles
from engines.technical.smc import analyze_smc
from providers.base import DataUnavailable, MarketData, utc_now


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
    frame = frame_from_candles(market_data.candles)
    ind = compute_indicators(frame)
    smc = analyze_smc(frame, ind["atr"])
    price = ind["price"]
    atr = ind["atr"] or price * 1e-5

    up: list[tuple[str, float]] = []
    down: list[tuple[str, float]] = []
    warnings: list[str] = []

    def vote(reason_up: str, reason_down: str, score: float) -> None:
        if score > 0 and reason_up:
            up.append((reason_up, score))
        elif score < 0 and reason_down:
            down.append((reason_down, abs(score)))

    # Trend structure
    if ind["trend"] == "UP":
        vote("Bullish EMA stack", "", 10 + 10 * ind["trend_strength"])
    elif ind["trend"] == "DOWN":
        vote("", "Bearish EMA stack", -(10 + 10 * ind["trend_strength"]))
    else:
        warnings.append("EMA stack is compressed (range conditions)")

    # EMA 200 regime
    if ind["ema200"]:
        vote("Price above EMA 200", "Price below EMA 200", 6 if price > ind["ema200"] else -6)

    # RSI momentum
    rsi = ind["rsi"]
    if rsi >= 70:
        warnings.append(f"RSI overbought ({rsi:.1f})")
        vote("", "RSI stretched from overbought", -4)
    elif rsi >= 58:
        vote("RSI momentum above 58", "", 8 + (rsi - 58) * 0.3)
    elif rsi <= 30:
        warnings.append(f"RSI oversold ({rsi:.1f})")
        vote("RSI recovering from oversold", "", 4)
    elif rsi <= 42:
        vote("", "RSI momentum below 42", -(8 + (42 - rsi) * 0.3))
    else:
        warnings.append("RSI in neutral band")

    # MACD
    if ind["macd_hist"] > 0:
        strength = 8 if ind["macd_hist"] >= ind["macd_hist_prev"] else 4
        vote("MACD histogram positive", "", strength)
    elif ind["macd_hist"] < 0:
        strength = 8 if ind["macd_hist"] <= ind["macd_hist_prev"] else 4
        vote("", "MACD histogram negative", -strength)

    # Stochastic momentum
    if ind["stoch_cross"] == "BULLISH":
        vote("Stochastic bullish cross", "", 3)
    elif ind["stoch_cross"] == "BEARISH":
        vote("", "Stochastic bearish cross", -3)

    # Bollinger position
    if price > ind["bb_upper"]:
        warnings.append("Price above upper Bollinger band")
    elif price < ind["bb_lower"]:
        warnings.append("Price below lower Bollinger band")

    # Market structure (recent events win)
    last_event = smc.get("last_event")
    if last_event:
        bars_since = len(frame) - 1 - last_event["index"]
        if bars_since <= 12:
            if last_event["direction"] == "bullish":
                label = "Bullish BOS" if last_event["event"] == "BOS" else "Bullish CHoCH"
                vote(label, "", 13)
            else:
                label = "Bearish BOS" if last_event["event"] == "BOS" else "Bearish CHoCH"
                vote("", label, 13)
        else:
            vote(
                "Bullish market structure intact" if smc["trend"] == "BULLISH" else "",
                "Bearish market structure intact" if smc["trend"] == "BEARISH" else "",
                4 if smc["trend"] != "NEUTRAL" else -4,
            )

    # Premium / discount location
    equilibrium = smc["premium_discount"]
    if equilibrium["zone"] == "DISCOUNT":
        vote("Price in discount zone", "", 5)
    elif equilibrium["zone"] == "PREMIUM":
        vote("", "Price in premium zone", -5)

    # Active fair value gaps close to price
    for gap in smc["fair_value_gaps"][-2:]:
        if gap["direction"] == "bullish" and gap["top"] <= price + atr * 0.8:
            vote("Unfilled bullish FVG nearby", "", 4)
        if gap["direction"] == "bearish" and gap["bottom"] >= price - atr * 0.8:
            vote("", "Unfilled bearish FVG nearby", -4)

    # Liquidity sweeps in the last few candles
    for sweep in smc["liquidity_sweeps"][-2:]:
        if len(frame) - 1 - sweep["index"] <= 6:
            if sweep["direction"] == "bullish":
                vote("Liquidity sweep below equal lows", "", 7)
            else:
                vote("", "Liquidity sweep above equal highs", -7)

    # Proximity to support / resistance
    if ind["support"] and price - ind["support"][0] <= atr * 0.6:
        vote("Reaction at support", "", 5)
    if ind["resistance"] and ind["resistance"][0] - price <= atr * 0.6:
        vote("", "Rejection from resistance", -5)

    # Candlestick confirmation
    for pattern in ind["patterns"]:
        if pattern["direction"] == "bullish":
            vote(f"{pattern['name']} pattern", "", 4)
        elif pattern["direction"] == "bearish":
            vote("", f"{pattern['name']} pattern", -4)

    # Volatility and spread warnings
    if ind["volatility"] == "HIGH":
        warnings.append("High volatility: expiry risk increases")
    if market_data.quote is not None:
        spread_pct = market_data.quote.spread_pct
        if spread_pct > 0.02:
            warnings.append(f"Wide spread ({spread_pct:.3f}%)")

    score_up = sum(points for _, points in up)
    score_down = sum(points for _, points in down)
    total = score_up + score_down
    if total <= 0:
        direction = "NO TRADE"
        confidence = 0.0
    else:
        best = max(score_up, score_down)
        separation = best / total
        direction = "UP" if score_up >= score_down else "DOWN"
        # A neutral prior keeps one-sided evidence from claiming near-certainty.
        prior = 18.0
        balance = abs(score_up - score_down) / (total + 2 * prior)
        confidence = _clamp(50 + balance * 90, 0, 92)
        if separation < 0.56:
            direction = "NO TRADE"
            warnings.append("Signals conflict: no clear edge")
        elif confidence < 58:
            direction = "NO TRADE"
            warnings.append("Confidence below trading threshold")
        elif min(score_up, score_down) > 18 and separation < 0.6:
            direction = "NO TRADE"
            warnings.append("Strong opposing evidence")

    chosen = up if direction == "UP" else down
    reasons = [reason for reason, _ in sorted(chosen, key=lambda item: -item[1])][:6]

    if market_data.asset.market.value == "smarty":
        # Expiry follows measured volatility, not the candle frame: quiet
        # conditions need room to move, choppy ones need a shorter window.
        expiry_seconds = {"LOW": 300, "NORMAL": 60, "HIGH": 15}.get(ind["volatility"], 60)
    else:
        expiry_seconds = max(30, market_data.timeframe.seconds)

    total_score = score_up + score_down
    if total_score > 0:
        buyers = round(100 * score_up / total_score)
        sellers = 100 - buyers
    else:
        buyers = sellers = 50

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
            "last_candle_at": market_data.candles[-1].time.isoformat(),
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
    )
