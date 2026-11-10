"""AI / Football / Luxury index markets: discovery, isolation, analysis."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import pi, sin

from bot import formatting as fmt
from providers.base import Candle
from engines.signals.generator import SignalGenerator, supported_durations
from providers.base import DataUnavailable
from providers.catalog import Market, get_asset, timeframe
from providers.inventory import MarketInventory
from providers.registry import DataSourceRegistry
from tests.conftest import FakeProvider, make_candles

INDEX_ROWS = (
    {"id": 285, "symbol": "AI_INDEX_OTC_R", "name": "AI Index", "market": "ai", "precision": 5},
    {"id": 278, "symbol": "FOOTBALL_INDEX_OTC_R", "name": "Football Index", "market": "football", "precision": 5},
    {"id": 286, "symbol": "LUXURY_INDEX_OTC_R", "name": "Luxury Index", "market": "luxury", "precision": 5},
)


class IndexBridge(FakeProvider):
    id = "eo_bridge"
    name = "ExpertOption Bridge"
    markets = frozenset({Market.OTC, Market.SMARTY, Market.AI, Market.FOOTBALL, Market.LUXURY})
    quote_price = None

    def __init__(self, drift: float = 0.02, error: DataUnavailable | None = None, candles=None) -> None:
        super().__init__(candles=candles or make_candles(200, tf_seconds=30, start=1000.0, drift=drift, noise=0.0))
        self.error = error

    async def fetch_assets(self, market: Market):
        if self.error is not None:
            raise self.error
        return [dict(row) for row in INDEX_ROWS if row["market"] == market.value]


async def test_index_assets_discovered_with_verified_ids():
    inventory = MarketInventory(IndexBridge())
    for market, expected_id in ((Market.AI, 285), (Market.FOOTBALL, 278), (Market.LUXURY, 286)):
        assets = await inventory.assets(market, force=True)
        assert len(assets) == 1
        assert assets[0].bridge_id == expected_id
        assert assets[0].market is market


async def test_index_unavailable_surfaces_reason():
    inventory = MarketInventory(IndexBridge(error=DataUnavailable("EO_ERROR", "no candles")))
    try:
        await inventory.assets(Market.AI, force=True)
    except DataUnavailable as exc:
        assert exc.code == "EO_ERROR"
        assert "UNAVAILABLE" in exc.message
    else:  # pragma: no cover
        raise AssertionError("index must not be served without bridge data")


async def test_index_analysis_uses_its_own_candles(settings, repo):
    registry = DataSourceRegistry([IndexBridge()])
    generator = SignalGenerator(registry, repo, settings)
    asset = get_asset("AI_INDEX_OTC_R_AI")
    result, record = await generator.generate(7, asset, "30sec", duration_seconds=45, min_confidence=0.0)
    assert result.market == "ai"
    assert result.direction in {"UP", "DOWN", "NO TRADE"}
    assert result.indicators["rsi"] is not None
    assert result.suggested_expiry_seconds in supported_durations(asset, timeframe("30sec"))
    text = fmt.smarty_result_text(result, record)
    assert "AI INDEX" in text
    assert "SMARTY ANALYSIS" not in text


def _conflicting_candles(count: int = 160) -> list[Candle]:
    now = datetime.now(timezone.utc)
    candles = []
    for i in range(count):
        close = 1000 + 1 * sin(2 * pi * i / 6)
        opened = 1000 + 1 * sin(2 * pi * (i - 1) / 6)
        candles.append(
            Candle(
                time=now - timedelta(seconds=30 * (count - i)),
                open=opened,
                high=max(opened, close) + 0.05,
                low=min(opened, close) - 0.05,
                close=close,
                volume=0.0,
            )
        )
    return candles


async def test_conflicting_index_market_returns_no_trade(settings, repo):
    registry = DataSourceRegistry([IndexBridge(candles=_conflicting_candles())])
    generator = SignalGenerator(registry, repo, settings)
    asset = get_asset("FOOTBALL_INDEX_OTC_R_FOOTBALL")
    result, record = await generator.generate(8, asset, "30sec", duration_seconds=30, min_confidence=0.0)
    assert result.direction == "NO TRADE"
    assert record is None


async def test_index_durations_are_expertoption_native():
    for key in ("AI_INDEX_OTC_R_AI", "FOOTBALL_INDEX_OTC_R_FOOTBALL", "LUXURY_INDEX_OTC_R_LUXURY"):
        allowed = supported_durations(get_asset(key), timeframe("1min"))
        assert {5, 15, 30, 45, 60, 105, 300}.issubset(set(allowed))
        assert 180 not in allowed


async def test_forex_durations_gain_45_and_105():
    allowed = supported_durations(get_asset("EUR_USD_FOREX"), timeframe("1min"))
    assert {30, 45, 60, 105}.issubset(set(allowed))


async def test_index_data_never_served_to_other_markets():
    inventory = MarketInventory(IndexBridge())
    for other in (Market.OTC, Market.SMARTY):
        try:
            await inventory.assets(other, force=True)
        except DataUnavailable:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"{other} must not borrow index data")
    assert all(a.market is not Market.SMARTY for a in await inventory.assets(Market.AI, force=True))
