import hashlib
import hmac
import json
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.keyboards import menus
from mini_app import api
from mini_app.auth import telegram_user
from providers.base import DataUnavailable
from providers.catalog import Market, dynamic_asset
from providers.registry import DataSourceRegistry
from tests.conftest import FakeProvider, make_candles


def signed(token, *, uid=42, age=0, signature="ed25519-field-is-included"):
    parts = {"user": json.dumps({"id": uid}), "auth_date": str(int(time.time()) - age), "signature": signature}
    plaintext = "\n".join(f"{k}={v}" for k, v in sorted(parts.items()))
    key = hmac.digest(b"WebAppData", token.encode(), hashlib.sha256)
    return urlencode({**parts, "hash": hmac.new(key, plaintext.encode(), hashlib.sha256).hexdigest()})


def test_telegram_binding_rejects_expired_tampered_and_duplicate(settings):
    token = settings.telegram_bot_token
    raw = signed(token)
    assert telegram_user(raw, token) == 42
    for bad in (signed(token, age=21601), raw + "&auth_date=1", raw.replace("ed25519-field", "modified-field")):
        with pytest.raises(ValueError):
            telegram_user(bad, token)


def test_button_only_adds_mini_app_in_private_chat(settings, monkeypatch):
    configured = replace(settings, port=8080, mini_app_url="https://bot.example/")
    monkeypatch.setattr(menus, "settings", configured)
    private = menus.nexus_home_menu(SimpleNamespace(type="private")).inline_keyboard
    group = menus.nexus_home_menu(SimpleNamespace(type="group")).inline_keyboard
    assert private[0][0].callback_data == group[0][0].callback_data == "nx:analyse"
    assert private[1][0].web_app.url == "https://bot.example/mini-app/"
    assert len(group) == 1
    assert replace(configured, mini_app_url="http://bot.example").mini_app_link is None
    assert replace(configured, mini_app_url="https://user@bot.example").mini_app_link is None


class Feed(FakeProvider):
    markets = frozenset({Market.FOREX, Market.SMARTY, Market.OTC})

    def __init__(self):
        super().__init__()
        self.calls = []
        self.old = False

    async def fetch_candles(self, asset, tf, limit=300):
        self.calls.append((asset.key, tf.code))
        if tf.code == "5sec":
            raise DataUnavailable("EMPTY", "exact 5s bars not served")
        now = api.utc_now()
        delay = tf.seconds * (4 if self.old else 1) + 1
        return make_candles(n=250, tf_seconds=tf.seconds, end=now - timedelta(seconds=delay))

    async def fetch_quote(self, asset):
        pytest.fail("next candle analysis must not wait for a quote")


class Inventory:
    async def assets(self, market):
        return {
            Market.SMARTY: [dynamic_asset("SMRTY", market, bridge_id=240)],
            Market.OTC: [dynamic_asset("USDNGN_OTC_R", market, bridge_id=559)],
        }.get(market, [])


