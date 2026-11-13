"""Williams Alligator + EMA 200 strategy: settings, gates and formatting."""
from __future__ import annotations

import pandas as pd
import pytest

from bot.formatting import analysis_details_text, unified_result_text
from engines.strategies.alligator_ma import (
    JAW, JAW_SHIFT, LIPS, LIPS_SHIFT, MA_PERIOD, TEETH, TEETH_SHIFT, TICK_SECONDS,
    AlligatorSignalGate, assess_alligator_ma,
)
from engines.technical.analyzer import analyze_market_data
from engines.validation import validate_candles
from providers.base import MarketData, utc_now
from providers.catalog import find_by_symbol, timeframe

from tests.conftest import make_candles

TF = timeframe("1min")
ASSET = find_by_symbol("EUR/USD")


def trend_candles(direction: str, n: int = 260):
    drift = 0.00008 if direction == "UP" else -0.00008
    return make_candles(n, drift=drift, noise=0.00001, tf_seconds=60), utc_now()


def market_data(candles) -> MarketData:
    return MarketData(
        asset=ASSET,
        timeframe=TF,
        candles=candles,
        source="test",
        quote=None,
        validation=validate_candles(candles, TF, min_bars=60),
    )


def frame(direction: str = "UP", n: int = 260, seed: int = 3) -> pd.DataFrame:
    rng = __import__("numpy").random.default_rng(seed)
    rows = []
    price = 1.1000
    for i in range(n):
        drift = (0.00006 if direction == "UP" else -0.00006) * i
        close = price + drift + 0.0003 * __import__("math").sin(i / 7) + rng.normal(0, 0.00005)
        open_price = close - (0.00010 if direction == "UP" else -0.00010)
        high = max(open_price, close) + 0.00008
        low = min(open_price, close) - 0.00008
        rows.append((open_price, high, low, close, 1))
    index = pd.date_range("2026-01-01", periods=n, freq="min", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"], index=index)


def test_standard_alligator_settings_are_used():
    assert (JAW, JAW_SHIFT) == (13, 8)
    assert (TEETH, TEETH_SHIFT) == (8, 5)
    assert (LIPS, LIPS_SHIFT) == (5, 3)
    assert MA_PERIOD == 200
    assert TICK_SECONDS == 5


def test_bullish_alligator_and_ema200_produce_buy():
    result = assess_alligator_ma(frame("UP"), asset_key="EUR/USD", timeframe="1min")
    assert result.decision == "BUY"
    assert result.ma_type == "EMA 200"
    assert result.ma_direction == "UP"
    assert result.alligator_state == "AWAKE"
    assert result.alligator_direction == "BULLISH"
    assert result.trend_strength in ("MODERATE", "STRONG")
    assert result.price is not None and result.price_time is not None
    assert result.reasons and not result.blockers
    assert result.invalidation


def test_bearish_alligator_and_ema200_produce_sell():
    result = assess_alligator_ma(frame("DOWN"), asset_key="EUR/USD", timeframe="1min")
    assert result.decision == "SELL"
    assert result.ma_direction == "DOWN"
    assert result.alligator_state == "AWAKE"
    assert result.alligator_direction == "BEARISH"
    assert result.reasons and not result.blockers


def test_insufficient_candles_block_signal():
    result = assess_alligator_ma(frame("UP", n=199))
    assert result.decision == "NO TRADE"
    assert result.bars == 199
    assert "needs 200" in result.blockers[0]


def test_flat_market_puts_alligator_to_sleep():
    index = pd.date_range("2026-01-01", periods=260, freq="min", tz="UTC")
    flat = pd.DataFrame(
        [(1.1000, 1.1000, 1.1000, 1.1000, 1)] * 260,
        columns=["open", "high", "low", "close", "volume"], index=index,
    )
    result = assess_alligator_ma(flat)
    assert result.decision == "NO TRADE"
    assert result.alligator_state == "SLEEPING"
    assert result.blockers


def test_last_closed_candle_must_confirm_direction():
    data = frame("UP")
    data.loc[data.index[-1], ["open", "high", "low", "close"]] = [1.1200, 1.1201, 1.1170, 1.1172]
    result = assess_alligator_ma(data)
    assert result.decision == "NO TRADE"
    assert any("confirmation candle" in item or "engulfing" in item for item in result.blockers)


def test_signal_gate_suppresses_identical_refreshes():
    gate = AlligatorSignalGate()
    first = assess_alligator_ma(frame("UP"), asset_key="EUR/USD", timeframe="1min")
    assert first.decision == "BUY"
    assert gate.should_emit("EUR/USD", first) is True
    assert gate.should_emit("EUR/USD", first) is False
    fresh = frame("UP", seed=3)
    fresh.index = fresh.index + pd.Timedelta(minutes=1)
    assert gate.should_emit("EUR/USD", assess_alligator_ma(fresh, asset_key="EUR/USD", timeframe="1min")) is True


def test_analyzer_exposes_alligator_block_for_both_cases():
    for direction in ("UP", "DOWN"):
        candles, now = trend_candles(direction)
        result = analyze_market_data(market_data(candles), now=now, duration_seconds=60)
        block = result.alligator_ma
        assert block["ma_type"] == "EMA 200"
        assert block["ma_direction"] in ("UP", "DOWN")
        assert block["alligator_state"] in ("AWAKE", "SLEEPING")
        assert block["price"] is not None
        assert block["price_time"] is not None
        text = unified_result_text(result, 60, "1min", None)
        assert "ALLIGATOR + MA 200" in text
        details = analysis_details_text(result)
        assert "ALLIGATOR + MA 200" in details
