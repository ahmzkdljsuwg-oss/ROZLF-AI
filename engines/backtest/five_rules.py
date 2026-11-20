"""Five fixed candle-direction hypotheses for offline comparison only."""
from __future__ import annotations

import numpy as np
import pandas as pd

RULES = (
    "ema_cross_9_21_200",
    "bollinger_rsi",
    "alligator_sma200",
    "breakout_retest",
    "atr_regime",
)
WARMUP = 220
TARGET_OFFSET = 2
OHLC = ["open", "high", "low", "close"]


def _side(up: pd.Series, down: pd.Series) -> pd.Series:
    return up.astype(int) - down.astype(int)


def _breakout_retest(op, hi, lo, cl, atr) -> pd.Series:
    """Freeze the broken level, then look for confirmation on a later bar."""
    upper = hi.shift().rolling(20).max()
    lower = lo.shift().rolling(20).min()
    direction, level, started = 0, 0.0, 0
    out = []
    for i, (o, h, l, c, vol, top, bottom) in enumerate(zip(op, hi, lo, cl, atr, upper, lower)):
        result = 0
        if not np.isfinite(top) or not np.isfinite(vol) or vol <= 0:
            out.append(0)
            continue
        if direction:
            if i - started > 5 or (c - level) * direction < 0:
                direction = 0
            elif (direction == 1 and l <= level + .15 * vol and c > max(level, o)) or (
                    direction == -1 and h >= level - .15 * vol and c < min(level, o)):
                result, direction = direction, 0
        if not direction and not result:
            if c > top + .10 * vol:
                direction, level, started = 1, top, i
            elif c < bottom - .10 * vol:
                direction, level, started = -1, bottom, i
        out.append(result)
    return pd.Series(out, index=cl.index)


