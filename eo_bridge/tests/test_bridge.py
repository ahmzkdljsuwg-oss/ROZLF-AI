"""End-to-end tests for ROZLF-EO-BRIDGE against a local protocol mock.

The mock speaks the same message envelopes as ExpertOption so the bridge code
can be exercised without an account. It is a test double only: nothing here is
presented as real market data.
"""
from __future__ import annotations

import json
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from eo_bridge.app import BridgeApp
from eo_bridge.catalog import (
    Instrument,
    classify,
    find_smarty,
    normalise_symbol,
    resolve,
    timeframe_seconds,
)
from eo_bridge.eo_client import ExpertOptionClient
from eo_bridge.settings import BridgeSettings

API_KEY = "test-bridge-key"


def make_settings(ws_url: str, token: str = "session-token") -> BridgeSettings:
    return BridgeSettings(
        api_key=API_KEY,
        eo_token=token,
        eo_region=ws_url,
        eo_demo=True,
        host="127.0.0.1",
        port=0,
        candle_history_seconds=1800,
        quote_cache_seconds=0.0,
        candle_cache_seconds=0.0,
        log_level="WARNING",
    )


ASSETS = [
    {"id": 142, "symbol": "EURUSD", "name": "EUR/USD", "is_active": 1, "profit": 80, "precision": 5},
    {"id": 179, "symbol": "EURUSD_OTC", "name": "EUR/USD OTC", "is_active": 1, "profit": 82, "is_otc": True, "precision": 5},
    {"id": 176, "symbol": "XAUUSD", "name": "Gold", "is_active": 1, "profit": 70, "precision": 2},
    {"id": 240, "symbol": "SMRTY", "name": "Smarty", "is_active": 1, "profit": 90, "precision": 5},
]


def candle_periods(asset_id: int, tf: int, count: int = 40) -> dict:
    now = int(time.time())
    start = now - (now % tf) - tf * count
    rows = []
    price = 1.0850
    for index in range(count):
        price += 0.0001
        rows.append([round(price, 5), round(price + 0.0002, 5), round(price - 0.0002, 5), round(price + 0.0001, 5)])
    return {"assetId": asset_id, "tf": tf, "candles": [{"periods": [[start, rows]]}]}


async def mock_socket(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)

    async def reply(action: str, ns, message) -> None:
        await ws.send_str(json.dumps({"action": action, "ns": ns, "message": message, "v": 23}))

    async for frame in ws:
        if frame.type is not web.WSMsgType.TEXT:
            continue
        data = json.loads(frame.data)
        action = data.get("action")
        ns = data.get("ns")
        if action == "ping":
            await reply("ping", ns, {})
        elif action == "multipleAction":
            for sub in data.get("message", {}).get("actions", []):
                name = sub.get("action")
                if name == "assets":
                    await reply("assets", sub.get("ns"), {"assets": ASSETS})
                elif name == "profile":
                    await reply("profile", sub.get("ns"), {"profile": {"id": 1}})
                elif name == "getCandlesTimeframes":
                    await reply("getCandlesTimeframes", sub.get("ns"), {"candlesTimeframes": [5, 60, 300, 900, 1800, 3600]})
        elif action == "assets":
            await reply("assets", ns, {"assets": ASSETS})
        elif action == "subscribeCandles":
            await reply("subscribeCandles", ns, {"assets": data.get("message", {}).get("assets", [])})
        elif action == "assetHistoryCandles":
            body = data.get("message", {})
            asset_id = int(body.get("assetid") or 0)
            tf = int((body.get("timeframes") or [60])[0])
            await ws.send_str(json.dumps({"action": "assetHistoryCandles", "ns": ns, "message": candle_periods(asset_id, tf)}))
    return ws


@pytest.fixture
async def bridge_client():
    socket_app = web.Application()
    socket_app.router.add_get("/ws", mock_socket)
    socket_server = TestServer(socket_app)
    await socket_server.start_server()
    ws_url = str(socket_server.make_url("/ws")).replace("http://", "ws://")

    client = ExpertOptionClient(make_settings(ws_url))
    app = BridgeApp(make_settings(ws_url), client).build()
    server = TestServer(app)
    test_client = TestClient(server)
    await test_client.start_server()
    yield test_client
    await test_client.close()
    await socket_server.close()


async def test_requires_api_key(bridge_client: TestClient) -> None:
    response = await bridge_client.get("/assets?market=otc")
    assert response.status == 401
    body = await response.json()
    assert body["error"] == "UNAUTHORIZED"


async def test_health_reports_connection(bridge_client: TestClient) -> None:
    response = await bridge_client.get("/health")
    assert response.status == 200
    body = await response.json()
    assert body["service"] == "ROZLF-EO-BRIDGE"
    assert body["configured"] is True


async def test_assets_list_marks_otc_and_smarty(bridge_client: TestClient) -> None:
    response = await bridge_client.get("/assets", headers={"X-API-Key": API_KEY})
    assert response.status == 200
    body = await response.json()
    by_symbol = {item["symbol"]: item for item in body["assets"]}
    assert by_symbol["EURUSD_OTC"]["market"] == "otc"
    assert by_symbol["SMRTY"]["market"] == "smarty"
    assert by_symbol["XAUUSD"]["market"] == "gold"


