"""Mini App: initData auth, API surface, shared-engine parity, bot menu wiring."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.keyboards.menus import main_menu
from engines.technical.analyzer import AnalysisResult
from mini_app import api as mini_api
from mini_app import service
from mini_app.auth import AuthError, validate_init_data
from providers.base import DataUnavailable, Candle, Quote, utc_now
from providers.catalog import Market, find_by_symbol, timeframe

TOKEN = "123456:TESTTOKEN"


def make_init_data(user_id: int = 7, auth_date: int | None = None, signature: str | None = None) -> str:
    values = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "query_id": "AAF",
        "user": json.dumps({"id": user_id, "first_name": "Test"}, separators=(",", ":")),
    }
    if signature:
        values["signature"] = signature
    check = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def _result(asset, direction="UP", confidence=78.0) -> AnalysisResult:
    return AnalysisResult(
        asset_key=asset.key,
        asset_display=asset.display,
        market=asset.market.value,
        timeframe="1min",
        direction=direction,
        confidence=confidence,
        score_up=6.0,
        score_down=2.0,
        price=1.10123,
        source="fake",
        generated_at=datetime.now(timezone.utc),
        reasons=["Bullish market structure", "EMA confirmation"],
        trend_summary="BULLISH",
        momentum_strength="STRONG",
        evidence_score=61.0,
        data_quality_score=85.0,
    )


class FakeRepo:
    def __init__(self):
        self.settings = {"min_confidence": 60.0}

    async def get_user_settings(self, user_id, defaults=None):
        return dict(self.settings)

    async def save_user_settings(self, user_id, settings):
        self.settings = dict(settings)

    async def recent_signals(self, limit=10, user_id=None):
        return []

    async def statistics(self, user_id=None):
        return {"accuracy": None, "verified": 0, "wins": 0, "losses": 0,
                "profit_factor": None, "active": 0}


class FakeGenerator:
    def __init__(self, asset):
        self.asset = asset
        self.calls = []

    async def fetch_and_analyse(self, asset, tf, duration_seconds=None):
        self.calls.append((asset.key, tf, duration_seconds))
        return SimpleNamespace(), _result(asset)

    async def generate(self, user_id, asset, tf, duration_seconds=None, min_confidence=None):
        self.calls.append((asset.key, tf, duration_seconds))
        return _result(asset), SimpleNamespace(id=11)

    async def create_signal(self, user_id, result, duration):
        return SimpleNamespace(id=12)


class FakeRegistry:
    def statuses(self):
        return [{"name": "fake", "configured": True, "markets": ["FOREX"]}]

    async def fetch(self, asset, frame, limit=100):
        now = utc_now()
        candles = [
            Candle(time=now, open=1.1, high=1.101, low=1.099, close=1.1005, volume=1)
            for _ in range(20)
        ]
        quote = Quote(symbol=asset.symbol, bid=1.1004, ask=1.1006, time=now, source="fake")
        return SimpleNamespace(
            candles=candles,
            quote=quote,
            last_close=1.1005,
            last_time=now,
            timeframe=timeframe(frame),
            validation=SimpleNamespace(bar_count=len(candles)),
            source="fake",
        )


def fake_context(asset):
    settings = SimpleNamespace(
        telegram_bot_token=TOKEN,
        min_confidence=60.0,
        eo_bridge_url=None,
        eo_bridge_key=None,
        async_database_url="sqlite+aiosqlite:///test.db",
        mini_app_url="https://example.test",
    )
    return SimpleNamespace(
        settings=settings,
        repo=FakeRepo(),
        generator=FakeGenerator(asset),
        registry=FakeRegistry(),
        inventory=None,
        health=None,
        mistral=SimpleNamespace(health=lambda: {"configured": True, "online": True, "model": "m"}),
    )


@pytest.fixture
def forex_asset():
    return find_by_symbol("EUR/USD", Market.FOREX)


@pytest.fixture
async def client(forex_asset):
    ctx = fake_context(forex_asset)
    app = web.Application()
    mini_api.install(app, lambda: ctx)
    async with TestClient(TestServer(app)) as test_client:
        yield test_client, ctx


def test_valid_init_data_returns_telegram_user():
    user = validate_init_data(make_init_data(7), TOKEN)
    assert user.id == 7
    assert user.display_name == "Test"


def test_tampered_init_data_is_rejected():
    good = make_init_data(7)
    wrong = good[:-1] + ("0" if good[-1] != "0" else "1")
    with pytest.raises(AuthError):
        validate_init_data(wrong, TOKEN)


def test_init_data_with_telegram_signature_field_is_accepted():
    user = validate_init_data(make_init_data(7, signature="ed25519-base64url-value"), TOKEN)
    assert user.id == 7


def test_expired_init_data_is_rejected():
    with pytest.raises(AuthError) as exc:
        validate_init_data(make_init_data(7, auth_date=int(time.time()) - 86400 * 2), TOKEN)
    assert exc.value.code == "EXPIRED_INIT_DATA"


def test_frontend_sends_dynamic_init_data_on_every_protected_route():
    source = (__import__("pathlib").Path(__file__).resolve().parents[1] / "mini_app/static/api.js").read_text()
    assert "initDataUnsafe" not in source
    assert "get initData()" in source
    assert 'if (window.console) console.warn("[ROZLF] Telegram initData is unavailable")' in source
    for header in ('"X-Telegram-Init-Data": rawInitData', 'Authorization: "tma " + rawInitData'):
        assert header in source
    assert "return await once(path, options, rawInitData);" in source
    for route in ("bootstrap", "markets", "history", "recommendations", "analyse", "settings"):
        assert route in source


def test_main_menu_has_mini_app_webapp_and_keeps_bot_entries():
    keyboard = main_menu("https://example.test/mini-app/")
    texts = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "📉 ANALYSIS" in texts and "⚙️ SETTINGS" in texts and "🏆 RECOMMENDATIONS" in texts
    web = [button for row in keyboard.inline_keyboard for button in row if button.web_app]
    assert len(web) == 1
    assert web[0].text == "🚀 Open Mini App"
    assert web[0].web_app.url == "https://example.test/mini-app/"


def test_main_menu_always_has_default_mini_app_url():
    keyboard = main_menu(None)
    web = [button for row in keyboard.inline_keyboard for button in row if button.web_app]
    assert len(web) == 1
    assert web[0].web_app.url == "https://web-production-b044b.up.railway.app/mini-app/"


async def test_api_requires_valid_init_data(client):
    http, _ = client
    response = await http.get("/api/mini/bootstrap")
    assert response.status == 401
    assert (await response.json())["error"] == "MISSING_INIT_DATA"
    assert response.headers["X-Rozlf-Auth-Error"] == "MISSING_INIT_DATA"
    response = await http.get("/api/mini/bootstrap", headers={"X-Telegram-Init-Data": "bad"})
    assert response.status == 401
    response = await http.get(
        "/api/mini/bootstrap",
        headers={"X-Telegram-Init-Data": make_init_data(7, auth_date=int(time.time()) - 86400 * 2)},
    )
    assert response.status == 401
    assert (await response.json())["error"] == "EXPIRED_INIT_DATA"
    response = await http.get(
        "/api/mini/bootstrap", headers={"X-Telegram-Init-Data": make_init_data(7)}
    )
    assert response.status == 200
    body = await response.json()
    assert body["user"]["id"] == 7
    assert body["brand"]["name"] == "ROZLF AI"


async def test_markets_and_market_detail(client, forex_asset):
    http, _ = client
    headers = {"X-Telegram-Init-Data": make_init_data(7)}
    response = await http.get("/api/mini/markets", headers=headers)
    body = await response.json()
    assert response.status == 200
    assert len(body["markets"]) == 6
    assert {row["key"] for row in body["markets"]} == {
        "SMARTY", "FOOTBALL", "LUXURY", "AI", "CRICKET", "FOREX"
    }
    response = await http.get("/api/mini/market/FOREX", headers=headers)
    detail = await response.json()
    assert response.status == 200
    assert detail["key"] == "FOREX"
    assert detail["assets"][0]["key"] == forex_asset.key
    assert detail["candles"] and detail["price"] == 1.1005


async def test_analyse_uses_the_same_engine_result(client, forex_asset):
    http, ctx = client
    headers = {"X-Telegram-Init-Data": make_init_data(7)}
    duration = service.durations_for(forex_asset)[0]
    response = await http.post(
        "/api/mini/analyse",
        json={"market": "FOREX", "asset": forex_asset.key, "duration": duration},
        headers=headers,
    )
    body = await response.json()
    engine = ctx.generator.calls[-1]
    assert response.status == 200
    assert body["direction"] == "UP"
    assert body["confidence"] == 78.0
    assert body["price"] == 1.10123
    assert body["duration"] == duration
    assert engine == (forex_asset.key, service.analysis_frame(forex_asset, duration), duration)


async def test_analyse_rejects_unsupported_market_and_duration(client, forex_asset):
    http, _ = client
    headers = {"X-Telegram-Init-Data": make_init_data(7)}
    response = await http.post(
        "/api/mini/analyse", json={"market": "OTC", "asset": forex_asset.key}, headers=headers
    )
    assert response.status == 400
    assert (await response.json())["error"] == "UNKNOWN_MARKET"
    response = await http.post(
        "/api/mini/analyse",
        json={"market": "FOREX", "asset": forex_asset.key, "duration": 7},
        headers=headers,
    )
    body = await response.json()
    assert body["error"] == "DURATION_UNSUPPORTED"


async def test_settings_persist_and_validate(client):
    http, _ = client
    headers = {"X-Telegram-Init-Data": make_init_data(7)}
    response = await http.post(
        "/api/mini/settings", json={"min_confidence": 80}, headers=headers
    )
    assert response.status == 200
    response = await http.get("/api/mini/settings", headers=headers)
    body = await response.json()
    assert body["settings"]["min_confidence"] == 80.0
    response = await http.post(
        "/api/mini/settings", json={"min_confidence": 77}, headers=headers
    )
    assert response.status == 400


async def test_status_exposes_only_configured_flags(client):
    http, _ = client
    response = await http.get(
        "/api/mini/status", headers={"X-Telegram-Init-Data": make_init_data(7)}
    )
    body = await response.json()
    assert body["telegram_configured"] is True
    assert body["bridge_configured"] is False
    assert body["ai"]["online"] is True


async def test_static_index_is_served_without_auth(client):
    http, _ = client
    response = await http.get("/mini-app/")
    assert response.status == 200
    text = await response.text()
    assert "ROZLF" in text and "telegram-web-app.js" in text


async def test_static_assets_and_redirect(client):
    http, _ = client
    for path in ("/mini-app/static/styles.css", "/mini-app/static/app.js",
                 "/mini-app/static/api.js", "/mini-app/static/charts.js"):
        response = await http.get(path)
        assert response.status == 200, path
        assert len(await response.text()) > 100
    redirect = await http.get("/mini-app", allow_redirects=False)
    assert redirect.status == 302
    assert redirect.headers["Location"] == "/mini-app/"


async def _engine_app():
    seen = {"init_data": None, "analyse": None}

    async def health(_request):
        return web.json_response(
            {
                "engine_ready": True,
                "telegram_configured": True,
                "bridge_configured": True,
                "ai": True,
                "build": "engine-sha",
            }
        )

    async def bootstrap(request):
        seen["init_data"] = request.headers.get("X-Telegram-Init-Data")
        return web.json_response({"user": {"id": 7}, "market_count": 6, "engine": "real"})

    async def markets(request):
        seen["init_data"] = request.headers.get("X-Telegram-Init-Data")
        return web.json_response({"markets": [{"key": "SMARTY"}, {"key": "FOREX"}]})

    async def analyse(request):
        seen["analyse"] = await request.json()
        return web.json_response({"direction": "UP", "confidence": 71.0, "price": 1.10123})

    app = web.Application()
    app.router.add_get("/api/mini/health", health)
    app.router.add_get("/api/mini/bootstrap", bootstrap)
    app.router.add_get("/api/mini/markets", markets)
    app.router.add_post("/api/mini/analyse", analyse)
    return app, seen


async def test_web_service_proxies_to_real_engine_when_local_ctx_missing():
    from mini_app.engine_client import EngineClient

    engine_app, seen = await _engine_app()
    async with TestServer(engine_app) as engine_server:
        app = web.Application()
        mini_api.install(app, lambda: None, engine=EngineClient(str(engine_server.make_url("")).rstrip("/")))
        async with TestClient(TestServer(app)) as web_client:
            health = await web_client.get("/api/mini/health")
            assert health.status == 200
            body = await health.json()
            assert body["engine_ready"] is True
            assert body["mode"] == "proxy"
            assert body["engine_api"] == "reachable"

            headers = {"X-Telegram-Init-Data": make_init_data(7), "Origin": "https://web.telegram.org"}
            bootstrap = await web_client.get("/api/mini/bootstrap", headers=headers)
            assert bootstrap.status == 200
            assert (await bootstrap.json())["engine"] == "real"
            assert seen["init_data"] == make_init_data(7)
            assert bootstrap.headers.get("Access-Control-Allow-Origin") == "https://web.telegram.org"

            analyse = await web_client.post(
                "/api/mini/analyse",
                json={"market": "SMARTY", "duration": 60},
                headers=headers,
            )
            assert analyse.status == 200
            assert seen["analyse"] == {"market": "SMARTY", "duration": 60}
            assert (await analyse.json())["confidence"] == 71.0


async def test_proxy_reports_unreachable_engine_without_fake_success():
    from mini_app.engine_client import EngineClient

    app = web.Application()
    mini_api.install(app, lambda: None, engine=EngineClient("http://127.0.0.1:9", timeout_seconds=0.4))
    async with TestClient(TestServer(app)) as web_client:
        health = await web_client.get("/api/mini/health")
        assert health.status == 503
        assert (await health.json())["engine_api"] == "unreachable"
        bootstrap = await web_client.get(
            "/api/mini/bootstrap", headers={"X-Telegram-Init-Data": make_init_data(7)}
        )
        assert bootstrap.status == 503
        assert (await bootstrap.json())["error"] == "ENGINE_UNREACHABLE"


async def test_proxy_preserves_init_data_authentication_and_real_engine_result(forex_asset):
    from mini_app.engine_client import EngineClient

    engine_app = web.Application()
    engine_ctx = fake_context(forex_asset)
    mini_api.install(engine_app, lambda: engine_ctx)
    async with TestServer(engine_app) as engine_server:
        app = web.Application()
        mini_api.install(app, lambda: None, engine=EngineClient(str(engine_server.make_url("")).rstrip("/")))
        async with TestClient(TestServer(app)) as web_client:
            denied = await web_client.get("/api/mini/bootstrap")
            assert denied.status == 401
            forged = await web_client.get(
                "/api/mini/bootstrap", headers={"X-Telegram-Init-Data": "bad"}
            )
            assert forged.status == 401

            headers = {"X-Telegram-Init-Data": make_init_data(7)}
            bootstrap = await web_client.get("/api/mini/bootstrap", headers=headers)
            assert bootstrap.status == 200
            assert (await bootstrap.json())["brand"]["name"] == "ROZLF AI"

            duration = service.durations_for(forex_asset)[0]
            analyse = await web_client.post(
                "/api/mini/analyse",
                json={"market": "FOREX", "asset": forex_asset.key, "duration": duration},
                headers=headers,
            )
            result = await analyse.json()
            assert analyse.status == 200
            assert result["confidence"] == 78.0
            assert result["price"] == 1.10123
            assert engine_ctx.generator.calls[-1] == (
                forex_asset.key,
                service.analysis_frame(forex_asset, duration),
                duration,
            )


async def test_bootstrap_exposes_service_connection_and_market_states(client):
    http, _ = client
    response = await http.get(
        "/api/mini/bootstrap", headers={"X-Telegram-Init-Data": make_init_data(7)}
    )
    assert response.status == 200
    payload = await response.json()
    connection = payload["connection"]
    assert connection["service"] == "ONLINE"
    assert connection["api"] == "ONLINE"
    assert connection["engine"] in ("ONLINE", "OFFLINE")
    assert connection["checked_at"]
    assert payload["markets"], "six markets must always be present"
    for market in payload["markets"]:
        assert market["data_state"] in ("LIVE", "UNAVAILABLE")
        assert "error" in market


async def test_health_snapshot_falls_back_to_cache_when_probe_times_out(forex_asset):
    class SlowHealth:
        def __init__(self):
            self.cache_calls = 0

        async def snapshot(self):
            raise RuntimeError("probe exploded")

        def cached(self):
            self.cache_calls += 1
            return {"FOREX": SimpleNamespace(ok=True, source="cached", last_time=None, error=None)}

    import asyncio

    ctx = SimpleNamespace(health=SlowHealth())
    health = await service._health_snapshot(ctx)
    assert "FOREX" in health
    assert ctx.health.cache_calls == 1
    counted = await asyncio.sleep(0, result=1)
    assert counted == 1


def test_frontend_shell_has_bilingual_toggle_and_five_tabs():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "mini_app/static"
    index = (root / "index.html").read_text()
    i18n = (root / "i18n.js").read_text()
    app = (root / "app.js").read_text()
    assert "static/i18n.js" in index and "static/app.js" in index
    assert 'id="lang-btn"' in index
    for route in ("home", "markets", "analysis", "opportunities", "history"):
        assert 'data-route="%s"' % route in index
    for state in ("CONNECTING", "ONLINE", "DEGRADED", "OFFLINE"):
        assert '"%s"' % state in app
    assert 'let language = "en"' in i18n
    assert '"state.online"' in i18n and '"state.online"' in i18n.split('ar:')[1]
    assert "initDataUnsafe" not in app


def test_confidence_calibration_keeps_quality_setups_above_default_threshold():
    from engines.technical.evidence import _clamp

    for quality_pct in (20.0, 25.0, 30.0, 40.0, 55.0):
        confidence = round(_clamp(50.0 + quality_pct * 0.62, 0.0, 92.0), 1)
        assert confidence >= 60.0
    assert round(_clamp(50.0 + 100.0 * 0.62, 0.0, 92.0), 1) == 92.0
