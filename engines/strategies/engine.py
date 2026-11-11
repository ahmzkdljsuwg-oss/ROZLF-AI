"""Independent trading strategies with explicit entries and invalidation.

Each strategy returns at most one signal. Families keep correlated readouts
from being counted as separate evidence by the scorer.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from engines.markets import MarketProfile
from engines.strategies.models import StrategyReport, StrategySignal
from engines.technical.indicators import (
    adx,
    extended_patterns,
    find_swings,
    macd,
    macd_divergence,
    rsi,
    rsi_divergence,
    supertrend,
    trendline_break,
    vwap,
)
from providers.catalog import Market

NY = ZoneInfo("America/New_York")


def _add(signals: list[StrategySignal], name: str, family: str, direction: str,
         score: float, reason: str, invalidation: str) -> None:
    if direction in ("UP", "DOWN"):
        signals.append(StrategySignal(name, family, direction, float(score), reason, invalidation))


def _resample(frame: pd.DataFrame, factor: int) -> pd.DataFrame:
    return frame.resample(f"{max(1, factor) * 60}s").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()


def _ema_trend(frame: pd.DataFrame) -> str:
    if len(frame) < 30:
        return "UNKNOWN"
    close = frame["close"]
    e9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
    e21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
    e50 = close.ewm(span=min(50, len(frame) - 1), adjust=False).mean().iloc[-1]
    if e9 > e21 > e50:
        return "UP"
    if e9 < e21 < e50:
        return "DOWN"
    return "RANGE"


def multi_timeframe(frame: pd.DataFrame, timeframe_seconds: int) -> dict:
    """Base frame plus 3x and 6x aggregations; no future bars are used."""
    base = _ema_trend(frame)
    medium = _ema_trend(_resample(frame, round(timeframe_seconds * 3 / 60)))
    long = _ema_trend(_resample(frame, round(timeframe_seconds * 6 / 60)))
    available = [value for value in (base, medium, long) if value != "UNKNOWN"]
    aligned = bool(available) and len(set(available)) == 1 and available[0] != "RANGE"
    return {
        "short": base,
        "medium": medium,
        "long": long,
        "aligned": aligned,
        "direction": available[0] if aligned else "MIXED",
    }


def _session(now: datetime, market: Market) -> tuple[str, bool]:
    """ICT sessions only when the market truly has exchange sessions."""
    if market is not Market.FOREX:
        return "NONE", False
    local = now.astimezone(NY)
    hour = local.hour + local.minute / 60
    if 2 <= hour < 5:
        return "LONDON KILL ZONE", True
    if 7 <= hour < 10:
        return "NEW YORK KILL ZONE", True
    if 10 <= hour < 11:
        return "SILVER BULLET AM", True
    if 14 <= hour < 15:
        return "SILVER BULLET PM", True
    return "OUTSIDE KILL ZONES", False


def evaluate_strategies(
    frame: pd.DataFrame,
    ind: dict,
    smc: dict,
    market: Market,
    timeframe_seconds: int,
    now: datetime | None = None,
    profile: MarketProfile | None = None,
) -> StrategyReport:
    now = now or datetime.now(timezone.utc)
    price = ind["price"]
    atr = ind["atr"] or price * 1e-5
    signals: list[StrategySignal] = []
    warnings: list[str] = []

    adx_line, plus_di, minus_di = adx(frame)
    adx_value = float(adx_line.iloc[-1])
    di_up = float(plus_di.iloc[-1])
    di_down = float(minus_di.iloc[-1])
    st_dir, st_line = supertrend(frame)
    st_direction = "UP" if float(st_dir.iloc[-1]) > 0 else "DOWN"
    st_value = float(st_line.iloc[-1])
    mtf = multi_timeframe(frame, timeframe_seconds)
    session, in_session = _session(now, market)

    # ---- SMC / ICT structure ------------------------------------------------
    last_event = smc.get("last_event")
    if last_event and (len(frame) - 1 - last_event["index"]) <= 12:
        bullish = last_event["direction"] == "bullish"
        label = f"{last_event['event']} {'bullish' if bullish else 'bearish'}"
        invalidation = (
            f"close back below {last_event['price']:.6f}" if bullish
            else f"close back above {last_event['price']:.6f}"
        )
        _add(signals, "BOS / CHoCH", "structure", "UP" if bullish else "DOWN",
             13 if last_event["event"] == "CHoCH" else 14, label, invalidation)
    elif smc.get("trend") in ("BULLISH", "BEARISH") and len(frame) > 60:
        bullish = smc["trend"] == "BULLISH"
        _add(signals, "Market Structure", "structure", "UP" if bullish else "DOWN", 4,
             f"intact {smc['trend'].lower()} structure",
             "structure break against the trend")

    for block in smc.get("demand_zones", [])[-1:]:
        if block["bottom"] - atr * 0.3 <= price <= block["top"] + atr * 0.3:
            _add(signals, "Order Block", "location", "UP", 8,
                 "price retesting unmitigated demand block",
                 f"close below {block['bottom']:.6f}")
    for block in smc.get("supply_zones", [])[-1:]:
        if block["bottom"] - atr * 0.3 <= price <= block["top"] + atr * 0.3:
            _add(signals, "Order Block", "location", "DOWN", 8,
                 "price retesting unmitigated supply block",
                 f"close above {block['top']:.6f}")

    for gap in smc.get("fair_value_gaps", [])[-2:]:
        if gap["direction"] == "bullish" and gap["top"] <= price + atr * 0.8:
            _add(signals, "Fair Value Gap", "structure", "UP", 6,
                 "unfilled bullish FVG below price",
                 f"close below {gap['bottom']:.6f}")
        if gap["direction"] == "bearish" and gap["bottom"] >= price - atr * 0.8:
            _add(signals, "Fair Value Gap", "structure", "DOWN", 6,
                 "unfilled bearish FVG above price",
                 f"close above {gap['top']:.6f}")

    for sweep in smc.get("liquidity_sweeps", [])[-2:]:
        if len(frame) - 1 - sweep["index"] <= 6:
            bullish = sweep["direction"] == "bullish"
            _add(signals, "Liquidity Sweep / Raid", "liquidity", "UP" if bullish else "DOWN", 9,
                 sweep["type"], f"close beyond swept level {sweep['level']:.6f}")

    if smc.get("equal_highs"):
        level = max(smc["equal_highs"])
        if price <= level + atr * 0.2 and smc.get("trend") == "BEARISH":
            _add(signals, "Buy-side Liquidity", "liquidity", "DOWN", 5,
                 "equal highs above price are a resting liquidity pool",
                 f"acceptance above {level:.6f}")
    if smc.get("equal_lows"):
        level = min(smc["equal_lows"])
        if price >= level - atr * 0.2 and smc.get("trend") == "BULLISH":
            _add(signals, "Sell-side Liquidity", "liquidity", "UP", 5,
                 "equal lows below price are a resting liquidity pool",
                 f"acceptance below {level:.6f}")

    zone = smc.get("premium_discount", {}).get("zone")
    if zone == "DISCOUNT" and smc.get("trend") == "BULLISH":
        _add(signals, "Premium / Discount", "structure", "UP", 5,
             "bullish trend trading from discount", "close below range low")
    if zone == "PREMIUM" and smc.get("trend") == "BEARISH":
        _add(signals, "Premium / Discount", "structure", "DOWN", 5,
             "bearish trend trading from premium", "close above range high")

    if len(frame) >= 3:
        last = frame.iloc[-1]
        body = abs(last["close"] - last["open"])
        if body >= atr * 1.2:
            bullish = last["close"] > last["open"]
            _add(signals, "ICT Displacement", "impulse", "UP" if bullish else "DOWN", 7,
                 "displacement candle beyond normal range",
                 "full retrace of the displacement candle")

    swings = find_swings(frame)
    highs = [s for s in swings if s["kind"] == "high"]
    lows = [s for s in swings if s["kind"] == "low"]
    if highs and lows:
        leg_low, leg_high = lows[-1]["price"], highs[-1]["price"]
        if leg_high > leg_low:
            retrace = (leg_high - price) / (leg_high - leg_low)
            if smc.get("trend") == "BULLISH" and 0.62 <= retrace <= 0.79:
                _add(signals, "Optimal Trade Entry", "location", "UP", 6,
                     "62-79% retracement of bullish leg", f"close below {leg_low:.6f}")
            if smc.get("trend") == "BEARISH" and 0.62 <= (price - leg_low) / (leg_high - leg_low) <= 0.79:
                _add(signals, "Optimal Trade Entry", "location", "DOWN", 6,
                     "62-79% retracement of bearish leg", f"close above {leg_high:.6f}")

    if in_session and len(frame) >= 12:
        window = frame.iloc[-12:]
        if float(window["high"].max()) - float(window["low"].min()) >= atr * 2:
            recent = window.iloc[-1]
            bullish = recent["close"] > recent["open"]
            _add(signals, "ICT Kill Zone", "ict", "UP" if bullish else "DOWN", 5,
                 f"{session} expansion in progress", "range compression inside the session")
        if session.startswith("SILVER BULLET") and smc.get("fair_value_gaps"):
            gap = smc["fair_value_gaps"][-1]
            _add(signals, "ICT Silver Bullet", "ict",
                 "UP" if gap["direction"] == "bullish" else "DOWN", 7,
                 f"{session} FVG entry window", "session close or FVG fill")

    if last_event and last_event["event"] == "CHoCH" and (len(frame) - 1 - last_event["index"]) <= 3:
        last = frame.iloc[-1]
        reversal = "UP" if float(last["close"]) > float(last["open"]) else "DOWN"
        if reversal == ("UP" if last_event["direction"] == "bullish" else "DOWN"):
            _add(signals, "Reversal Confirmation", "confirmation", reversal, 6,
                 "CHoCH followed by a close in the reversal direction",
                 "close back through the CHoCH level")

    # ---- Price action ------------------------------------------------------
    if ind.get("support") and price - ind["support"][0] <= atr * 0.6:
        _add(signals, "Support Reaction", "location", "UP", 5,
             "reaction at support", f"close below {ind['support'][0]:.6f}")
    if ind.get("resistance") and ind["resistance"][0] - price <= atr * 0.6:
        _add(signals, "Resistance Rejection", "location", "DOWN", 5,
             "rejection from resistance", f"close above {ind['resistance'][0]:.6f}")

    if len(frame) > 25:
        prior = frame.iloc[-25:-5]
        prior_high = float(prior["high"].max())
        prior_low = float(prior["low"].min())
        close_prev = float(frame["close"].iloc[-2])
        if close_prev > prior_high and abs(price - prior_high) <= atr * 0.5:
            _add(signals, "Breakout & Retest", "location", "UP", 8,
                 "retest of broken resistance as support", f"close back below {prior_high:.6f}")
        if close_prev < prior_low and abs(price - prior_low) <= atr * 0.5:
            _add(signals, "Breakout & Retest", "location", "DOWN", 8,
                 "retest of broken support as resistance", f"close back above {prior_low:.6f}")
        if float(frame["high"].iloc[-1]) > prior_high and price < prior_high:
            _add(signals, "False Breakout", "liquidity", "DOWN", 7,
                 "failed break above prior high", f"close above {prior_high:.6f}")
        if float(frame["low"].iloc[-1]) < prior_low and price > prior_low:
            _add(signals, "False Breakout", "liquidity", "UP", 7,
                 "failed break below prior low", f"close below {prior_low:.6f}")

    trend_break = trendline_break(frame)
    if trend_break != "NONE":
        _add(signals, "Trendline Break", "structure", "UP" if trend_break == "BULLISH" else "DOWN",
             6, f"{trend_break.lower()} trendline break", "return inside the former trendline")

    for pattern in list(ind.get("patterns", [])) + extended_patterns(frame):
        direction = {"bullish": "UP", "bearish": "DOWN"}.get(pattern["direction"])
        if direction:
            _add(signals, "Candlestick Pattern", "confirmation", direction, 4,
                 f"{pattern['name']} confirmation", "pattern invalidation by the next close")

    # ---- Trend following ---------------------------------------------------
    if ind["trend"] in ("UP", "DOWN"):
        strength = 10 + 10 * ind.get("trend_strength", 0.0)
        _add(signals, "EMA 9/21/50 Stack", "trend", ind["trend"], min(16, strength),
             f"EMA stack aligned {ind['trend'].lower()}", "EMA9 crosses EMA21")
    if ind.get("ema200"):
        direction = "UP" if price > ind["ema200"] else "DOWN"
        _add(signals, "EMA 200 Regime", "trend", direction, 5,
             f"price {'above' if direction == 'UP' else 'below'} EMA 200", "close through EMA 200")
    close = frame["close"]
    e9 = close.ewm(span=9, adjust=False).mean()
    e21 = close.ewm(span=21, adjust=False).mean()
    if len(frame) >= 22:
        if e9.iloc[-1] > e21.iloc[-1] and e9.iloc[-2] <= e21.iloc[-2]:
            _add(signals, "MA Crossover", "trend_strength", "UP", 7,
                 "EMA 9 crossed above EMA 21", "cross back below EMA21")
        elif e9.iloc[-1] < e21.iloc[-1] and e9.iloc[-2] >= e21.iloc[-2]:
            _add(signals, "MA Crossover", "trend_strength", "DOWN", 7,
                 "EMA 9 crossed below EMA 21", "cross back above EMA21")
    if adx_value >= 20 and di_up != di_down:
        direction = "UP" if di_up > di_down else "DOWN"
        _add(signals, "ADX / DI", "trend_strength", direction, min(12, 4 + adx_value / 5),
             f"ADX {adx_value:.1f} with {'+DI' if direction == 'UP' else '-DI'} dominant",
             "ADX below 18 or DI flip")
    _add(signals, "Supertrend", "trend_strength", st_direction, 9,
         f"Supertrend {'bullish' if st_direction == 'UP' else 'bearish'}",
         f"close through {st_value:.6f}")
    if ind["macd_hist"] != 0:
        direction = "UP" if ind["macd_hist"] > 0 else "DOWN"
        accelerating = (ind["macd_hist"] > ind["macd_hist_prev"]) if direction == "UP" else (
            ind["macd_hist"] < ind["macd_hist_prev"]
        )
        _add(signals, "MACD Trend", "macd", direction, 8 if accelerating else 5,
             f"MACD histogram {'positive' if direction == 'UP' else 'negative'}",
             "MACD histogram flip")
    labels = smc.get("labels", [])
    if labels and labels[-2:] in (["HL", "HH"], ["HH", "HL"]):
        _add(signals, "Higher Highs / Higher Lows", "swing", "UP", 6,
             f"swing labels {labels[-2:]}", "lower low forms")
    if labels and labels[-2:] in (["LH", "LL"], ["LL", "LH"]):
        _add(signals, "Lower Highs / Lower Lows", "swing", "DOWN", 6,
             f"swing labels {labels[-2:]}", "higher high forms")
    if mtf["aligned"]:
        _add(signals, "Multi-Timeframe Trend", "mtf", mtf["direction"], 9,
             f"short/medium/long all {mtf['direction']}", "any higher timeframe flips")
    elif mtf["direction"] == "MIXED":
        warnings.append("Timeframes disagree: confidence is reduced")

    # ---- Momentum / reversal ----------------------------------------------
    rsi_vals = rsi(close)
    _, _, hist = macd(close)
    rsi_div = rsi_divergence(frame, rsi_vals)
    macd_div = macd_divergence(frame, hist)
    if rsi_div != "NONE":
        _add(signals, "RSI Divergence", "divergence", "UP" if rsi_div == "BULLISH" else "DOWN", 8,
             f"{rsi_div.lower()} RSI divergence", "divergence level broken")
    if macd_div != "NONE":
        _add(signals, "MACD Divergence", "divergence", "UP" if macd_div == "BULLISH" else "DOWN", 7,
             f"{macd_div.lower()} MACD divergence", "divergence level broken")
    if ind["stoch_cross"] in ("BULLISH", "BEARISH"):
        _add(signals, "Stochastic Cross", "stochastic",
             "UP" if ind["stoch_cross"] == "BULLISH" else "DOWN", 4,
             f"stochastic {ind['stoch_cross'].lower()} cross", "cross reverses")
    mean_reversion_allowed = profile is None or profile.allow_mean_reversion
    if mean_reversion_allowed and price < ind["bb_lower"] and close.iloc[-1] > close.iloc[-2]:
        _add(signals, "Bollinger Mean Reversion", "mean_reversion", "UP", 5,
             "close reclaiming lower Bollinger band", "new low below the band")
    if mean_reversion_allowed and price > ind["bb_upper"] and close.iloc[-1] < close.iloc[-2]:
        _add(signals, "Bollinger Mean Reversion", "mean_reversion", "DOWN", 5,
             "close rejecting upper Bollinger band", "new high above the band")
    vwap_line = vwap(frame)
    if vwap_line is not None:
        value = float(vwap_line.iloc[-1])
        if price > value * 1.001:
            _add(signals, "VWAP", "vwap", "UP", 4, "price above VWAP", "close below VWAP")
        elif price < value * 0.999:
            _add(signals, "VWAP", "vwap", "DOWN", 4, "price below VWAP", "close above VWAP")
    if len(frame) > 20:
        breakout_high = float(frame["high"].iloc[-21:-1].max())
        breakout_low = float(frame["low"].iloc[-21:-1].min())
        if price > breakout_high:
            _add(signals, "Momentum Breakout", "momentum", "UP", 8,
                 "close above the prior 20-bar high", f"close below {breakout_high:.6f}")
        elif price < breakout_low:
            _add(signals, "Momentum Breakout", "momentum", "DOWN", 8,
                 "close below the prior 20-bar low", f"close above {breakout_low:.6f}")

    if ind["volatility"] == "HIGH":
        warnings.append("High ATR regime: wider stops and shorter expiries are safer")

    return StrategyReport(
        signals=signals,
        mtf=mtf,
        session=session,
        context={
            "adx": round(adx_value, 2),
            "plus_di": round(di_up, 2),
            "minus_di": round(di_down, 2),
            "supertrend": st_direction,
            "vwap": float(vwap_line.iloc[-1]) if vwap_line is not None else None,
            "warnings": warnings,
        },
    )
