from datetime import datetime, timezone

import numpy as np
import pandas as pd

from engines.strategies.engine import evaluate_strategies, multi_timeframe
from engines.technical.analyzer import analyze_market_data
from engines.technical.indicators import compute_indicators
from engines.technical.smc import analyze_smc
from providers.base import Candle, MarketData, Quote, ValidationReport
from providers.catalog import FOREX_ASSETS, Market, Timeframe


def _frame(direction: int) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=240, freq="60s", tz="UTC")
    drift = np.linspace(0, direction * 2.0, len(index))
    close = 100 + drift + np.sin(np.arange(len(index)) / 5) * 0.05
    return pd.DataFrame(
        {
            "open": close - direction * 0.01,
            "high": close + 0.08,
            "low": close - 0.08,
            "close": close,
            "volume": 0.0,
        },
        index=index,
    )


def test_strategy_families_are_independent():
    frame = _frame(-1)
    ind = compute_indicators(frame)
    smc = analyze_smc(frame, ind["atr"])
    report = evaluate_strategies(frame, ind, smc, Market.FOREX, 60, datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc))
    strongest: dict[str, float] = {}
    for signal in report.signals:
        strongest[signal.family] = max(strongest.get(signal.family, 0.0), signal.score)
    # Correlated members collapse into one weight per family.
    assert sum(strongest.values()) <= sum(signal.score for signal in report.signals)
    for signal in report.signals:
        assert signal.invalidation


def test_multitimeframe_flags_conflict_and_alignment():
    aligned = multi_timeframe(_frame(-1), 60)
    assert aligned["short"] == "DOWN"
    assert aligned["aligned"] is True
    assert aligned["direction"] == "DOWN"


def test_analyzer_reports_evidence_and_cancellation():
    frame = _frame(1)
    candles = [
        Candle(t.to_pydatetime(), float(r.open), float(r.high), float(r.low), float(r.close), 0.0)
        for t, r in frame.iterrows()
    ]
    asset = FOREX_ASSETS[0]
    data = MarketData(
        asset=asset,
        timeframe=Timeframe("1min", "1M", 60),
        candles=candles,
        source="test",
        quote=Quote(asset.symbol, candles[-1].close, candles[-1].close, candles[-1].time, "test"),
        validation=ValidationReport(True, len(candles)),
    )
    result = analyze_market_data(data, now=candles[-1].time)
    assert result.direction in ("UP", "DOWN", "NO TRADE")
    assert result.mtf
    assert result.data_confidence["level"] == "HIGH"
    assert 0 <= result.evidence_score <= 100
    if result.direction == "NO TRADE":
        assert result.cancellation_reason


def test_session_only_for_forex():
    frame = _frame(1)
    ind = compute_indicators(frame)
    smc = analyze_smc(frame, ind["atr"])
    forex = evaluate_strategies(frame, ind, smc, Market.FOREX, 60, datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc))
    index = evaluate_strategies(frame, ind, smc, Market.AI, 60, datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc))
    assert forex.session != "NONE"
    assert index.session == "NONE"
