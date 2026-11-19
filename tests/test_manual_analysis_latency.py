import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from engines.technical import analyzer, next_candle
from engines.technical.analyzer import AnalysisResult
from engines.technical.indicators import find_swings
from providers.base import MarketData, ValidationReport
from providers.catalog import Market, assets_for, timeframe
from providers.registry import DataSourceRegistry
from services import market_analysis as manual
from tests.conftest import FakeProvider, make_candles
from tests.test_nexus_telegram import FakeCallback


NOW = datetime(2026, 11, 19, 12, 0, 2, tzinfo=timezone.utc)


def bars_for(seconds, count=250):
    return make_candles(count, tf_seconds=seconds, end=NOW - timedelta(seconds=seconds + 2))


def test_swings_match_reference_for_ties_short_windows_and_boundaries():
    rng = np.random.default_rng(15)
    lows = 1 + rng.integers(0, 20, 300)
    highs = lows + rng.integers(0, 20, 300)
    frame = pd.DataFrame(dict(high=highs, low=lows))
    for w in (1, 3, 10, 149, 150):
        expected = []
        for i in range(w, len(frame) - w):
            if highs[i] >= max(highs[i-w:i]) and highs[i] >= max(highs[i+1:i+w+1]):
                expected.append(dict(index=i, price=float(highs[i]), kind="high"))
            if lows[i] <= min(lows[i-w:i]) and lows[i] <= min(lows[i+1:i+w+1]):
                expected.append(dict(index=i, price=float(lows[i]), kind="low"))
        assert find_swings(frame, w) == expected


def test_live_strong_does_not_apply_legacy_calibration_to_different_target(eurusd, monkeypatch):
    tf = timeframe("1min")
    bars = bars_for(tf.seconds)
    data = MarketData(eurusd, tf, bars, "test", None, ValidationReport(True, len(bars)), fetched_at=NOW)
    bucket = {"low": 0, "high": 999, "n": 200, "up_wins": 181}
    markets = {"forex": {"1min": {"enabled": True, "bins": [bucket]}}}
    monkeypatch.setattr(next_candle, "load_calibration", lambda: {"target_offset": 1, "markets": markets})
    blocked = analyzer.analyze_market_data(data, NOW, live_candle_target=True)
    assert blocked.direction == "NO TRADE" and not blocked.confidence_verified
    assert blocked.win_probability is None
    assert "معايرة مطابقة" in blocked.reasons[0]
    assert blocked.target_open_at == bars[-1].time + timedelta(minutes=2)
    monkeypatch.setattr(next_candle, "load_calibration", lambda: {"target_offset": 2, "markets": markets})
    verified = analyzer.analyze_market_data(data, NOW, live_candle_target=True)
    assert verified.direction == "UP" and verified.confidence_verified
    assert verified.target_open_at == blocked.target_open_at


async def test_cache_expires_when_next_bar_closes_even_without_forming_bar(eurusd):
    tick = NOW.replace(second=59)
    first_bars = bars_for(60)

    class Source(FakeProvider):
        calls = 0

        async def fetch_candles(self, asset, tf, limit=300):
            self.calls += 1
            return first_bars if self.calls == 1 else self.candles

    new = replace(first_bars[-1], time=first_bars[-1].time + timedelta(minutes=1))
    source = Source([*first_bars, new])
    reg = DataSourceRegistry([source], clock=lambda: tick, cache_ttl=30)
    tf = timeframe("1min")
    first = await reg.fetch(eurusd, tf, with_quote=False)
    assert first.candles[-1] == first_bars[-1]
    assert reg.cached_candles(eurusd, tf) is first
    tick += timedelta(seconds=1)
    assert reg.cached_candles(eurusd, tf) is None
    second = await reg.fetch(eurusd, tf, with_quote=False)
    assert second.candles[-1] == new and source.calls == 2


async def test_manual_strong_does_not_await_quote_and_anchors_target(eurusd, settings, monkeypatch):
    monkeypatch.setattr(manual, "utc_now", lambda: NOW)
    monkeypatch.setattr(analyzer, "utc_now", lambda: NOW)

    class Source(FakeProvider):
        async def fetch_candles(self, asset, tf, limit=300):
            return bars_for(tf.seconds)

        async def fetch_quote(self, asset):
            pytest.fail("Closed-candle analysis must not wait for a separate quote")

    result = await manual.MarketAnalysisService(DataSourceRegistry([Source()], clock=lambda: NOW), settings).analyse(
        Market.FOREX, eurusd.key)
    assert result.fetched > 0 and result.result.asset_key == eurusd.key


