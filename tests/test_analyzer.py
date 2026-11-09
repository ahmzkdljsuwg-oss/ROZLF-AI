from __future__ import annotations

from rozlf.engines.technical.analyzer import NO_TRADE, analyze
from conftest import flat_candles, make_candles


def test_analysis_returns_plan_or_no_trade(candles):
    result = analyze(candles, 300)
    assert result.direction in ("UP", "DOWN", NO_TRADE)
    if result.direction != NO_TRADE:
        assert result.entry and result.stop and result.target
        assert result.score >= 0
        assert result.reasons


def test_uptrend_bias_is_up(candles):
    result = analyze(make_candles(240, trend=0.0006), 300)
    assert result.bull >= result.bear


def test_high_threshold_rejects(candles):
    strict = analyze(candles, 300, min_score=99)
    assert strict.direction == NO_TRADE
    assert strict.warnings


def test_stop_side_matches_direction(candles):
    result = analyze(candles, 300)
    if result.direction == "UP":
        assert result.stop < result.entry
        assert result.target > result.entry
    if result.direction == "DOWN":
        assert result.stop > result.entry
        assert result.target < result.entry


def test_too_few_candles_no_trade():
    assert analyze(make_candles(20), 300).direction == NO_TRADE
