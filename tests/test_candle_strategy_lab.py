from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pandas as pd
from bot.formatting import nexus_signal_text
from engines.strategies.candle_lab import FAMILIES, RULES, family_series, strategy_series, strategy_snapshot
from engines.strategies.engine import _resample
from engines.technical.analyzer import analyze_market_data
from engines.technical.indicators import frame_from_candles
from engines.validation import validate_candles
from providers.base import MarketData, ValidationReport
from providers.catalog import SMARTY_ASSET, timeframe
from scripts.audit_candle_strategies import evaluate
from tests.conftest import make_candles


def _bars(n=380):
    end = datetime(2026, 11, 18, 14, tzinfo=timezone.utc)
    return make_candles(n=n, tf_seconds=30, end=end)


def test_replay_and_live_agree_without_future_rows():
    frame = frame_from_candles(_bars())
    cutoff = len(frame) - 30
    history = strategy_series(frame, 30)
    same_prefix = strategy_series(frame.iloc[:cutoff], 30)
    pd.testing.assert_frame_equal(history.iloc[:cutoff], same_prefix)
    snap = strategy_snapshot(frame.iloc[:cutoff], 30)
    observed = {rule["key"]: rule["state"] for family in snap for rule in family["rules"]}
    sides = {1: "UP", -1: "DOWN", 0: "NEUTRAL"}
    assert list(FAMILIES) == [family["key"] for family in snap]
    assert set(observed) == set(RULES)
    assert observed == {k: sides[history.iloc[cutoff-1][k]] for k in RULES}


def test_malformed_bar_or_gap_restarts_features():
    bars = _bars()
    gap = frame_from_candles(bars[:-2] + bars[-1:])
    assert strategy_series(gap, 30).iloc[-1].isna().all()
    bars[-2] = replace(bars[-2], high=float("nan"))
    assert not validate_candles(bars, timeframe("30sec"), now=bars[-1].time).ok
    corrupted = strategy_series(frame_from_candles(bars), 30)
    assert corrupted.iloc[-2:].isna().all(axis=None)


def test_disagreeing_rules_do_not_stack_one_family():
    rules = pd.DataFrame({k: [float("nan"), 0.0] for k in RULES})
    rules.loc[1, ["bollinger_reentry", "rsi_recovery"]] = [1, -1]
    out = family_series(rules)
    assert pd.isna(out.loc[0, "reversal"]) and out.loc[1, "reversal"] == 0


def test_mtf_uses_only_full_buckets_at_native_multiples():
    raw = frame_from_candles(_bars(9))
    raw.index = pd.date_range("2026-11-18T14:00:00Z", periods=len(raw), freq="30s")
    closed = _resample(raw.iloc[:8], 30, 3)
    assert [timestamp.strftime("%M:%S") for timestamp in closed.index] == ["00:00", "01:30"]
    assert closed.close.iloc[-1] == raw.close.iloc[5]
    missing = _resample(raw.iloc[:8].drop(raw.index[4]), 30, 3)
    assert missing.empty


def test_pro_readings_ignore_a_forming_bar_and_do_not_turn_into_a_signal():
    bars = _bars()
    now = bars[-1].time + timedelta(seconds=1)
    data = MarketData(SMARTY_ASSET, timeframe("30sec"), bars, "bridge", None,
                      ValidationReport(True, len(bars)), fetched_at=now)
    changed = bars[:-1] + [replace(bars[-1], high=900.0, close=899.0)]
    first = analyze_market_data(data, now=now, analysis_mode="pro")
    second = analyze_market_data(replace(data, candles=changed), now=now, analysis_mode="pro")
    assert first.strategy_readings == second.strategy_readings
    assert len(first.strategy_readings) == len(FAMILIES)
    assert first.direction == "NO TRADE" and not first.confidence_verified
    rendered = nexus_signal_text("smarty", first.direction, 30, None, strategy_readings=first.strategy_readings)
    assert "قراءة الشموع المغلقة · ليست توصية" in rendered
    assert "NO TRADE" in rendered and "🎯 الثقة" not in rendered


def test_replay_counts_baselines_on_identical_candles_and_respects_end():
    sample = frame_from_candles(_bars())
    summary = evaluate(sample, 30)
    assert summary["eligible"] == len(sample) - int(.4*len(sample)) - 2
    assert len(summary["folds"]) == 3
    for row in summary["rules"].values():
        assert max(row["wins"], row["ties"], row["majority"], row["last_candle"]) <= row["n"] <= summary["eligible"]


def test_pro_does_not_patch_over_a_historical_gap_to_get_200_bars():
    bars = _bars()
    del bars[-122]
    now = bars[-1].time + timedelta(seconds=1)
    data = MarketData(SMARTY_ASSET, timeframe("30sec"), bars, "bridge", None,
                      ValidationReport(True, len(bars)), fetched_at=now)
    result = analyze_market_data(data, now=now, analysis_mode="pro")
    assert result.closed_candles == 120
    assert result.direction == "NO TRADE" and "120" in result.reasons[0]
    assert result.strategy_readings[0]["state"] == "UNAVAILABLE"
