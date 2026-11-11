"""Shared fixtures: synthetic candles, fake provider, temp database."""
from __future__ import annotations

import random
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from config import settings as base_settings
from database.repository import Repository
from providers.base import BaseProvider, Candle, DataUnavailable, Quote, utc_now
from providers.catalog import Asset, Market, Timeframe, dynamic_asset, find_by_symbol, timeframe


def make_candles(
    n: int = 200,
    *,
    start: float = 1.1000,
    drift: float = 0.00004,
    noise: float = 0.00002,
    tf_seconds: int = 300,
    end: datetime | None = None,
    seed: int = 7,
) -> list[Candle]:
    rng = random.Random(seed)
    end = end or utc_now() - timedelta(seconds=tf_seconds)
    times = [end - timedelta(seconds=tf_seconds * (n - 1 - i)) for i in range(n)]
    candles: list[Candle] = []
    price = start
    for index, stamp in enumerate(times):
        open_price = price
        close = open_price + drift + rng.uniform(-noise, noise)
        high = max(open_price, close) + abs(rng.uniform(0, noise))
        low = min(open_price, close) - abs(rng.uniform(0, noise))
        candles.append(Candle(time=stamp, open=open_price, high=high, low=low, close=close, volume=100 + index))
        price = close
    return candles


class FakeProvider(BaseProvider):
    id = "fake"
    name = "Fake Feed"
    markets = frozenset({Market.FOREX, Market.GOLD})

    def __init__(self, candles: list[Candle] | None = None, quote_price: float | None = None) -> None:
        self.candles = candles or make_candles()
        self.quote_price = quote_price
        self.fail = False

    async def fetch_candles(self, asset: Asset, timeframe: Timeframe, limit: int = 300) -> list[Candle]:
        if self.fail:
            raise DataUnavailable("NETWORK", "fake provider failure")
        return list(self.candles[-limit:])

    async def fetch_quote(self, asset: Asset) -> Quote:
        if self.quote_price is None:
            raise DataUnavailable("QUOTE_UNAVAILABLE", "no fake quote")
        price = self.quote_price
        return Quote(symbol=asset.symbol, bid=price - 0.00005, ask=price + 0.00005, time=utc_now(), source=self.name)


@pytest.fixture
def settings(tmp_path):
    return replace(
        base_settings,
        telegram_bot_token="123456:TESTTOKEN",
        telegram_chat_id=42,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        mistral_api_key=None,
        eo_bridge_url=None,
        eo_bridge_key=None,
        min_confidence=60.0,
        scanner_enabled=False,
    )


@pytest_asyncio.fixture
async def repo(settings):
    repository = Repository(settings)
    await repository.init()
    yield repository
    await repository.close()


@pytest.fixture
def eurusd() -> Asset:
    return find_by_symbol("EUR/USD", Market.FOREX)


@pytest.fixture
def btc_otc() -> Asset:
    return dynamic_asset("BTCUSD_OTC", Market.OTC, precision=2, bridge_id=999)
