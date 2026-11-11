"""Local emulation of the ExpertOption gateway.

These tests prove how the bridge parses an ExpertOption payload: token errors,
SMARTY asset discovery, millisecond period timestamps, [open, close, low, high]
row ordering and OHLC validation. They use a local websocket server and
synthetic bars, so they do not claim that a live ExpertOption account works.
"""
from __future__ import annotations

import asyncio
import json
import time

import aiohttp
import pytest
from aiohttp import WSMsgType, web

from eo_bridge.app import BridgeApp
from eo_bridge.eo_client import BridgeError, ExpertOptionClient
from eo_bridge.settings import BridgeSettings

GOOD_TOKEN = "good-token"
SMARTY_ID = 240


def _settings(url: str, token: str | None = GOOD_TOKEN) -> BridgeSettings:
    return BridgeSettings(
        api_key="test-key",
        eo_token=token,
        eo_region=url,
        eo_demo=True,
        host="127.0.0.1",
        port=0,
        candle_history_seconds=7200,
        quote_cache_seconds=1.0,
        candle_cache_seconds=3.0,
        log_level="INFO",
    )


def _assets_payload() -> dict:
    return {
        "assets": [
            {"id": SMARTY_ID, "symbol": "SMRTY", "name": "Smarty", "precision": 2, "is_active": 1},
            {"id": 142, "symbol": "EURUSD", "name": "EUR/USD", "precision": 5, "is_active": 1},
        ]
    }


def _history_payload(rows: int = 90, tf: int = 60) -> dict:
    now = int(time.time())
    start = (now // tf) * tf - rows * tf
    # ms timestamps and [open, close, low, high] ordering, both seen in EO builds
    periods = []
    price = 1000.0
    for index in range(rows):
        open_ = price
        close = price + (0.3 if index % 3 else -0.2)
        low = min(open_, close) - 0.15
        high = max(open_, close) + 0.15
        price = close
        periods.append([open_, close, low, high])
    return {
        "assetId": SMARTY_ID,
        "asset": "SMRTY",
        "tf": tf,
        "candles": [{"periods": [[start * 1000, periods]]}],
    }


async def _gateway(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    authed = False
    async for message in ws:
        if message.type is not WSMsgType.TEXT:
            continue
        data = json.loads(message.data)
        action = data.get("action")
        ns = data.get("ns")
        if action == "multipleAction":
            token = (data.get("message") or {}).get("token")
            if token != GOOD_TOKEN:
                await ws.send_json({"action": "error", "ns": ns, "message": "token is invalid or expired"})
                continue
            authed = True
            await ws.send_json({"action": "assets", "ns": ns, "message": _assets_payload()})
        elif action == "assets":
            if not authed:
                await ws.send_json({"action": "error", "ns": ns, "message": "token is invalid or expired"})
                continue
            await ws.send_json({"action": "assets", "ns": ns, "message": _assets_payload()})
        elif action == "subscribeCandles":
            await ws.send_json({"action": "subscribeCandles", "ns": ns, "message": {"success": True}})
        elif action == "assetHistoryCandles":
            await ws.send_json({"action": "assetHistoryCandles", "ns": ns, "message": _history_payload()})
        elif action in {"profile", "getCandlesTimeframes", "setTimeZone"}:
            await ws.send_json({"action": action, "ns": ns, "message": {}})
    return ws


@pytest.fixture
async def gateway_url():
    app = web.Application()
    app.router.add_get("/", _gateway)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001 - test fixture
    yield f"ws://127.0.0.1:{port}/"
    await runner.cleanup()


async def test_smarty_assets_and_candles(gateway_url):
    client = ExpertOptionClient(_settings(gateway_url))
    try:
        instruments = await client.ensure_assets()
        smarty = [item for item in instruments if item.market == "smarty"]
        assert [item.id for item in smarty] == [SMARTY_ID]
        assert smarty[0].symbol == "SMRTY"

        candles = await client.get_candles(smarty[0], 60, limit=60)
        assert len(candles) >= 60
        assert all(candle.time < time.time() + 60 for candle in candles)
        for candle in candles:
            assert candle.high >= max(candle.open, candle.close)
            assert candle.low <= min(candle.open, candle.close)
        assert candles == sorted(candles, key=lambda candle: candle.time)
    finally:
        await client.stop()


async def test_invalid_token_is_reported_not_retried_forever(gateway_url):
    client = ExpertOptionClient(_settings(gateway_url, token="expired-token"))
    try:
        with pytest.raises(BridgeError) as excinfo:
            await asyncio.wait_for(client.ensure_assets(), timeout=20)
        assert excinfo.value.code == "TOKEN_INVALID"
        assert "token" in excinfo.value.message.lower()
        assert client.status()["last_error"].startswith("TOKEN_INVALID")
    finally:
        await client.stop()


async def test_missing_token_raises_clear_error(gateway_url):
    client = ExpertOptionClient(_settings(gateway_url, token=None))
    try:
        with pytest.raises(BridgeError) as excinfo:
            await client.ensure_assets()
        assert excinfo.value.code == "EO_TOKEN_MISSING"
    finally:
        await client.stop()


async def test_reconnect_resubscribes_after_socket_drop(gateway_url):
    client = ExpertOptionClient(_settings(gateway_url))
    try:
        instruments = await client.ensure_assets()
        smarty = next(item for item in instruments if item.market == "smarty")
        await client.get_candles(smarty, 60, limit=60)
        assert client._subscriptions  # noqa: SLF001 - asserting cache state

        await client._close_socket()  # noqa: SLF001 - simulate a dropped socket
        assert not client._subscriptions  # noqa: SLF001 - must be re-sent after reconnect

        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not client.connected:
            await asyncio.sleep(0.1)
        assert client.connected
        candles = await client.get_candles(smarty, 60, limit=60)
        assert len(candles) >= 60
    finally:
        await client.stop()


async def test_http_smarty_endpoint_serves_bridge_candles(gateway_url):
    bridge_app = BridgeApp(_settings(gateway_url))
    runner = web.AppRunner(bridge_app.build())
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # noqa: SLF001 - test fixture
    base = f"http://127.0.0.1:{port}"
    headers = {"X-API-Key": "test-key"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{base}/health") as response:
                health = await response.json()
                assert response.status == 200
                assert health["configured"] is True
                assert health["connected"] is True

            async with session.get(f"{base}/assets?market=smarty", headers=headers) as response:
                payload = await response.json()
                assert response.status == 200
                assert payload["count"] == 1
                assert payload["assets"][0]["id"] == SMARTY_ID

            async with session.get(f"{base}/smarty?timeframe=1min&limit=90", headers=headers) as response:
                payload = await response.json()
                assert response.status == 200, payload
                assert payload["asset_id"] == SMARTY_ID
                assert len(payload["candles"]) >= 60
                assert payload["stale_seconds"] < 180

            async with session.get(f"{base}/smarty", headers={"X-API-Key": "wrong"}) as response:
                assert response.status == 401
    finally:
        await runner.cleanup()
