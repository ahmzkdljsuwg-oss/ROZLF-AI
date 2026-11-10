from datetime import datetime, timedelta, timezone

import numpy as np

from engines.backtest.runner import BacktestConfig, BacktestTrade, compute_metrics, run_backtest
from providers.base import Candle
from providers.catalog import FOREX_ASSETS, Timeframe

ASSET = FOREX_ASSETS[0]
TF = Timeframe("1min", "1M", 60)


def _candles(count: int = 260) -> list[Candle]:
    rng = np.random.default_rng(7)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    prices = 100 + np.cumsum(rng.normal(0, 0.04, count))
    return [
        Candle(start + timedelta(minutes=i), float(p), float(p + 0.05), float(p - 0.05), float(p), 0.0)
        for i, p in enumerate(prices)
    ]


def test_no_lookahead_future_candles_do_not_change_earlier_trades():
    candles = _candles()
    cutoff = 180
    mutated = list(candles)
    for index in range(cutoff, len(mutated)):
        candle = mutated[index]
        mutated[index] = Candle(candle.time, candle.open * 1.1, candle.high * 1.1, candle.low * 1.1, candle.close * 1.1)

    config = BacktestConfig(ASSET, TF, 300, warmup_bars=150)
    base = run_backtest(config, candles, "test")
    other = run_backtest(config, mutated, "test")
    horizon = candles[cutoff].time
    base_early = [t for t in base.trades if t.expiry_time <= horizon]
    other_early = [t for t in other.trades if t.expiry_time <= horizon]
    assert base_early
    assert [(t.decision_index, t.result, t.entry_price) for t in base_early] == [
        (t.decision_index, t.result, t.entry_price) for t in other_early
    ]


def test_metrics_exclude_draws_from_win_rate():
    trades = [
        BacktestTrade(0, datetime.now(timezone.utc), datetime.now(timezone.utc), "UP", 70, 1.0, 1.1, "WIN"),
        BacktestTrade(1, datetime.now(timezone.utc), datetime.now(timezone.utc), "UP", 70, 1.0, 0.9, "LOSS"),
        BacktestTrade(2, datetime.now(timezone.utc), datetime.now(timezone.utc), "UP", 70, 1.0, 1.0, "DRAW"),
    ]
    metrics = compute_metrics(trades)
    assert metrics.win_rate == 50.0
    assert metrics.profit_factor == 1.0
    assert metrics.expectancy == 0.0
    assert metrics.max_drawdown == 1.0
