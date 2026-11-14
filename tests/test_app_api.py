"""Native app API: public read-only routes, candle payloads and honest states."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from engines.technical.analyzer import AnalysisResult
from mini_app import api as mini_api
from providers.base import MarketData, Quote, ValidationReport, utc_now
from providers.catalog import Market, assets_for, find_by_symbol, timeframe
from tests.conftest import make_candles


def _market_data(asset, frame="1min", n=200):
    candles = make_candles(n=n, tf_seconds=timeframe(frame).seconds)
    return MarketData(
        asset=asset,
        candles=candles,
        quote=Quote(symbol=asset.symbol, bid=1.1004, ask=1.1006, time=utc_now(), source="fake"),
        timeframe=timeframe(frame),
        validation=ValidationReport(ok=True, bar_count=len(candles)),
        source="fake",
    )


def _result(asset, direction="UP", confidence=82.0):
    return AnalysisResult(
        asset_key=asset.key,
        asset_display=asset.display,
        market=asset.market.value,
        timeframe="1min",
        direction=direction,
        confidence=confidence,
        score_up=8.0,
        score_down=1.0,
        price=1.1012,
        source="fake",
        generated_at=datetime.now(timezone.utc),
        reasons=["Market structure", "Alligator confirmation", "EMA 200 trend"],
        trend_summary="BULLISH",
        momentum_strength="STRONG",
        evidence_score=73.0,
        data_quality_score=90.0,
        invalidation=["Close below EMA21 cancels the setup"],
        alligator_ma={"jaw": 1.099, "teeth": 1.0995, "lips": 1.1005},
        indicators={"volatility": "NORMAL", "rsi": 58.0},
        smc={"trend": "BULLISH"},
    )


class FakeRepo:
    def __init__(self):
        self.settings = {"min_confidence": 60.0}
        self.saved = []

    async def get_user_settings(self, user_id, defaults=None):
        return dict(self.settings)

    async def save_user_settings(self, user_id, settings):
        self.settings = dict(settings)
        self.saved.append((user_id, dict(settings)))

    async def recent_signals(self, limit=10, user_id=None):
        return []

    async def statistics(self, user_id=None):
        return {"accuracy": None, "verified": 3, "wins": 2, "losses": 1, "active": 1}


class FakeGenerator:
    def __init__(self, asset, direction="UP"):
        self.asset = asset
        self.direction = direction
        self.calls = []

    async def fetch_and_analyse(self, asset, tf, duration_seconds=None):
        self.calls.append((asset.key, str(tf), duration_seconds))
        return _market_data(asset, str(tf)), _result(asset, self.direction)

    async def create_signal(self, user_id, result, duration):
        return SimpleNamespace(id=501, expiry_seconds=duration)


class FakeRegistry:
    def statuses(self):
        return {"forex": {"ok": True, "source": "fake"}}

    async def fetch(self, asset, frame, limit=100):
        return _market_data(asset, str(frame))


def fake_context(asset):
    settings = SimpleNamespace(
        telegram_bot_token="123:TEST",
        min_confidence=60.0,
        eo_bridge_url=None,
        eo_bridge_key=None,
        async_database_url="sqlite+aiosqlite:///test.db",
    )
    ctx = SimpleNamespace(
        settings=settings,
        repo=FakeRepo(),
        generator=FakeGenerator(asset),
        registry=FakeRegistry(),
        inventory=None,
        health=None,
        mistral=SimpleNamespace(health=lambda: {"configured": False}),
    )
    ctx.generator.fetch_and_analyse = AsyncMock(side_effect=ctx.generator.fetch_and_analyse)
    return ctx


@pytest.fixture
def asset():
    return find_by_symbol("EUR/USD", Market.FOREX)


@pytest.fixture
async def client(asset):
    ctx = fake_context(asset)
    app = web.Application()
    mini_api.install(app, lambda: ctx)
    async with TestClient(TestServer(app)) as test_client:
        yield test_client, ctx


@pytest.mark.asyncio
async def test_public_health_does_not_require_telegram_auth(client):
    response = await client[0].get("/api/app/health")
    assert response.status == 200
    body = await response.json()
    assert body["engine"] == "ONLINE"
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_manual_analysis_returns_candles_entry_and_invalidation(client):
    response = await client[0].post(
        "/api/app/analyse", json={"market": "forex", "asset": "EUR_USD_FOREX", "duration": 300}
    )
    assert response.status == 200
    body = await response.json()
    assert body["direction"] == "UP"
    assert body["duration_mode"] == "manual"
    assert body["status"] == "READY"
    assert body["entry"]["ready"] is True
    assert body["entry"]["price"] == 1.1012
    assert body["entry"]["invalidation"]
    assert len(body["candle_analysis"]["candles"]) == 8
    assert body["candle_analysis"]["summary"]
    assert body["signal_id"] == 501


@pytest.mark.asyncio
async def test_auto_duration_is_explained_and_uses_verified_expiry(client):
    response = await client[0].post(
        "/api/app/analyse", json={"market": "forex", "asset": "EUR_USD_FOREX", "duration": "auto"}
    )
    assert response.status == 200
    body = await response.json()
    assert body["duration_mode"] == "auto"
    if body["direction"] in ("UP", "DOWN"):
        assert body["duration"] in body["available_durations"]
    else:
        assert body["duration"] is None
        assert body["entry"]["ready"] is False
    assert body["duration_reason"]


@pytest.mark.asyncio
async def test_no_trade_never_returns_an_entry(client):
    client[1].generator.direction = "NO TRADE"
    response = await client[0].post(
        "/api/app/analyse", json={"market": "forex", "asset": "EUR_USD_FOREX", "duration": 300}
    )
    body = await response.json()
    assert body["direction"] == "NO TRADE"
    assert body["entry"]["ready"] is False
    assert body["signal_id"] is None


@pytest.mark.asyncio
async def test_settings_round_trip_is_persisted_for_app_user(client):
    response = await client[0].post("/api/app/settings", json={"min_confidence": 80})
    assert response.status == 200
    body = await response.json()
    assert body["settings"]["min_confidence"] == 80.0
    assert client[1].repo.saved


@pytest.mark.asyncio
async def test_app_markets_lists_the_six_traded_markets(client):
    response = await client[0].get("/api/app/markets")
    body = await response.json()
    keys = {row["key"] for row in body["markets"]}
    assert keys == {"SMARTY", "FOOTBALL", "LUXURY", "AI", "CRICKET", "FOREX"}


def test_app_payload_rejects_unknown_asset_from_another_market():
    from mini_app.app_payload import entry_plan

    asset = assets_for(Market.SMARTY)[0]
    result = _result(asset)
    plan = entry_plan(result, 30, 60.0)
    assert plan["ready"] is True
    assert plan["window_seconds"] == 30
    assert plan["valid_until"] is not None
