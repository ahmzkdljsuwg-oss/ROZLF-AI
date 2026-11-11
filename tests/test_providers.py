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


async def test_missing_bars_rejected(eurusd):
    registry = DataSourceRegistry([FakeProvider(candles=make_candles(12))])
    with pytest.raises(DataUnavailable):
        await registry.fetch(eurusd, timeframe("15min"))
