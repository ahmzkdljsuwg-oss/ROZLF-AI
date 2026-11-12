"""SMARTY end-to-end wiring with a local bridge double.

The candles here are synthetic fixtures: this proves the SMARTY path (bridge
asset -> candles -> indicators -> signal/story) works, not that a live
ExpertOption account is connected.
"""
from __future__ import annotations

from bot import formatting as fmt
from engines.signals.generator import SignalGenerator
from providers.base import DataUnavailable
from providers.catalog import SMARTY_ASSET, Market
from providers.inventory import MarketInventory
from providers.registry import DataSourceRegistry
from tests.conftest import FakeProvider, make_candles

SMARTY_ROW = {"id": 240, "symbol": "SMRTY", "name": "SMARTY", "market": "smarty", "precision": 2}


class SmartyBridge(FakeProvider):
    id = "eo_bridge"
    name = "ExpertOption Bridge"
    markets = frozenset({Market.SMARTY})
    quote_price = None

    def __init__(self, error: DataUnavailable | None = None) -> None:
        super().__init__(candles=make_candles(200, tf_seconds=60, start=1000.0, drift=0.02, noise=0.05))
        self.error = error

    async def fetch_assets(self, market: Market):
        if self.error is not None:
            raise self.error
        return [dict(SMARTY_ROW)] if market is Market.SMARTY else []

    async def smarty(self):
        if self.error is not None:
            raise self.error
        return {"asset_id": 240, "asset": dict(SMARTY_ROW)}


async def test_smarty_asset_comes_from_bridge():
    inventory = MarketInventory(SmartyBridge())
    assets = await inventory.assets(Market.SMARTY)
    assert [asset.symbol for asset in assets] == ["SMRTY"]
    assert assets[0].bridge_id == 240
    assert assets[0].market is Market.SMARTY


async def test_smarty_unavailable_surfaces_real_reason():
    inventory = MarketInventory(SmartyBridge(error=DataUnavailable("TOKEN_INVALID", "token expired")))
    try:
        await inventory.assets(Market.SMARTY, force=True)
    except DataUnavailable as exc:
        assert exc.code == "TOKEN_INVALID"
        assert "SMARTY UNAVAILABLE" in exc.message
        assert "token expired" in exc.message
    else:  # pragma: no cover - the call must fail
        raise AssertionError("SMARTY must not be served without verified data")


async def test_smarty_analysis_and_message(settings, repo):
    bridge = SmartyBridge()
    registry = DataSourceRegistry([bridge])
    generator = SignalGenerator(registry, repo, settings)
    result, record = await generator.generate(42, SMARTY_ASSET, "1min", duration_seconds=60, min_confidence=0.0)

    assert result.market == "smarty"
    assert result.source == "ExpertOption Bridge"
    assert result.direction in {"UP", "DOWN", "NO TRADE"}
    assert result.indicators["rsi"] is not None
    assert result.indicators["macd_hist"] is not None

    text = fmt.smarty_result_text(result, record)
    assert "SMARTY ANALYSIS" in text
    assert "RSI:" in text
    assert "MACD HIST:" in text
    if record is None:
        assert "NO TRADE" in text
        assert "SUGGESTED DURATION" in text
    else:
        assert record.expiry_seconds == 60
        assert "TRADE DURATION: 1 MIN" in text
        assert "SIGNAL ID" in text
