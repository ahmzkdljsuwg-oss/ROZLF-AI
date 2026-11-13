from datetime import timedelta

import pytest

from providers.base import DataUnavailable, utc_now
from providers.registry import DataSourceRegistry
from providers.catalog import Market, find_by_symbol, timeframe

from tests.conftest import FakeProvider, make_candles


async def test_forex_uses_registered_candles(eurusd):
    registry = DataSourceRegistry([FakeProvider(quote_price=1.1000)])
    data = await registry.fetch(eurusd, "5min")
    assert data.source == "Fake Feed"
    assert len(data.candles) == 300 or len(data.candles) > 60
    assert data.validation.is_tradeable
    assert data.quote is not None


async def test_otc_never_borrows_forex_data(btc_otc):
    registry = DataSourceRegistry([FakeProvider()])
    with pytest.raises(DataUnavailable) as excinfo:
        await registry.fetch(btc_otc, "1min")
    assert "DATA UNAVAILABLE" in excinfo.value.message
    assert "no verified source" in excinfo.value.message


async def test_stale_candles_are_refused(eurusd):
    stale = make_candles(200, end=utc_now() - timedelta(hours=5))
    registry = DataSourceRegistry([FakeProvider(candles=stale)])
    with pytest.raises(DataUnavailable) as excinfo:
        await registry.fetch(eurusd, "5min")
    assert "stale" in (excinfo.value.detail or "").lower() or "DATA UNAVAILABLE" in excinfo.value.message


async def test_provider_failure_falls_through(eurusd):
    broken = FakeProvider()
    broken.fail = True
    registry = DataSourceRegistry([broken, FakeProvider()])
    data = await registry.fetch(eurusd, "5min")
    assert data.source == "Fake Feed"


async def test_quote_falls_back(eurusd):
    registry = DataSourceRegistry([FakeProvider()])
    with pytest.raises(DataUnavailable):
        await registry.fetch_quote(eurusd)


async def test_source_summary_reports_none_for_unconfigured_market(btc_otc):
    registry = DataSourceRegistry([FakeProvider()])
    assert registry.source_summary(btc_otc) == "NONE"
    assert registry.source_summary(find_by_symbol("EUR/USD", Market.FOREX)) == "Fake Feed"


class CountingProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__(quote_price=1.1000)
        self.calls = 0

    async def fetch_candles(self, asset, timeframe, limit: int = 300):
        self.calls += 1
        return await super().fetch_candles(asset, timeframe, limit=limit)


async def test_repeated_fetch_is_served_from_short_cache(eurusd):
    provider = CountingProvider()
    registry = DataSourceRegistry([provider], cache_ttl=30.0)
    first = await registry.fetch(eurusd, "5min")
    second = await registry.fetch(eurusd, "5min")
    assert provider.calls == 1
    assert first.candles[-1].close == second.candles[-1].close


async def test_concurrent_fetch_is_coalesced(eurusd):
    import asyncio

    provider = CountingProvider()
    registry = DataSourceRegistry([provider], cache_ttl=30.0)
    results = await asyncio.gather(*(registry.fetch(eurusd, "5min") for _ in range(5)))
    assert provider.calls == 1
    assert all(result.source == "Fake Feed" for result in results)


async def test_zero_cache_still_refetches(eurusd):
    provider = CountingProvider()
    registry = DataSourceRegistry([provider], cache_ttl=0.0)
    await registry.fetch(eurusd, "5min")
    await registry.fetch(eurusd, "5min")
    assert provider.calls == 2


async def test_missing_bars_rejected(eurusd):
    registry = DataSourceRegistry([FakeProvider(candles=make_candles(12))])
    with pytest.raises(DataUnavailable):
        await registry.fetch(eurusd, timeframe("15min"))
