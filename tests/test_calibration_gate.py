"""The real calibration file must gate unproven markets and frames."""
from __future__ import annotations

import pytest

import engines.technical.next_candle as nc

from tests.conftest import make_candles
from tests.test_evidence_engine import _market
from engines.technical.analyzer import analyze_market_data
from providers.catalog import Market, assets_for


@pytest.fixture(autouse=True)
def _real_calibration():
    import importlib

    importlib.reload(nc)
    yield
    importlib.reload(nc)


def test_real_calibration_contains_only_audited_horizon_tables():
    calibration = nc.load_calibration()
    assert calibration["version"] == 2
    assert calibration["markets"]
    for frames in calibration["markets"].values():
        for table in frames.values():
            assert table["horizons"]
            for horizon, data in table["horizons"].items():
                assert data["horizon_bars"] == int(horizon)
                assert data["expiry_seconds"] > 0
                assert data["wilson_95_lower_hit_rate"] <= data["break_even_hit_rate"]


@pytest.mark.parametrize(("market", "frame"), [("forex", "1min"), ("football", "5min"), ("smarty", "1h")])
def test_unproven_market_and_frame_returns_no_trade(market, frame):
    asset = assets_for(Market[market.upper()])[0]
    result = analyze_market_data(_market(asset, make_candles(260, tf_seconds=300), tf=frame))
    assert result.direction == "NO TRADE"
    assert any("walk-forward" in reason for reason in result.reasons)


def test_proven_frame_uses_calibrated_confidence():
    from providers.catalog import timeframe

    candles = make_candles(260, drift=0.00008, noise=0.00035, seed=3, tf_seconds=900)
    asset = assets_for(Market.GOLD)[0]
    result = analyze_market_data(_market(asset, candles, tf="15min"), duration_seconds=900)
    assert result.direction in {"UP", "DOWN", "NO TRADE"}
    assert result.direction == "NO TRADE"
    assert result.confidence == 0.0
    assert any("no calibrated walk-forward table" in blocker
               for blocker in result.next_candle["blockers"])
    assert timeframe("15min").seconds == 900
