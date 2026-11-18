from datetime import timedelta

import pandas as pd
import pytest

from engines.technical.indicators import frame_from_candles
from engines.technical.regime_candle import WARMUP, contiguous_tail, decide_regime, regime_features
from tests.conftest import make_candles


def test_features_are_prefix_invariant_and_window_bounded():
    full = frame_from_candles(make_candles(270, tf_seconds=5))
    only_known = full.iloc[:245]
    changed = full.copy()
    changed.iloc[245:, :4] *= 17
    pd.testing.assert_series_equal(regime_features(changed).iloc[244],
                                   regime_features(only_known.tail(WARMUP)).iloc[-1])


def test_missing_bar_is_not_treated_as_an_adjacent_candle():
    full = frame_from_candles(make_candles(WARMUP + 5, tf_seconds=15))
    assert contiguous_tail(full, 15)
    assert not contiguous_tail(full.drop(full.index[-4]), 15)
    assert not contiguous_tail(full, 5)
    assert not contiguous_tail(full.head(WARMUP - 1), 15)


def sample(**kwargs):
    return {"volatility": 1.0, "shock": 1.0, "efficiency": 0.45, "bias": 1.0, "ma_slope": 0.1,
            "jaw": 1.0, "teeth": 1.1, "lips": 1.2, "body": 0.4, "placement": 0.85,
            "short_momentum": 0.5, "sweep_low": False, "sweep_high": False,
            "extension_up": 0.1, "extension_down": -1.0, **kwargs}


@pytest.mark.parametrize("changes,regime,direction", [
    ({}, "TREND", "UP"),
    ({"shock": 3}, "VOLATILE", "NO TRADE"),
    ({"volatility": 1.8}, "VOLATILE", "NO TRADE"),
    ({"sweep_high": True}, "TREND", "NO TRADE"),
    ({"efficiency": 0.23}, "MIXED", "NO TRADE"),
    ({"efficiency": 0.10, "sweep_low": True}, "RANGE", "UP"),
    ({"efficiency": 0.10, "sweep_low": True, "sweep_high": True}, "RANGE", "NO TRADE"),
    ({"bias": -1.0, "lips": 0.9, "teeth": 1.0, "jaw": 1.1, "ma_slope": -0.1,
      "body": -0.4, "placement": 0.15, "short_momentum": -0.5}, "TREND", "DOWN"),
])
def test_distinguishes_trends_ranges_and_volatility(changes, regime, direction):
    result = decide_regime(sample(**changes))
    assert (result.regime, result.direction) == (regime, direction)


def test_replay_labels_exact_future_candle_and_skips_gaps():
    from scripts.replay_smarty_regime import _window

    frame = frame_from_candles(make_candles(WARMUP + 8, tf_seconds=5))
    changed = frame.copy()
    target = changed.index[WARMUP + 1]
    changed.loc[target, "open"] = changed.loc[target, "close"] + 0.001
    rows = _window(changed, 5)
    assert rows[0]["target"] == frame.index[WARMUP - 1] + timedelta(seconds=10)
    assert rows[0]["label"] == "DOWN"
    assert _window(changed.drop(changed.index[WARMUP]), 5) == []


@pytest.mark.parametrize("forming", [True, False])
def test_smarty_targets_same_future_slot_with_or_without_forming_bar(forming):
    from dataclasses import replace
    from datetime import datetime, timezone

    from engines.technical.analyzer import analyze_market_data
    from engines.validation import validate_candles
    from providers.base import MarketData
    from providers.catalog import SMARTY_ASSET, timeframe

    tf = timeframe("5sec")
    slot_start = datetime(2026, 11, 16, 15, 30, tzinfo=timezone.utc)
    now = slot_start + timedelta(seconds=2)
    complete = make_candles(260, tf_seconds=5, end=slot_start - timedelta(seconds=5))
    ticks = [replace(complete[-1], time=slot_start)] if forming else []
    candles = complete + ticks
    data = MarketData(asset=SMARTY_ASSET, timeframe=tf, candles=candles, source="test", quote=None,
                      validation=validate_candles(candles, tf, now=now))
    result = analyze_market_data(data, now=now, analysis_mode="lo")
    expected = slot_start + timedelta(seconds=5)
    assert result.target_open_at == expected
    assert result.closed_candles == len(complete)
    assert result.next_candle["regime"] != "UNREADY"
    from providers.base import DataUnavailable
    with pytest.raises(DataUnavailable) as err:
        analyze_market_data(replace(data, candles=complete), now=expected, analysis_mode="lo")
    assert err.value.code == "MISSING_RECENT_CANDLE"


async def test_smarty_falls_back_to_real_minute_and_blocks_expired_target(settings, monkeypatch):
    from datetime import datetime, timezone

    from engines.technical.analyzer import AnalysisResult
    from providers.catalog import Market
    from services import market_analysis as service

    now = datetime(2026, 11, 16, 15, 30, tzinfo=timezone.utc)
    requested = []

    async def one(self, asset, frame, semaphore):
        requested.append(frame)
        if frame != "1min":
            return None
        result = AnalysisResult(asset.key, asset.display, "smarty", frame, "UP", 0,
                                10, 0, 1, "test", now, target_open_at=now - timedelta(seconds=1))
        return result, frame

    monkeypatch.setattr(service, "utc_now", lambda: now)
    monkeypatch.setattr(service.MarketAnalysisService, "_one", one)
    outcome = await service.MarketAnalysisService(None, settings, mode="lo").analyse(Market.SMARTY)
    assert requested == ["30sec", "1min", "15sec"]
    assert outcome.fetched == 1
    assert not outcome.actionable
    assert "غير كافٍ" in outcome.conflict
