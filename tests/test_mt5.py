"""MT5 market analysis: catalog, bridge, provider validation, menu and formatter."""
from __future__ import annotations

from datetime import timedelta

import httpx
import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot import formatting as fmt
from bot.keyboards import menus
from engines.technical.analyzer import analyze_market_data
from engines.validation import validate_candles
from mt5_bridge.app import create_app
from mt5_bridge.client import canonical_symbol
from mt5_bridge.settings import BridgeSettings
from providers.base import DataUnavailable, MarketData, utc_now
from providers.catalog import MT5_ASSETS, get_asset, timeframe
from providers.mt5 import MT5BridgeProvider, discovered_assets

from tests.conftest import make_candles

ASSET = get_asset("MT5_AUDCAD")
TF = timeframe("1min")


def candles_payload(count: int = 260, age_seconds: int = 30) -> list[dict]:
    stamps = [utc_now() - timedelta(seconds=age_seconds + 60 * (count - 1 - i)) for i in range(count)]
    return [
        {
            "time": stamp.isoformat().replace("+00:00", "Z"),
            "open": 1.0400 + i * 0.00001, "high": 1.0405 + i * 0.00001,
            "low": 1.0395 + i * 0.00001, "close": 1.0402 + i * 0.00001,
            "tick_volume": 100, "spread": 10, "real_volume": 0,
        }
        for i, stamp in enumerate(stamps)
    ]


def payload(kind: str = "candles", *, age_seconds: int = 30, source: str = "MetaTrader 5") -> dict:
    base = {
        "ok": True, "market": "MT5", "source": source, "terminal_connected": True,
        "canonical": "AUDCAD", "symbol": "AUDCAD", "broker": "AUDCAD.a",
    }
    if kind == "quote":
        return {**base, "bid": 1.0401, "ask": 1.0402,
                "time": (utc_now() - timedelta(seconds=age_seconds)).isoformat().replace("+00:00", "Z")}
    if kind == "symbols":
        return {**base, "symbols": [
            {"canonical": "AUDCAD", "broker": "AUDCAD.a", "description": "AUD vs CAD", "forex": True},
            {"canonical": "EURUSD", "broker": "EURUSD.a", "description": "EUR vs USD", "forex": True},
            {"canonical": "XAUUSD", "broker": "XAUUSD.a", "description": "Gold", "forex": False},
        ]}
    return {**base, "timeframe": "1min", "candles": candles_payload(age_seconds=age_seconds)}


def provider(handler) -> MT5BridgeProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return MT5BridgeProvider("http://bridge.local", "secret", client=client)


def test_canonical_symbol_handles_broker_suffixes() -> None:
    assert canonical_symbol("AUDCAD") == "AUDCAD"
    assert canonical_symbol("AUDCAD.a") == "AUDCAD"
    assert canonical_symbol("EURUSD_pro") == "EURUSD"
    assert canonical_symbol("GBPJPYm") == "GBPJPY"
    assert canonical_symbol("US30.cash") is None
    assert canonical_symbol("BTCUSD") is None


def test_catalog_holds_the_28_requested_pairs() -> None:
    assert len(MT5_ASSETS) == 28
    assert len({asset.key for asset in MT5_ASSETS}) == 28
    assert get_asset("MT5_EURUSD").symbol == "EUR/USD"
    assert all(asset.market.value == "mt5" for asset in MT5_ASSETS)


@pytest.mark.asyncio
async def test_provider_reads_real_bridge_contract() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "secret"
        assert request.url.params["symbol"] == "AUDCAD"
        return httpx.Response(200, json=payload("candles"))

    feed = provider(handler)
    candles = await feed.fetch_candles(ASSET, TF, limit=300)
    assert len(candles) == 260
    assert candles == sorted(candles, key=lambda item: item.time)
    await feed.close()