async def test_manual_inventory_cannot_redirect_to_another_market(eurusd, settings):
    class WrongInventory:
        async def assets(self, _market):
            return [eurusd]

    service = manual.MarketAnalysisService(None, settings, WrongInventory(), mode="lo")
    outcome = await service.analyse(Market.SMARTY, eurusd.key)
    assert outcome.result is None and outcome.attempted == 0


async def test_deep_budget_preserves_a_finished_result_and_cancels_waiter(settings, monkeypatch, eurusd):
    monkeypatch.setattr(manual, "DEEP_BUDGET", .12)
    monkeypatch.setattr(manual, "utc_now", lambda: NOW)
    monkeypatch.setattr(manual, "forecast_frames", lambda _market, _frames: ("1min", "5min"))
    stopped = asyncio.Event()

    async def one(_self, asset, frame, _sem):
        if frame == "5min":
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        return AnalysisResult(asset.key, asset.display, "forex", frame, "NO TRADE", 0, 0, 0,
                              1, "test", NOW), frame

    monkeypatch.setattr(manual.MarketAnalysisService, "_one", one)
    out = await asyncio.wait_for(manual.MarketAnalysisService(None, settings).analyse(Market.FOREX, eurusd.key), 1.0)
    assert stopped.is_set() and out.fetched == 1 and out.result.timeframe == "1min"


async def test_unrelated_asset_does_not_veto_calibrated_signal(settings, monkeypatch):
    monkeypatch.setattr(manual, "utc_now", lambda: NOW)
    monkeypatch.setattr(manual, "forecast_frames", lambda _market, _frames: ("1min",))
    first, second = assets_for(Market.FOREX)[:2]

    class Service(manual.MarketAnalysisService):
        async def assets_for(self, _market, _key):
            return [first, second]

        async def _one(self, asset, frame, _sem):
            direction = "UP" if asset is first else "DOWN"
            result = AnalysisResult(asset.key, asset.display, asset.market.value, frame, direction,
                                    80 if asset is first else 78, 0, 0, 1, "test", NOW,
                                    target_open_at=NOW + timedelta(seconds=30))
            return result, frame

    service = Service(None, settings)
    service.reviewer = SimpleNamespace(configured=lambda: False)
    out = await service.analyse(Market.FOREX)
    assert out.actionable and out.result.asset_key == first.key


async def test_lo_skips_a_blocked_frame_then_uses_the_same_assets_other_frame(settings, monkeypatch):
    monkeypatch.setattr(manual, "LO_FRAME_BUDGET", .06)
    monkeypatch.setattr(manual, "LO_BUDGET", .40)
    monkeypatch.setattr(manual, "utc_now", lambda: NOW)
    stopped = asyncio.Event()
    requested = []

    async def one(_self, asset, frame, _sem):
        requested.append((asset.key, frame))
        if frame == "30sec":
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        return AnalysisResult(asset.key, asset.display, "smarty", frame, "NO TRADE", 0, 0, 0,
                              1, "test", NOW, target_open_at=NOW + timedelta(seconds=30)), frame

    monkeypatch.setattr(manual.MarketAnalysisService, "_one", one)
    out = await manual.MarketAnalysisService(None, settings, mode="lo").analyse(Market.SMARTY)
    assert stopped.is_set() and out.result.timeframe == "1min"
    assert [frame for _, frame in requested] == ["30sec", "1min"]
    assert len({key for key, _ in requested}) == 1


async def test_button_double_tap_cannot_queue_a_second_analysis(settings, monkeypatch):
    from bot.handlers import menus

    waiting = asyncio.Event()
    ready = asyncio.Event()
    calls = []

    class First(FakeCallback):
        async def answer(self, *args, **kwargs):
            waiting.set()
            await ready.wait()

    class Service:
        def __init__(self, *_args, **_kwargs):
            pass

        async def analyse(self, market, asset_key=None):
            calls.append(market)
            return manual.MarketAnalysis(market)

    monkeypatch.setattr(menus, "get_context", lambda: SimpleNamespace(registry=None, settings=settings))
    monkeypatch.setattr(menus, "MarketAnalysisService", Service)
    first = asyncio.create_task(menus._nexus_analyse(First("nx:classic:smarty", 99217), "SMARTY"))
    try:
        await asyncio.wait_for(waiting.wait(), 1.0)
        second = FakeCallback("nx:classic:smarty", 99217)
        await asyncio.wait_for(menus._nexus_analyse(second, "SMARTY"), 1.0)
        assert second.answered == ["التحليل السابق لم ينتهِ بعد"] and second.message.edits == []
    finally:
        ready.set()
        await first
    assert calls == [Market.SMARTY]
