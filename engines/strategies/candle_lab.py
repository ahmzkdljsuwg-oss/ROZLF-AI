"""Deterministic OHLC research readings, separate from live signal scoring.

Every row sees only its own completed candle and earlier contiguous candles.
Correlated rules are grouped for display, not counted as independent votes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RULES = {
    "ema_stack": ("trend", "EMA 9/21/50/200", 200),
    "alligator": ("trend", "Alligator + MA 200", 200),
    "macd_cross": ("momentum", "MACD cross", 101),
    "rate_of_change": ("momentum", "Rate of change", 16),
    "rsi_recovery": ("reversal", "RSI recovery", 66),
    "bollinger_reentry": ("reversal", "Bollinger re-entry", 21),
    "stochastic_turn": ("reversal", "Stochastic turn", 18),
    "donchian_break": ("structure", "Donchian breakout", 21),
    "liquidity_sweep": ("structure", "Liquidity sweep", 21),
    "engulfing": ("price_action", "Engulfing", 15),
    "pin_bar": ("price_action", "Pin bar", 15),
    "inside_break": ("price_action", "Inside bar break", 15),
}
FAMILIES = ("trend", "momentum", "reversal", "structure", "price_action")
SIDES = {-1: "DOWN", 0: "NEUTRAL", 1: "UP"}


def _ema(series, period, window):
    # Resettable finite lookback, so replay and live match on equal tails.
    decay = (period - 1) / (period + 1)
    weights = (1 - decay) * decay ** np.arange(window, dtype=float)
    weights[-1] = decay ** (window - 1)  # Seed from the oldest close.
    values = np.convolve(series.to_numpy(dtype=float), weights, mode="full")[:len(series)]
    values[:window - 1] = np.nan
    return pd.Series(values, index=series.index)


def _block(frame):
    op, hi, lo, cl = (frame[k].astype(float) for k in ("open", "high", "low", "close"))
    prev = cl.shift()
    true_range = pd.concat([hi - lo, (hi - prev).abs(), (lo - prev).abs()], axis=1).max(axis=1)
    atr = true_range.rolling(14).mean()
    active = (atr > 0) & ((hi - lo) <= atr * 3)
    body = cl - op
    mid = (hi + lo) / 2
    upper_wick = hi - pd.concat([cl, op], axis=1).max(axis=1)
    lower_wick = pd.concat([cl, op], axis=1).min(axis=1) - lo
    e9, e21, e50, e200 = (_ema(cl, n, w) for n, w in ((9, 28), (21, 64), (50, 150), (200, 200)))
    jaw, teeth, lips = (_ema(mid, 2*n-1, 5*n).shift(shift) for n, shift in ((13, 8), (8, 5), (5, 3)))
    sma200 = cl.rolling(200).mean()
    macd = _ema(cl, 12, 36) - _ema(cl, 26, 78)
    hist = macd - _ema(macd, 9, 23)
    mom = cl - cl.shift(5)
    delta = cl.diff()
    gains = _ema(delta.clip(lower=0), 27, 64)
    losses = _ema(-delta.clip(upper=0), 27, 64)
    rsi = 100 * gains / (gains + losses).replace(0, np.nan)
    rsi = rsi.mask((gains == 0) & (losses == 0), 50)
    avg = cl.rolling(20).mean()
    sd = cl.rolling(20).std(ddof=0)
    upper, lower = avg + 2 * sd, avg - 2 * sd
    bottom, top = lo.rolling(14).min(), hi.rolling(14).max()
    k = (cl - bottom) / (top - bottom).replace(0, np.nan) * 100
    d = k.rolling(3).mean()
    prior_high, prior_low = hi.shift().rolling(20).max(), lo.shift().rolling(20).min()
    inside = (hi.shift() <= hi.shift(2)) & (lo.shift() >= lo.shift(2)) & (hi.shift(2) > lo.shift(2))
    tests = {
        "ema_stack": ((e9 > e21) & (e21 > e50) & (cl > e200), (e9 < e21) & (e21 < e50) & (cl < e200)),
        "alligator": ((lips > teeth) & (teeth > jaw) & (cl > sma200), (lips < teeth) & (teeth < jaw) & (cl < sma200)),
        "macd_cross": ((hist > 0) & (hist.shift() <= 0), (hist < 0) & (hist.shift() >= 0)),
        "rate_of_change": (mom >= atr * .75, mom <= -atr * .75),
        "rsi_recovery": ((rsi > 30) & (rsi.shift() <= 30), (rsi < 70) & (rsi.shift() >= 70)),
        "bollinger_reentry": ((prev < lower.shift()) & (cl >= lower) & (body > 0),
                              (prev > upper.shift()) & (cl <= upper) & (body < 0)),
        "stochastic_turn": ((k > d) & (k.shift() <= d.shift()) & (k.shift() < 20),
                            (k < d) & (k.shift() >= d.shift()) & (k.shift() > 80)),
        "donchian_break": (cl > prior_high, cl < prior_low),
        "liquidity_sweep": ((lo < prior_low) & (cl > prior_low) & (body > 0),
                            (hi > prior_high) & (cl < prior_high) & (body < 0)),
        "engulfing": ((body > 0) & (body.shift() < 0) & (op <= prev) & (cl >= op.shift()),
                      (body < 0) & (body.shift() > 0) & (op >= prev) & (cl <= op.shift())),
        "pin_bar": ((lower_wick > (hi-lo)*.60) & (body > 0) & (body.abs() <= (hi-lo)*.35),
                    (upper_wick > (hi-lo)*.60) & (body < 0) & (body.abs() <= (hi-lo)*.35)),
        "inside_break": (inside & (cl > hi.shift(2)), inside & (cl < lo.shift(2))),
    }
    result = pd.DataFrame(index=frame.index)
    for key, (up, down) in tests.items():
        minimum = RULES[key][2]
        # Keep ambiguous and inactive setups neutral, and unavailable rows null.
        result[key] = (up.astype(int) - down.astype(int)).where(active, 0).where(np.arange(len(frame)) >= minimum-1)
    return result


def strategy_series(frame: pd.DataFrame, seconds: int) -> pd.DataFrame:
    """Return causal integer readings, with NaN for unavailable inputs."""
    if frame.empty:
        return pd.DataFrame(index=frame.index, columns=list(RULES), dtype=float)
    if seconds <= 0 or not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("expected increasing native candle timestamps")
    ohlc = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
    op, hi, lo, cl = ohlc.T
    valid = (np.isfinite(ohlc).all(axis=1) & (ohlc > 0).all(axis=1)
             & (lo <= np.minimum(op, cl)) & (hi >= np.maximum(op, cl)))
    step = pd.Timedelta(seconds=seconds)
    continuous = (frame.index.to_series().diff() == step).to_numpy(copy=True)
    continuous[1:] &= valid[1:] & valid[:-1]
    result = []
    starts = np.flatnonzero(~continuous)
    for start, end in zip(starts, [*starts[1:], len(frame)]):
        part = frame.iloc[start:end]
        result.append(_block(part) if valid[start] and len(part) >= 15 else
                      pd.DataFrame(None, index=part.index, columns=list(RULES), dtype=float))
    return pd.concat(result)


def family_series(readings: pd.DataFrame) -> pd.DataFrame:
    families = pd.DataFrame(index=readings.index)
    for family in FAMILIES:
        rules = readings[[key for key, (group, _, _) in RULES.items() if group == family]]
        up, down = (rules == 1).any(axis=1), (rules == -1).any(axis=1)
        families[family] = (up.astype(int) - down.astype(int)).where(rules.notna().any(axis=1))
    return families


def strategy_snapshot(frame: pd.DataFrame, seconds: int) -> list[dict]:
    if frame.empty:
        return []
    history = strategy_series(frame.tail(201), seconds)
    last = history.iloc[-1]
    result = []
    for family in FAMILIES:
        members = [{"key": key, "name": name, "state": "UNAVAILABLE" if pd.isna(last[key]) else SIDES[int(last[key])]}
                   for key, (group, name, _) in RULES.items() if group == family]
        states = {m["state"] for m in members}
        sides = states & {"UP", "DOWN"}
        state = "MIXED" if len(sides) == 2 else next(iter(sides), "UNAVAILABLE" if states == {"UNAVAILABLE"} else "NEUTRAL")
        result.append({"key": family, "state": state, "rules": members})
    return result