@pytest.mark.asyncio
async def test_provider_rejects_wrong_market_source_and_symbol() -> None:
    async def wrong_source(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload(source="Yahoo Finance"))

    with pytest.raises(DataUnavailable) as exc:
        await (provider(wrong_source)).fetch_candles(ASSET, TF)
    assert exc.value.code == "MT5_OFFLINE"

    async def wrong_symbol(request: httpx.Request) -> httpx.Response:
        data = payload("candles")
        data["canonical"] = "EURUSD"
        return httpx.Response(200, json=data)

    with pytest.raises(DataUnavailable) as exc:
        await (provider(wrong_symbol)).fetch_candles(ASSET, TF)
    assert exc.value.code == "MT5_SYMBOL_MISMATCH"


@pytest.mark.asyncio
async def test_provider_rejects_stale_candles_and_ticks() -> None:
    async def stale_candles(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload("candles", age_seconds=900))

    with pytest.raises(DataUnavailable) as exc:
        await (provider(stale_candles)).fetch_candles(ASSET, TF)
    assert exc.value.code == "MT5_STALE_DATA"

    async def stale_quote(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload("quote", age_seconds=600))

    with pytest.raises(DataUnavailable) as exc:
        await (provider(stale_quote)).fetch_quote(ASSET)
    assert exc.value.code == "MT5_STALE_TICK"


@pytest.mark.asyncio
async def test_provider_lists_only_broker_forex_symbols() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload("symbols"))

    feed = provider(handler)
    rows = await feed.list_fx_symbols()
    assets = discovered_assets(rows)
    assert [asset.key for asset in assets] == ["MT5_AUDCAD", "MT5_EURUSD"]
    assert assets[0].bridge_symbol == "AUDCAD.a"
    await feed.close()


@pytest.mark.asyncio
async def test_provider_is_offline_without_configuration() -> None:
    feed = MT5BridgeProvider(None, None)
    assert feed.configured is False
    with pytest.raises(DataUnavailable) as exc:
        await feed.fetch_candles(ASSET, TF)
    assert exc.value.code == "MT5_NOT_CONFIGURED"


def test_mt5_analysis_uses_alligator_and_ma200() -> None:
    candles = make_candles(260, drift=0.00008, noise=0.00001, tf_seconds=60)
    data = MarketData(
        asset=ASSET, timeframe=TF, candles=candles, source="MetaTrader 5",
        quote=None, validation=validate_candles(candles, TF, min_bars=200),
    )
    result = analyze_market_data(data, duration_seconds=60)
    assert result.market == "mt5"
    assert result.direction in {"BUY", "SELL", "NO TRADE"}
    assert result.alligator_ma["ma_type"] == "EMA 200"
    text = fmt.mt5_analysis_text(result, data, 60)
    assert "MT5 MARKET ANALYSIS" in text
    assert "ALLIGATOR" in text
    assert "EMA 200" in text
    assert "ANALYSIS ONLY" in text


def test_mt5_menus_and_formatters() -> None:
    main = menus.main_menu()
    datas = [button.callback_data for row in main.inline_keyboard for button in row]
    assert "mt5:list" in datas

    pairs = menus.mt5_pairs_menu(list(MT5_ASSETS))
    assert any(button.text == "🎯 AUD/CAD" for row in pairs.inline_keyboard for button in row)

    durations = menus.mt5_duration_menu(ASSET)
    callbacks = [button.callback_data for row in durations.inline_keyboard for button in row]
    assert [f"mt5d:MT5_AUDCAD:{value}" for value in (60, 300, 900, 1800, 3600)] == [
        item for item in callbacks if item.startswith("mt5d:")
    ]
    assert "MT5 OFFLINE" in fmt.mt5_offline_text("terminal disconnected")
    assert "PAIRS AVAILABLE" in fmt.mt5_pairs_text(list(MT5_ASSETS))