async def test_quote_returns_requested_symbol(bridge_client: TestClient) -> None:
    response = await bridge_client.get(
        "/quote?market=otc&symbol=EURUSD", headers={"X-API-Key": API_KEY}
    )
    assert response.status == 200
    body = await response.json()
    assert body["symbol"] == "EURUSD"
    assert body["eo_symbol"] == "EURUSD_OTC"
    assert body["market"] == "otc"
    assert body["bid"] == body["ask"]
    assert body["source"] == "ExpertOption"


async def test_candles_are_sorted_ohlc(bridge_client: TestClient) -> None:
    response = await bridge_client.get(
        "/candles?market=otc&symbol=EURUSD&timeframe=5min&limit=30",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status == 200
    body = await response.json()
    assert body["symbol"] == "EURUSD"
    assert body["timeframe"] == "5min"
    assert len(body["candles"]) >= 10
    times = [row["timestamp"] for row in body["candles"]]
    assert times == sorted(times)
    for row in body["candles"]:
        assert row["high"] >= max(row["open"], row["close"])
        assert row["low"] <= min(row["open"], row["close"])


async def test_discover_lists_live_otc_assets(bridge_client: TestClient) -> None:
    response = await bridge_client.get("/discover", headers={"X-API-Key": API_KEY})
    assert response.status == 200
    body = await response.json()
    assert body["discovered"] is True
    assert body["counts"]["otc"] == 1
    assert body["otc_symbols"] == ["EURUSD_OTC"]
    assert body["smarty"][0]["symbol"] == "SMRTY"
    assert "XAUUSD" in body["gold_symbols"]


async def test_smarty_endpoint_returns_id_240(bridge_client: TestClient) -> None:
    response = await bridge_client.get("/smarty?timeframe=1min&limit=20", headers={"X-API-Key": API_KEY})
    assert response.status == 200
    body = await response.json()
    assert body["asset_id"] == 240
    assert body["eo_symbol"] == "SMRTY"
    assert body["market"] == "smarty"
    assert body["source"] == "ExpertOption"
    assert body["candles"]
    assert body["bid"] == body["candles"][-1]["close"]


async def test_smarty_endpoint_reports_missing_asset() -> None:
    instruments = [Instrument(179, "EURUSD_OTC", "EUR/USD OTC", "otc", True, 80, 5)]
    assert find_smarty(instruments) is None


async def test_smarty_pair_is_not_invented(bridge_client: TestClient) -> None:
    response = await bridge_client.get(
        "/candles?market=smarty&symbol=EURUSD&timeframe=5min",
        headers={"X-API-Key": API_KEY},
    )
    assert response.status == 404
    body = await response.json()
    assert body["error"] == "UNSUPPORTED_SYMBOL"


async def test_bad_timeframe_rejected(bridge_client: TestClient) -> None:
    response = await bridge_client.get(
        "/candles?market=otc&symbol=EURUSD&timeframe=7min", headers={"X-API-Key": API_KEY}
    )
    assert response.status == 400


async def test_missing_token_answers_data_unavailable() -> None:
    from dataclasses import replace

    settings = replace(make_settings("wss://example.invalid/", token=""), eo_token=None)
    client = ExpertOptionClient(settings)
    app = BridgeApp(settings, client).build()
    server = TestServer(app)
    test_client = TestClient(server)
    await test_client.start_server()
    try:
        health = await (await test_client.get("/health")).json()
        assert health["connected"] is False
        response = await test_client.get("/candles?market=otc&symbol=EURUSD&timeframe=5min", headers={"X-API-Key": API_KEY})
        assert response.status == 503
        assert (await response.json())["error"] == "EO_TOKEN_MISSING"
    finally:
        await test_client.close()


def test_catalog_classification_and_resolution() -> None:
    instruments = [
        Instrument(179, "EURUSD_OTC", "EUR/USD OTC", "otc", True, 80, 5),
        Instrument(142, "EURUSD", "EUR/USD", "forex", True, 80, 5),
        Instrument(240, "SMRTY", "Smarty", "smarty", True, 90, 5),
        Instrument(176, "XAUUSD", "Gold", "gold", True, 70, 2),
    ]
    assert resolve(instruments, "otc", "EUR/USD").symbol == "EURUSD_OTC"
    assert resolve(instruments, "forex", "EURUSD").symbol == "EURUSD"
    assert resolve(instruments, "smarty", "SMRTY").symbol == "SMRTY"
    assert resolve(instruments, "otc", "SMRTY") is None
    assert classify({"id": 240, "symbol": "SMRTY"}) == "smarty"
    assert classify({"id": 1, "symbol": "EURUSD", "is_otc": 1}) == "otc"
    assert normalise_symbol("xau/usd") == "XAUUSD"
    assert timeframe_seconds("15min") == 900
    assert timeframe_seconds("900") == 900
    assert timeframe_seconds("7min") is None
