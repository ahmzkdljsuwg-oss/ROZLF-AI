"""Five-minute trend mode: deterministic fixtures, vetoes and fixed expiry."""
from __future__ import annotations

import math
import random
from datetime import timedelta

from engines.signals.generator import SignalGenerator
from engines.technical.analyzer import analyze_market_data
from engines.technical.trend5m import MODE_SECONDS
from providers.base import Candle, MarketData, Quote, ValidationReport, utc_now
from providers.catalog import Market, find_by_symbol, timeframe
from providers.registry import DataSourceRegistry

from tests.conftest import FakeProvider


def trend_candles(direction: str = "UP", *, flat: int = 210, run: int = 50, seed: int = 9):
    rng = random.Random(seed)
    tf = 60
    n = flat + run
    now = utc_now().replace(microsecond=0)
    close_time = now - timedelta(seconds=tf)
    times = [close_time - timedelta(seconds=tf * (n - 1 - i)) for i in range(n)]
    slope = 0.000008 if direction == "UP" else -0.000008
    price = 1.0800
    rows = []
    for index, stamp in enumerate(times):
        open_price = price
        if index < flat:
            close = open_price + rng.uniform(-1e-5, 1e-5)
        else:
            k = index - flat
            step = slope if (k % 7) < 5 else -slope * 0.6
            close = open_price + step + 1e-5 * math.sin(k * 0.9) + rng.uniform(-1e-5, 1e-5)
        high = max(open_price, close) + abs(rng.uniform(0, 7e-6))
        low = min(open_price, close) - abs(rng.uniform(0, 7e-6))
        rows.append([stamp, open_price, high, low, close])
        price = close
    stamp, open_price, high, low, close = rows[-1]
    body = 0.00012 if direction == "UP" else -0.00012
    open_price = rows[-2][4]
    close = open_price + body
    rows[-1] = [stamp, open_price, close + 2e-5, open_price - 1e-5, close]
    candles = [
        Candle(time=stamp, open=o, high=h, low=l, close=c, volume=100 + i)
        for i, (stamp, o, h, l, c) in enumerate(rows)
    ]
    return candles, now


def market_data(candles):
    asset = find_by_symbol("EUR/USD", Market.FOREX)
    return MarketData(
        asset=asset,
        timeframe=timeframe("1min"),
        candles=candles,
        source="synthetic-test",
        quote=Quote("EUR/USD", candles[-1].close, candles[-1].close, candles[-1].time, "synthetic-test"),
        validation=ValidationReport(ok=True, bar_count=len(candles), last_candle_time=candles[-1].time),
    )


def test_trend_mode_confirms_aligned_five_minute_setup():
    candles, now = trend_candles("UP")
    result = analyze_market_data(market_data(candles), now=now, duration_seconds=MODE_SECONDS)
    assert result.analysis_mode == "5M TREND"
    assert result.trade_duration_seconds == MODE_SECONDS
    assert result.direction == "UP"
    assert result.five_min["trend"] == "UP"
    assert result.five_min["checks"]["ema_aligned"] is True
    assert result.five_min["checks"]["structure_supports"] is True
    assert result.five_min["checks"]["candle_confirmed"] is True
    assert result.five_min["blockers"] == []
    assert result.expiry_at - result.entry_at == timedelta(seconds=MODE_SECONDS)
    assert result.signal_at is not None and result.signal_at <= now


def test_trend_mode_refuses_stale_closed_candle():
    candles, now = trend_candles("UP")
    late = now + timedelta(minutes=2)
    result = analyze_market_data(market_data(candles), now=late, duration_seconds=MODE_SECONDS)
    assert result.direction == "NO TRADE"
    assert any("stale" in blocker for blocker in result.five_min["blockers"])


def test_trend_mode_refuses_flat_chop():
    candles, now = trend_candles("UP", flat=260, run=0)
    result = analyze_market_data(market_data(candles), now=now, duration_seconds=MODE_SECONDS)
    assert result.direction == "NO TRADE"
    assert result.five_min["entry_ok"] is False
    assert result.five_min["blockers"]


def test_trend_mode_never_changes_duration():
    candles, now = trend_candles("UP")
    standard = analyze_market_data(market_data(candles), now=now, duration_seconds=60)
    assert standard.analysis_mode == "STANDARD"
    assert standard.trade_duration_seconds is None
    assert standard.five_min == {}


async def test_five_minute_signal_uses_fixed_expiry(settings, repo, eurusd):
    candles, _ = trend_candles("UP")
    registry = DataSourceRegistry([FakeProvider(candles, quote_price=candles[-1].close)])
    generator = SignalGenerator(registry, repo, settings)
    result, record = await generator.generate(
        42, eurusd, "1min", duration_seconds=MODE_SECONDS, min_confidence=0.0
    )
    assert result.analysis_mode == "5M TREND"
    assert record is not None
    assert record.expiry_seconds == MODE_SECONDS
    assert record.entry_at is not None
    assert record.expires_at - record.entry_at == timedelta(seconds=MODE_SECONDS)


async def test_five_minute_signal_is_blocked_by_vetoed_setup(settings, repo, eurusd):
    candles, now = trend_candles("UP")
    stale = [c for c in candles[:-1]]
    registry = DataSourceRegistry([FakeProvider(stale, quote_price=stale[-1].close)])
    generator = SignalGenerator(registry, repo, settings)
    result, record = await generator.generate(
        42, eurusd, "1min", duration_seconds=MODE_SECONDS, min_confidence=0.0
    )
    assert result.analysis_mode == "5M TREND"
    assert result.five_min["entry_ok"] is False
    assert result.direction == "NO TRADE"
    assert record is None


def test_signal_text_reports_five_minute_mode_and_timing():
    from bot.formatting import unified_result_text

    candles, now = trend_candles("UP")
    result = analyze_market_data(market_data(candles), now=now, duration_seconds=MODE_SECONDS)
    text = unified_result_text(result, MODE_SECONDS, "1min", None)
    assert "5-MINUTE TREND MODE" in text
    assert "FIXED DURATION: 5 MIN" in text
    assert "ENTRY TIME" in text
    assert "EXPIRY" in text
