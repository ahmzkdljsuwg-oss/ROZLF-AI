from __future__ import annotations

import time

import pytest

from rozlf.engines.signals.generator import RiskPolicy, persist_signal
from rozlf.engines.signals.tracker import SignalTracker
from rozlf.providers.base import Candle, Quote, ProviderStatus
from conftest import make_candles
from test_signals import draft


class QuoteProvider:
    name = "fake"
    title = "Fake"
    can_serve_candles = True

    def __init__(self, price: float, when: int | None = None):
        self.price = price
        self.when = when or int(time.time())

    async def quote(self, asset):
        return Quote(symbol=asset.symbol, price=self.price, time=self.when, source="fake")

    async def candles(self, asset, timeframe, limit=200):
        return make_candles(limit, start=self.price, timeframe=timeframe)


class FakeRegistry:
    def __init__(self, provider):
        self.provider = provider

    def asset(self, symbol):
        from rozlf.providers.base import Asset

        return Asset(symbol=symbol, name=symbol, market="FOREX", provider="fake")

    def provider_for(self, asset):
        return self.provider

    async def quote(self, asset):
        return await self.provider.quote(asset)

    async def candles(self, asset, timeframe, limit=200):
        from rozlf.engines.validation import validate_candles

        data = await self.provider.candles(asset, timeframe, limit)
        return data, validate_candles(data, timeframe)


async def _open_signal(repo, direction="UP", entry=1.1000):
    now = int(time.time())
    return await repo.add(
        symbol="EURUSD",
        market="FOREX",
        direction=direction,
        timeframe=300,
        expiry_seconds=300,
        entry=entry,
        stop=None,
        target=None,
        score=90,
        source="test",
        reasons="test",
        warnings="",
        ai_note="",
        status="OPEN",
        created_at=now - 600,
        expires_at=now - 5,
    )


async def test_win_when_price_moves_up(repo):
    row = await _open_signal(repo, "UP", 1.1000)
    tracker = SignalTracker(repo, FakeRegistry(QuoteProvider(1.1050)))
    resolved = await tracker.resolve_due()
    assert resolved, "expected the due signal to be resolved"
    row = await repo.get(row.id)
    assert row.result == "WIN"
    assert row.exit_price == pytest.approx(1.1050)


async def test_loss_when_price_moves_against(repo):
    row = await _open_signal(repo, "DOWN", 1.1000)
    tracker = SignalTracker(repo, FakeRegistry(QuoteProvider(1.1060)))
    await tracker.resolve_due()
    row = await repo.get(row.id)
    assert row.result == "LOSS"


async def test_unverified_when_quote_is_stale(repo):
    row = await _open_signal(repo, "UP", 1.1000)
    tracker = SignalTracker(repo, FakeRegistry(QuoteProvider(1.1050, when=int(time.time()) - 3600)))
    await tracker.resolve_due()
    row = await repo.get(row.id)
    assert row.status in ("OPEN", "UNVERIFIED")
