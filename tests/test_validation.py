from datetime import timedelta

from engines.validation import validate_candles
from providers.base import Candle, utc_now
from providers.catalog import timeframe

from tests.conftest import make_candles


def test_valid_series_passes():
    candles = make_candles(150)
    report = validate_candles(candles, timeframe("5min"))
    assert report.ok and not report.stale
    assert report.bar_count == 150
    assert report.is_tradeable


def test_duplicates_and_order_are_rejected():
    candles = make_candles(150)
    broken = [candles[5]] + candles
    report = validate_candles(broken, timeframe("5min"))
    assert not report.ok
    assert any("duplicate" in issue for issue in report.issues)


def test_ohlc_sanity_is_enforced():
    candles = make_candles(80)
    candles[10] = Candle(
        time=candles[10].time, open=1.1, high=1.0, low=0.9, close=1.2
    )
    report = validate_candles(candles, timeframe("5min"))
    assert not report.ok
    assert any("OHLC" in issue or "high" in issue for issue in report.issues)


def test_stale_series_is_flagged():
    old_end = utc_now() - timedelta(hours=3)
    candles = make_candles(150, end=old_end)
    report = validate_candles(candles, timeframe("5min"))
    assert report.stale
    assert not report.is_tradeable


def test_too_few_bars_is_rejected():
    report = validate_candles(make_candles(10), timeframe("5min"))
    assert not report.ok
