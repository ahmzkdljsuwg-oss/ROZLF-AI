"""Live-network checks (skipped unless ROZLF_NETWORK_TESTS=1).

These hit Yahoo Finance's public FX endpoint, so they prove real candles are
reachable from this machine. They are not run in the default suite.
"""
from __future__ import annotations

import os

import pytest

from providers.base import DataUnavailable
from providers.catalog import Market, assets_for, get_asset
from providers.yahoo import YahooForexProvider

pytestmark = pytest.mark.skipif(
    os.environ.get("ROZLF_NETWORK_TESTS") != "1", reason="set ROZLF_NETWORK_TESTS=1 to allow network checks"
)


async def test_yahoo_serves_real_forex_candles():
    provider = YahooForexProvider()
    asset = get_asset("EUR_USD_FOREX")
    candles = await provider.fetch_candles(asset, __import__("providers.catalog", fromlist=["timeframe"]).timeframe("5min"))
    await provider.close()
    assert len(candles) >= 100
    assert candles[-1].close > 0


async def test_yahoo_refuses_otc():
    provider = YahooForexProvider()
    with pytest.raises(DataUnavailable):
        from providers.catalog import dynamic_asset

        await provider.fetch_candles(
            dynamic_asset("EURUSD_OTC", Market.OTC, precision=5, bridge_id=179), "5min"
        )
    await provider.close()


async def test_every_forex_pair_has_a_candle_source():
    from providers.base import DataUnavailable as Unavailable
    from providers.registry import build_registry
    from config import settings

    registry = build_registry(settings)
    for asset in assets_for(Market.FOREX):
        data = await registry.fetch(asset, "5min", limit=200)
        assert len(data.candles) > 60, asset.symbol
