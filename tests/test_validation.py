from __future__ import annotations

import time

from rozlf.engines.validation import validate_candles
from rozlf.providers.base import Candle

from conftest import make_candles


def test_empty_is_unusable():
    report = validate_candles([], 300)
    assert not report.ok
    assert report.code == "EMPTY"
    assert report.quality == "unusable"


def test_real_series_is_good(candles):
    report = validate_candles(candles, 300)
    assert report.ok, report.detail
    assert report.quality == "good"
    assert report.count == len(candles)


def test_too_few_candles_rejected():
    report = validate_candles(make_candles(20), 300)
    assert not report.ok
    assert report.code == "TOO_FEW"


def test_bad_ohlc_rejected():
    now = int(time.time())
    bad = [Candle(now - i * 300, 1.0, 0.5, 1.2, 1.0, 10) for i in range(5, 0, -1)]
    bad += make_candles(80)
    report = validate_candles(bad, 300)
    assert not report.ok
    assert report.code == "BAD_OHLC"


def test_stale_data_flagged(candles):
    old = [Candle(c.time - 86400, c.open, c.high, c.low, c.close, c.volume) for c in candles]
    report = validate_candles(old, 300)
    assert not report.ok
    assert report.code == "STALE"


def test_gaps_only_degrade(candles):
    holed = candles[:100] + candles[130:]
    report = validate_candles(holed, 300)
    assert report.gaps > 0
    assert report.quality in ("degraded", "good")
