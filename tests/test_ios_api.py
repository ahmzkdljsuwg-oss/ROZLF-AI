from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from providers.base import DataUnavailable
from providers.catalog import Market, dynamic_asset
from providers.registry import DataSourceRegistry
from services.ios_api import install
from tests.conftest import FakeProvider, make_candles


class Feed(FakeProvider):
    markets = frozenset({Market.FOREX, Market.SMARTY, Market.OTC})

    def __init__(self):
        super().__init__()
        self.calls = []

    async def fetch_candles(self, asset, tf, limit=300):
        self.calls.append((asset.market, asset.key, tf.code))
        if asset.market is Market.OTC:
            raise DataUnavailable("EMPTY", "No verified OTC bars")
        return make_candles(n=300, tf_seconds=tf.seconds)


class Inventory:
    async def assets(self, market):
        return {
            Market.SMARTY: [dynamic_asset("SMARTY", market, bridge_id=240)],
            Market.OTC: [dynamic_asset("USDNGN_OTC_R", market, bridge_id=559)],
        }.get(market, [])


async def test_native_scan_auth_and_market_isolation():
    provider = Feed()
    context = SimpleNamespace(registry=DataSourceRegistry([provider]), inventory=Inventory(), vision=None)
    app = web.Application()
    install(app, lambda: context, "a-test-device-token")
    async with TestClient(TestServer(app)) as client:
        path = "/api/nexus/v1/"
        auth = {"Authorization": "Bearer a-test-device-token"}
        assert (await client.get(path + "health")).status == 401
        assert (await client.get(path + "health", headers=auth)).status == 200
        markets = await (await client.get(path + "markets", headers=auth)).json()
        assert {m["key"] for m in markets["markets"]} == {"forex", "smarty", "otc"}
        scan = await (await client.post(path + "scan?mode=lo", headers=auth)).json()
        assert scan["checked"] == 3
        assert {item["market"] for item in scan["items"]} == {"forex", "smarty"}
        assert "OTC" in scan["unavailable"]
        for result in scan["items"]:
            assert result["direction"] in {"UP", "DOWN", "NO TRADE"}
            assert result["confidence"] is None
            assert 0 < len(result["candles"]) <= 48
        broken = await client.post(path + "analyze", headers=auth, json={
            "market": "otc", "asset": "EUR_USD_FOREX", "mode": "lo"
        })
        assert broken.status == 404
        selected = await client.post(path + "analyze", headers=auth, json={
            "market": "forex", "asset": "GBP_JPY_FOREX", "mode": "lo"
        })
        assert selected.status == 200
        assert (await selected.json())["asset_key"] == "GBP_JPY_FOREX"
        assert (Market.FOREX, "GBP_JPY_FOREX", "1min") in provider.calls
        assert (await client.post(path + "image", headers=auth, data=b"image")).status == 503


async def test_api_only_enabled_when_token_configured():
    app = web.Application()
    install(app, lambda: None, "")
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/api/nexus/v1/health")).status == 404


async def test_scan_preserves_no_trade_when_calibration_fails(monkeypatch):
    from engines.technical import next_candle

    monkeypatch.setattr(next_candle, "load_calibration", lambda: {})
    feed = Feed()
    context = SimpleNamespace(registry=DataSourceRegistry([feed]), inventory=Inventory(), vision=None)
    app = web.Application()
    install(app, lambda: context, "key")
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/api/nexus/v1/scan", headers={"Authorization": "Bearer key"})
        assert response.status == 200
        data = await response.json()
        assert data["items"]
        assert all(r["direction"] == "NO TRADE" for r in data["items"])


async def test_invalid_chart_image_returns_validation_message():
    class Vision:
        configured = True

    app = web.Application()
    install(app, lambda: SimpleNamespace(vision=Vision()), "key")
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/api/nexus/v1/image", headers={"Authorization": "Bearer key"}, data=b"")
        assert response.status == 400
        assert (await response.json())["message"]