def _read_block(frame: pd.DataFrame) -> pd.DataFrame:
    op, hi, lo, cl = (frame[col] for col in OHLC)
    prev = cl.shift()
    tr = pd.concat((hi - lo, (hi - prev).abs(), (lo - prev).abs()), axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    e9, e21, e200 = (cl.ewm(span=n, adjust=False, min_periods=n).mean() for n in (9, 21, 200))
    cross = _side((e9 > e21) & (e9.shift() <= e21.shift()) & (cl > e200),
                  (e9 < e21) & (e9.shift() >= e21.shift()) & (cl < e200))

    move = cl.diff()
    gain = move.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-move.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rsi = (100 * gain / (gain + loss).replace(0, np.nan)).mask((gain == 0) & (loss == 0), 50)
    mean, sd = cl.rolling(20).mean(), cl.rolling(20).std(ddof=0)
    high_band, low_band = mean + 2 * sd, mean - 2 * sd
    reversion = _side((prev < low_band.shift()) & (rsi.shift() <= 30) & (cl >= low_band) & (cl > op),
                      (prev > high_band.shift()) & (rsi.shift() >= 70) & (cl <= high_band) & (cl < op))

    mid = (hi + lo) / 2
    jaw, teeth, lips = (
        mid.ewm(alpha=1/n, adjust=False, min_periods=n).mean().shift(shift)
        for n, shift in ((13, 8), (8, 5), (5, 3))
    )
    sma = cl.rolling(200).mean()
    spread = (lips - jaw).abs()
    alligator = _side((lips > teeth) & (teeth > jaw) & (cl > sma),
                      (lips < teeth) & (teeth < jaw) & (cl < sma))
    alligator = alligator.where((spread >= .10 * atr) & (spread > spread.shift()), 0)

    # Use ATR for relative volatility, and path efficiency for trend/range.
    typical_atr = atr.shift().rolling(60).median()
    relative_atr = atr / typical_atr.replace(0, np.nan)
    efficiency = (cl - cl.shift(20)).abs() / move.abs().rolling(20).sum().replace(0, np.nan)
    calm = relative_atr.between(.65, 1.60) & (tr <= 2.5 * atr.shift())
    regime = cross.where(calm & (efficiency >= .45), 0)
    regime = regime.mask(calm & (efficiency <= .25), reversion)

    readings = pd.DataFrame(dict(zip(RULES, (
        cross, reversion, alligator, _breakout_retest(op, hi, lo, cl, atr), regime,
    ))))
    ready = pd.Series(np.arange(len(frame)) >= WARMUP - 1, index=frame.index)
    return readings.where(ready, axis=0)


def _segments(frame: pd.DataFrame, seconds: int) -> tuple[pd.Series, pd.Series]:
    if (seconds <= 0 or not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None
            or frame.index.hasnans or frame.index.has_duplicates or not frame.index.is_monotonic_increasing):
        raise ValueError("expected increasing, unique, timezone-aware candle opens")
    values = frame[OHLC].astype(float)
    op, hi, lo, cl = (values[c] for c in OHLC)
    good = (np.isfinite(values).all(axis=1) & (values > 0).all(axis=1)
            & (hi >= np.maximum(op, cl)) & (lo <= np.minimum(op, cl)))
    starts = (frame.index.to_series().diff() != pd.Timedelta(seconds=seconds)
              ) | ~good | ~good.shift(fill_value=False)
    return good, starts.cumsum()


def strategy_readings(frame: pd.DataFrame, seconds: int) -> pd.DataFrame:
    """Use only each row's closed OHLC and earlier valid contiguous history."""
    good, groups = _segments(frame, seconds)
    parts = [_read_block(part.astype(float)) for _, part in frame.loc[good].groupby(groups[good])]
    return pd.concat(parts).reindex(frame.index) if parts else pd.DataFrame(
        index=frame.index, columns=list(RULES), dtype=float,
    )


def _metrics(actual, predicted, previous, majority, payout, cost) -> dict:
    selected = predicted.isin((-1, 1))
    actual, predicted = actual[selected], predicted[selected]
    n = len(actual)
    wins = int((actual == predicted).sum())
    draws = int((actual == 0).sum())
    losses = n - wins - draws
    return {
        "eligible": len(selected),
        "selected": n,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "hit_rate_pct": round(100 * wins / n, 2) if n else None,
        "scenario_net_per_forecast": round((wins * payout - losses - n * cost) / n, 6) if n else None,
        "coverage_pct": round(100 * n / len(selected), 2) if len(selected) else None,
        "baselines": {
            "previous_candle_wins": int((actual == previous[selected]).sum()),
            "past_majority_wins": int((actual == majority[selected]).sum()),
            "always_up_wins": int((actual == 1).sum()),
            "always_down_wins": int((actual == -1).sum()),
        },
    }


def replay(frame: pd.DataFrame, seconds: int, *, as_of, evaluate_from=None,
           payout: float = .80, cost: float = 0.) -> dict:
    """Evaluate i+2 direction, with fixed rules and same-row baselines."""
    if not (np.isfinite(payout) and 0 < payout <= 1 and np.isfinite(cost) and 0 <= cost < payout):
        raise ValueError("payout must be in (0, 1]; cost must be nonnegative and below payout")
    step = pd.Timedelta(seconds=seconds)
    if pd.Timestamp(as_of).tzinfo is None or (evaluate_from is not None and pd.Timestamp(evaluate_from).tzinfo is None):
        raise ValueError("cutoffs must be timezone-aware")
    good, groups = _segments(frame, seconds)
    settled = frame.index + step <= as_of
    frame, good, groups = frame.loc[settled, OHLC].astype(float), good.loc[settled], groups.loc[settled]
    readings = strategy_readings(frame, seconds)
    times = frame.index.to_series()
    body = _side(frame.close > frame.open, frame.close < frame.open).where(good)
    target = body.shift(-TARGET_OFFSET)
    decision = times + step
    # At i+1's open, i+2 is still in the future. Skip gaps and invalid targets.
    available = (readings.notna().all(axis=1) & target.notna()
                 & (groups == groups.shift(-TARGET_OFFSET)))
    if evaluate_from is not None:
        available &= decision >= evaluate_from
    # At the decision boundary, bar i has only just closed. The learned
    # comparator uses only strictly earlier settled outcomes.
    history_up = (body == 1).cumsum().shift(fill_value=0)
    history_down = (body == -1).cumsum().shift(fill_value=0)
    majority = pd.Series(np.where(history_up >= history_down, 1, -1), index=frame.index)
    previous = body.where(body != 0, majority)
    idx = times[available].index
    folds = []
    for positions in np.array_split(np.arange(len(idx)), 3):
        if len(positions) == 0:
            continue
        selected = idx[positions]
        folds.append({
            "first_decision": decision.loc[selected[0]].isoformat(),
            "last_decision": decision.loc[selected[-1]].isoformat(),
            "eligible": len(selected),
            "rules": {name: _metrics(target.loc[selected], readings.loc[selected, name],
                                      previous.loc[selected], majority.loc[selected], payout, cost) for name in RULES},
        })
    return {
        "closed_bars": len(frame),
        "eligible": len(idx),
        "rules": {name: _metrics(target.loc[idx], readings.loc[idx, name],
                                 previous.loc[idx], majority.loc[idx], payout, cost) for name in RULES},
        "folds": folds,
    }
