"""Per-market wiring: every market must reach its own real source.

All providers here are local test doubles; nothing in this file proves a live
ExpertOption or Twelve Data connection.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot import formatting as fmt
from bot.keyboards import menus as kb
from engines.signals.generator import SignalGenerator
from providers.base import DataUnavailable, utc_now
from providers.catalog import SMARTY_ASSET, Market, assets_for, get_asset
from providers.inventory import MarketInventory
from providers.registry import DataSourceRegistry
from services.health import MarketHealthService
from tests.conftest import FakeProvider


class FakeBridge(FakeProvider):
    """Test double for the ExpertOption bridge (no real connection)."""

    id = "eo_bridge"
    name = "ExpertOption Bridge"
    markets = frozenset({Market.OTC, Market.SMARTY})

    def __init__(self, rows=None, error: DataUnavailable | None = None) -> None:
        from tests.conftest import make_candles

        super().__init__(candles=make_candles(200, tf_seconds=60))
        self.rows = rows or []
        self.error = error
        self.calls: list[Market] = []

    async def fetch_assets(self, market: Market):
        self.calls.append(market)
        if self.error is not None:
            raise self.error
        return [row for row in self.rows if row["market"] == market.value]


OTC_ROWS = [
    {"id": 179, "symbol": "EURUSD_OTC", "name": "EUR/USD OTC", "market": "otc", "precision": 5},
    {"id": 185, "symbol": "AUDUSD_OTC", "name": "AUD/USD OTC", "market": "otc", "precision": 5},
]
SMARTY_ROWS = [
    {"id": 240, "symbol": "SMRTY", "name": "SMARTY", "market": "smarty", "precision": 2},
]


async def test_inventory_lists_only_bridge_otc_assets():
    bridge = FakeBridge(OTC_ROWS)
    inventory = MarketInventory(bridge)
    assets = await inventory.assets(Market.OTC)
    assert [asset.symbol for asset in assets] == ["EURUSD_OTC", "AUDUSD_OTC"]
    assert assets[0].bridge_id == 179
    assert get_asset(assets[0].key) is assets[0]


async def test_inventory_reports_real_bridge_failure():
    bridge = FakeBridge(error=DataUnavailable("EO_BRIDGE_NOT_CONFIGURED", "No verified ExpertOption bridge is configured"))
    inventory = MarketInventory(bridge)
    with pytest.raises(DataUnavailable) as excinfo:
        await inventory.assets(Market.OTC)
    assert "bridge" in excinfo.value.message.lower()


async def test_forex_pairs_reach_registry_provider(settings, repo):
    registry = DataSourceRegistry([FakeProvider(quote_price=1.1)])
    generator = SignalGenerator(registry, repo, settings)
    pairs = [asset for asset in assets_for(Market.FOREX)]
    assert len(pairs) >= 9
    for asset in pairs:
        result, _ = await generator.generate(42, asset, "5min", min_confidence=0.0)
        assert result.source == "Fake Feed"
        assert result.market == Market.FOREX.value


async def test_gold_reaches_registry_provider(settings, repo):
    registry = DataSourceRegistry([FakeProvider(quote_price=2000.0)])
    generator = SignalGenerator(registry, repo, settings)
    result, _ = await generator.generate(42, get_asset("XAU_USD_GOLD"), "15min", min_confidence=0.0)
    assert result.market == Market.GOLD.value
    assert result.source == "Fake Feed"


async def test_otc_uses_bridge_candles_only(settings, repo):
    bridge = FakeBridge(OTC_ROWS)
    inventory = MarketInventory(bridge)
    otc_asset = (await inventory.assets(Market.OTC))[0]
    registry = DataSourceRegistry([FakeProvider(quote_price=1.1), bridge])
    generator = SignalGenerator(registry, repo, settings)
    result, _ = await generator.generate(42, otc_asset, "1min", min_confidence=0.0)
    assert result.source == "ExpertOption Bridge"
    assert result.market == Market.OTC.value


async def test_smarty_card_shows_durations_not_currencies():
    asset = SMARTY_ASSET
    text = fmt.smarty_card_text(asset, "ExpertOption Bridge", "ID 240")
    assert "EUR/USD" not in text
    assert "SMARTY" in text
    markup = kb.smarty_menu(asset)
    callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert f"sm:{asset.key}:60" in callbacks
    assert not any(str(data).startswith("tf:") for data in callbacks)


async def test_smarty_menu_unavailable_without_bridge(monkeypatch):
    from bot import context
    from bot.handlers import menus as handlers
    from tests.test_handlers import FakeCallback, FakeRegistry

    inventory = MarketInventory(FakeBridge(error=DataUnavailable("EO_BRIDGE_NOT_CONFIGURED", "bridge missing")))
    monkeypatch.setattr(
        context,
        "_context",
        SimpleNamespace(registry=FakeRegistry(), inventory=inventory, settings=SimpleNamespace(min_confidence=65.0)),
        raising=False,
    )
    callback = FakeCallback("mkt:SMARTY")
    await handlers.cb_market(callback)
    text = callback.message.edits[-1][0]
    assert "SMARTY_UNAVAILABLE" in text
    assert "EUR/USD" not in text


async def test_status_panel_uses_live_probe_not_env():
    bridge = FakeBridge(OTC_ROWS)
    registry = DataSourceRegistry([FakeProvider(), bridge])
    health = MarketHealthService(registry, MarketInventory(bridge))
    snapshot = await health.snapshot(force=True)
    text = fmt.status_text(
        SimpleNamespace(min_confidence=65.0, scan_interval=90),
        [{"name": "ExpertOption Bridge", "configured": True, "can_serve_candles": True, "detail": ""}],
        snapshot,
        {"ready": False},
    )
    assert "MARKET COVERAGE (LIVE PROBE)" in text
    assert "🟢 LIVE" in text or "🔴 UNAVAILABLE" in text
    assert "NOT PROBED" not in text


async def test_health_probe_surfaces_real_reason():
    broken = FakeProvider()
    broken.fail = True
    registry = DataSourceRegistry([broken])
    bridge = FakeBridge(error=DataUnavailable("EO_BRIDGE_NOT_CONFIGURED", "No verified ExpertOption bridge is configured"))
    health = MarketHealthService(registry, MarketInventory(bridge))
    snapshot = await health.snapshot(force=True)
    assert snapshot[Market.OTC.value].ok is False
    assert snapshot[Market.OTC.value].error


async def test_scanner_skips_unavailable_market_with_reason(settings, repo):
    from services.scanner import AutoScanner

    broken = FakeProvider()
    broken.fail = True
    registry = DataSourceRegistry([broken])
    generator = SignalGenerator(registry, repo, settings)
    inventory = MarketInventory(FakeBridge(error=DataUnavailable("EO_BRIDGE_NOT_CONFIGURED", "bridge missing")))
    from dataclasses import replace

    scan_settings = replace(settings, scan_markets="OTC")
    scanner = AutoScanner(generator, repo, registry, scan_settings, inventory=inventory)
    await scanner.scan_once()
    assert "OTC" in scanner.last_skips
    assert "bridge" in scanner.last_skips["OTC"].lower()
