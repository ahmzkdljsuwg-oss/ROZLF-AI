"""Task K: evidence engine, closed-bar rule and premium card."""
from datetime import timedelta

import pytest

from bot.formatting import unified_result_text
from database.repository import STATUS_WIN, Repository
from engines.technical.analyzer import analyze_market_data
from engines.validation import closed_candles
from providers.base import Candle, DataUnavailable, MarketData, Quote, ValidationReport, utc_now
from providers.catalog import timeframe

from tests.conftest import make_candles


def _market(asset, candles, tf="5min", quote=None):
    frame = timeframe(tf)
    return MarketData(
        asset=asset,
        timeframe=frame,
        candles=candles,
        source="real-test-feed",
        quote=quote or Quote(asset.symbol, candles[-1].close, candles[-1].close, candles[-1].time, "real-test-feed"),
        validation=ValidationReport(ok=True, bar_count=len(candles), last_candle_time=candles[-1].time),
    )


def test_closed_candles_drop_bar_that_is_still_forming():
    now = utc_now()
    tf = timeframe("1min")
    closed = Candle(now - timedelta(seconds=120), 1.0, 1.1, 0.9, 1.05, 1)
    forming = Candle(now - timedelta(seconds=30), 1.0, 5.0, 0.5, 4.0, 1)
    assert closed_candles([closed, forming], tf, now) == [closed]


def test_analyzer_never_reads_the_forming_bar(eurusd):
    candles = make_candles(200, end=utc_now() - timedelta(seconds=300))
    forming = Candle(
        time=utc_now(),
        open=candles[-1].close,
        high=candles[-1].close + 9,
        low=candles[-1].close - 9,
        close=candles[-1].close + 8,
        volume=1,
    )
    result = analyze_market_data(_market(eurusd, candles + [forming]))
    assert result.indicators["last_candle_at"] == candles[-1].time.isoformat()
    assert forming.time.isoformat() != result.indicators["last_candle_at"]


def test_too_few_closed_candles_is_rejected(eurusd):
    candles = make_candles(40, end=utc_now() - timedelta(seconds=300))
    with pytest.raises(DataUnavailable) as error:
        analyze_market_data(_market(eurusd, candles))
    assert error.value.code == "INSUFFICIENT_BARS"


def test_confidence_is_evidence_based_and_not_constant(eurusd):
    trending = analyze_market_data(_market(eurusd, make_candles(220, noise=0.0001, seed=23)))
    choppy = analyze_market_data(_market(eurusd, make_candles(220, drift=0.0, noise=0.0004, seed=3)))
    assert trending.confidence_components
    assert trending.confidence != 80.0 or trending.confidence != choppy.confidence
    assert trending.confidence != choppy.confidence
    assert "data" in trending.confidence_components
    assert trending.data_quality_score >= 6


def test_weak_market_can_return_no_trade(eurusd):
    result = analyze_market_data(
        _market(eurusd, make_candles(220, drift=0.0, noise=0.0004, seed=11))
    )
    assert result.direction in {"UP", "DOWN", "NO TRADE"}
    if result.direction == "NO TRADE":
        assert result.blockers


def test_premium_card_shows_trade_time_before_confidence(eurusd):
    result = analyze_market_data(_market(eurusd, make_candles(220, noise=0.0001, seed=23)))
    text = unified_result_text(result, 30, "5min")
    assert text.startswith("📊 السوق: <b>FOREX</b>")
    assert "⚪ الإشارة: <b>لا توجد فرصة تداول</b>" in text

    from bot import formatting as fmt

    card = fmt.signal_card_text("forex", "EUR/USD", "UP", 30, 72.0)
    assert card.index("مدة الصفقة") < card.index("قوة الإشارة")
    assert "🟢 الإشارة: <b>شراء</b>" in card


async def test_settlement_reason_is_persisted(repo: Repository):
    from services.signal_tracker import SignalTracker

    record = await repo.add_signal(
        7,
        "EUR_USD_FOREX",
        "EUR/USD (FOREX)",
        "forex",
        "5min",
        "UP",
        70.0,
        1.1000,
        "real-test-feed",
        ["Bullish market structure"],
        [],
        60,
        utc_now(),
    )
    reason = SignalTracker._result_reason(record, STATUS_WIN, 1.1005)
    await repo.finish_signal(record.id, STATUS_WIN, 1.1005, utc_now(), "real-test-feed", reason)
    closed = (await repo.recent_signals(1))[0]
    assert closed.status == STATUS_WIN
    assert closed.result_reason and "Bullish market structure" in closed.result_reason