@pytest.mark.asyncio
async def test_mini_api_real_analyzer_and_modes(settings, monkeypatch):
    from engines.technical import next_candle

    monkeypatch.setattr(next_candle, "load_calibration", lambda: {})
    now = datetime(2026, 11, 17, 13, 0, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(api, "utc_now", lambda: now)
    feed = Feed()
    registry = DataSourceRegistry([feed], cache_ttl=0, clock=lambda: now)
    ctx = SimpleNamespace(registry=registry, inventory=Inventory())
    settings = replace(settings, subscriptions_enabled=False)
    app = web.Application()
    api.install(app, settings, lambda: ctx)
    async with TestClient(TestServer(app)) as client:
        path = "/api/nexus-mini/v1/"
        auth = {"X-Telegram-Init-Data": signed(settings.telegram_bot_token)}
        wrong_user = {"X-Telegram-Init-Data": signed(settings.telegram_bot_token, uid=43)}
        page = await client.get("/mini-app/")
        assert page.status == 200 and "تحليل سريع" in await page.text()
        assert "Content-Security-Policy" in page.headers
        assert (await client.get(path + "markets")).status == 401
        assert (await client.get(path + "markets", headers=wrong_user)).status == 403
        response = await client.get(path + "markets", headers=auth)
        assert {m["key"] for m in (await response.json())["markets"]} == {"forex", "otc", "smarty"}
        assert feed.calls == []
        assert (await client.post(path + "analyze", headers=auth, json={
            "market": "otc", "asset": "EUR_USD_FOREX", "mode": "fast"
        })).status == 404

        response = await client.post(path + "analyze", headers=auth, json={
            "market": "smarty", "asset": "SMARTY_240", "mode": "fast"
        })
        fast = await response.json()
        assert response.status == 200, fast
        assert feed.calls[:2] == [("SMARTY_240", "5sec"), ("SMARTY_240", "15sec")]
        assert fast["frame"] == "15sec" and fast["direction"] == "UP"
        assert fast["confidence"] is None and fast["target_ms"] > fast["server_ms"]
        assert fast["target_ms"] == fast["candles"][-1]["at"] + 2 * 15000
        assert fast["end_ms"] - fast["target_ms"] == 15000
        assert all(c["at"] + 15000 <= fast["server_ms"] for c in fast["candles"])

        response = await client.post(path + "analyze", headers=auth, json={
            "market": "forex", "asset": "GBP_JPY_FOREX", "mode": "minute"
        })
        precise = await response.json()
        assert response.status == 200 and precise["direction"] == "NO TRADE"
        assert precise["frame"] == "1min" and precise["target_ms"] is None
        assert feed.calls[-1] == ("GBP_JPY_FOREX", "1min")

        feed.old = True
        response = await client.post(path + "analyze", headers=auth, json={
            "market": "otc", "asset": "OTC_559", "mode": "fast"
        })
        assert response.status == 503 and (await response.json())["code"] == "DATA_UNAVAILABLE"


@pytest.mark.asyncio
async def test_existing_subscription_gate_applies_in_webapp(settings):
    settings = replace(settings, subscriptions_enabled=True)
    async def no_subscription(_):
        return False
    ctx = SimpleNamespace(repo=SimpleNamespace(is_subscribed=no_subscription))
    app = web.Application()
    api.install(app, settings, lambda: ctx)
    async with TestClient(TestServer(app)) as client:
        auth = {"X-Telegram-Init-Data": signed(settings.telegram_bot_token)}
        assert (await client.get("/api/nexus-mini/v1/markets", headers=auth)).status == 403


@pytest.mark.asyncio
async def test_signal_is_withheld_if_processing_uses_up_the_candle_window(monkeypatch):
    from providers.catalog import assets_for

    now = datetime(2026, 11, 17, 13, 0, 1, tzinfo=timezone.utc)
    clock = [now]
    monkeypatch.setattr(api, "utc_now", lambda: clock[0])
    real_analyzer = api.analyze_market_data

    def slow_result(*args):
        result = real_analyzer(*args)
        assert result.direction == "UP"
        clock[0] = result.target_open_at - timedelta(milliseconds=300)
        return result

    monkeypatch.setattr(api, "analyze_market_data", slow_result)
    registry = DataSourceRegistry([Feed()], cache_ttl=0, clock=lambda: now)
    result = await api._analyze_frame(registry, assets_for(Market.FOREX)[0], "1min", "fast")
    assert result["direction"] == "NO TRADE"
    assert result["target_ms"] is None and result["confidence"] is None


@pytest.mark.asyncio
async def test_expired_registry_snapshot_refreshes_same_asset_without_quote(monkeypatch):
    from providers.catalog import assets_for

    clock = [datetime(2026, 11, 17, 13, 0, 1, tzinfo=timezone.utc)]
    monkeypatch.setattr(api, "utc_now", lambda: clock[0])
    feed = Feed()
    registry = DataSourceRegistry([feed], cache_ttl=6, clock=lambda: clock[0])
    asset = assets_for(Market.FOREX)[0]
    await registry.fetch(asset, "1min", with_quote=False)
    clock[0] += timedelta(seconds=60)
    result = await api._analyze_frame(registry, asset, "1min", "fast")
    assert feed.calls == [(asset.key, "1min"), (asset.key, "1min")]
    assert result["data_issue"] is None
    assert result["last_closed_ms"] == api._ms(clock[0] - timedelta(seconds=1))


@pytest.mark.asyncio
async def test_short_genuine_history_is_chart_only(monkeypatch):
    from providers.catalog import assets_for

    now = datetime(2026, 11, 17, 13, 0, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(api, "utc_now", lambda: now)

    class Short(Feed):
        async def fetch_candles(self, asset, tf, limit=300):
            return make_candles(n=135, tf_seconds=tf.seconds, end=now - timedelta(seconds=tf.seconds + 1))

    def forecast(*_):
        pytest.fail("short history must not run a forecast")

    monkeypatch.setattr(api, "analyze_market_data", forecast)
    registry = DataSourceRegistry([Short()], cache_ttl=0, clock=lambda: now)
    result = await api._analyze_frame(registry, assets_for(Market.FOREX)[0], "1min", "fast")
    assert result["data_issue"] == "SHORT_HISTORY"
    assert result["closed_count"] == 135 and len(result["candles"]) == 40
    assert result["direction"] == "NO TRADE"
    assert result["target_ms"] is None and result["confidence"] is None


@pytest.mark.asyncio
async def test_slow_candle_source_no_longer_capped_at_six_seconds(monkeypatch):
    import asyncio
    from providers.catalog import assets_for

    now = datetime(2026, 11, 17, 13, 0, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(api, "utc_now", lambda: now)
    assert api.FRAME_BUDGET["1min"] >= 16
    real_wait_for = asyncio.wait_for

    async def scaled_wait_for(task, timeout):
        return await real_wait_for(task, timeout / 50)

    monkeypatch.setattr(api.asyncio, "wait_for", scaled_wait_for)

    class Slow(Feed):
        async def fetch_candles(self, asset, tf, limit=300):
            await asyncio.sleep(8 / 50)
            return await super().fetch_candles(asset, tf, limit)

    registry = DataSourceRegistry([Slow()], cache_ttl=0, clock=lambda: now)
    outcome = await api._analyze_frame(registry, assets_for(Market.FOREX)[0], "1min", "fast")
    assert outcome["closed_count"] == 250 and outcome["data_issue"] is None


@pytest.mark.asyncio
async def test_forex_rate_limit_is_reported_as_such(settings, monkeypatch):
    from providers.catalog import assets_for

    class Quota(Feed):
        async def fetch_candles(self, asset, tf, limit=300):
            raise DataUnavailable("RATE_LIMITED", "quota exhausted")

    registry = DataSourceRegistry([Quota()], cache_ttl=0)
    ctx = SimpleNamespace(registry=registry, inventory=None)
    settings = replace(settings, subscriptions_enabled=False)
    app = web.Application()
    api.install(app, settings, lambda: ctx)
    async with TestClient(TestServer(app)) as client:
        auth = {"X-Telegram-Init-Data": signed(settings.telegram_bot_token)}
        response = await client.post("/api/nexus-mini/v1/analyze", headers=auth, json={
            "market": "forex", "asset": assets_for(Market.FOREX)[0].key, "mode": "fast",
        })
        assert response.status == 503
        error = await response.json()
        assert error["reason"] == "RATE_LIMITED" and "حد الطلبات" in error["message"]