class FakeMT5:
    def __init__(self, stale: bool = False) -> None:
        self.stale = stale

    def status(self) -> dict:
        return {"terminal_connected": True, "server": "Broker-Demo", "account": 42}

    def symbols(self) -> list[dict]:
        return [{"canonical": "AUDCAD", "broker": "AUDCAD.a", "forex": True}]

    def candles(self, symbol: str, frame: str, limit: int):
        stamp = utc_now() - timedelta(hours=5 if self.stale else 0, seconds=30)
        return "AUDCAD.a", [{
            "time": stamp.isoformat().replace("+00:00", "Z"),
            "open": 1.04, "high": 1.05, "low": 1.03, "close": 1.045,
            "tick_volume": 10, "spread": 5, "real_volume": 0,
        }]

    def quote(self, symbol: str):
        return "AUDCAD.a", {
            "bid": 1.0401, "ask": 1.0402,
            "time": (utc_now() - timedelta(seconds=5)).isoformat().replace("+00:00", "Z"),
            "broker": "AUDCAD.a",
        }


def settings() -> BridgeSettings:
    return BridgeSettings(
        api_key="secret", host="127.0.0.1", port=0, terminal_path=None,
        login=None, password=None, server=None, max_age_seconds=180,
    )


@pytest.mark.asyncio
async def test_bridge_requires_api_key_and_returns_candles() -> None:
    client = TestClient(TestServer(create_app(settings(), FakeMT5())))
    await client.start_server()
    try:
        unauth = await client.get("/candles", params={"symbol": "AUDCAD", "timeframe": "1min"})
        assert unauth.status == 401
        bad_key = await client.get("/candles", headers={"X-API-Key": "wrong"})
        assert bad_key.status == 401
        ok = await client.get(
            "/candles", params={"symbol": "AUDCAD", "timeframe": "1min"},
            headers={"X-API-Key": "secret"},
        )
        body = await ok.json()
        assert ok.status == 200
        assert body["market"] == "MT5" and body["canonical"] == "AUDCAD"
        assert body["terminal_connected"] is True
        assert body["candles"][0]["close"] == 1.045
        symbols = await client.get("/symbols", headers={"X-API-Key": "secret"})
        assert (await symbols.json())["symbols"][0]["broker"] == "AUDCAD.a"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_bridge_returns_503_for_stale_terminal_data() -> None:
    client = TestClient(TestServer(create_app(settings(), FakeMT5(stale=True))))
    await client.start_server()
    try:
        response = await client.get(
            "/candles", params={"symbol": "AUDCAD", "timeframe": "1min"},
            headers={"Authorization": "Bearer secret"},
        )
        assert response.status == 503
        assert (await response.json())["error"] == "MT5_STALE_DATA"
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("seconds", "frame_code"),
    [(60, "1min"), (300, "5min"), (900, "15min"), (1800, "30min"), (3600, "1h")],
)
def test_every_mt5_duration_maps_to_a_supported_frame(seconds: int, frame_code: str) -> None:
    from bot.handlers.menus import analysis_frame_for_duration

    assert analysis_frame_for_duration(ASSET, seconds) == frame_code


@pytest.mark.parametrize("seconds", [60, 300, 900, 1800, 3600])
@pytest.mark.parametrize("asset_key", [asset.key for asset in MT5_ASSETS])
def test_every_pair_analyses_on_every_duration(asset_key: str, seconds: int) -> None:
    from bot.handlers.menus import analysis_frame_for_duration

    asset = get_asset(asset_key)
    frame = timeframe(analysis_frame_for_duration(asset, seconds))
    candles = make_candles(260, drift=0.00008, noise=0.00001, tf_seconds=frame.seconds)
    data = MarketData(
        asset=asset, timeframe=frame, candles=candles, source="MetaTrader 5",
        quote=None, validation=validate_candles(candles, frame, min_bars=200),
    )
    result = analyze_market_data(data, duration_seconds=seconds)
    assert result.direction in {"BUY", "SELL", "NO TRADE"}
    assert 0 <= result.confidence <= 100
    assert "MT5 MARKET ANALYSIS" in fmt.mt5_analysis_text(result, data, seconds)
