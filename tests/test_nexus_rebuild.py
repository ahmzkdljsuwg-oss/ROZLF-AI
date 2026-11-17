"""Integration protections for the original NEXUS Telegram application."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from dataclasses import replace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from engines.technical.analyzer import analyze_market_data
from mini_app import api
from providers.base import DataUnavailable
from providers.catalog import Market, timeframe
from providers.registry import DataSourceRegistry
from services.signal_tracker import SignalTracker
from tests.conftest import FakeProvider, make_candles
from tests.test_nexus_mini import Inventory, signed


@pytest.mark.asyncio
async def test_one_history_request_when_a_fast_waiter_cancels(eurusd):
    now = datetime(2026, 11, 17, 18, 0, 3, tzinfo=timezone.utc)
    started, ready = asyncio.Event(), asyncio.Event()

    class SlowProvider(FakeProvider):
        count = 0
        async def fetch_candles(self, *args, **kwargs):
            self.count += 1
            started.set()
            await ready.wait()
            return await super().fetch_candles(*args, **kwargs)

    provider = SlowProvider(make_candles(n=240, tf_seconds=60, end=now-timedelta(seconds=63)))
    registry = DataSourceRegistry([provider], clock=lambda: now)
    first = asyncio.create_task(registry.fetch(eurusd, "1min", with_quote=False))
    await started.wait()
    second = asyncio.create_task(registry.fetch(eurusd, "1min", with_quote=False))
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    ready.set()
    data = await second
    assert data is await registry.fetch(eurusd, "1min", with_quote=False)
    assert provider.count == 1
    assert registry.market_readiness(Market.FOREX)["state"] == "online"
    assert registry.latency()["fake"]["n"] == 1


@pytest.mark.asyncio
async def test_fast_verifies_closed_only_and_pro_fails_closed(eurusd, monkeypatch):
    from engines.technical import next_candle

    now = datetime(2026, 11, 17, 18, 0, 3, tzinfo=timezone.utc)
    candles = make_candles(n=250, tf_seconds=60, end=now-timedelta(seconds=3))
    registry = DataSourceRegistry([FakeProvider(candles)], clock=lambda: now)
    data = await registry.fetch(eurusd, "1min", with_quote=False)
    quick = analyze_market_data(data, now, analysis_mode="fast")
    assert quick.closed_candles == len(candles) - 1
    assert not quick.confidence_verified
    assert quick.target_open_at == now + timedelta(seconds=57)
    with pytest.raises(DataUnavailable, match="متأخرة"):
        analyze_market_data(data, now + timedelta(seconds=59), analysis_mode="fast")
    monkeypatch.setattr(next_candle, "load_calibration", lambda: {
        "markets": {"global": {"1min": {"enabled": True,
            "bins": [{"low": 0, "high": 100, "n": 100, "up_wins": 99}]}}}})
    pro = analyze_market_data(data, now, analysis_mode="pro")
    assert pro.direction == "NO TRADE" and not pro.confidence_verified


@pytest.mark.asyncio
async def test_same_source_exact_target_candle_and_only_acknowledged_stats(repo, eurusd):
    opened = datetime(2026, 11, 17, 18, 0, tzinfo=timezone.utc)
    closed = opened + timedelta(seconds=65)
    tf = timeframe("1min")
    bars = make_candles(n=250, tf_seconds=60, end=opened)
    registry = DataSourceRegistry([FakeProvider(bars)], clock=lambda: closed)
    tracker = SignalTracker(repo, registry)

    async def save(uid, delivered=None, source="Fake Feed"):
        return await repo.add_signal(uid, eurusd.key, eurusd.display, "forex", tf.code,
             "UP", 0.0, 1, source, [], [], 60, opened - timedelta(seconds=15),
             target_open_at=opened, delivered_at=delivered, analysis_mode="fast")

    ok = await save(42, opened - timedelta(seconds=2))
    never_sent = await save(43)
    await save(44, opened - timedelta(seconds=2), "Another feed")
    assert not await repo.mark_candle_delivery(never_sent.id, opened)
    assert await tracker.verify_due(closed) == 2
    [row] = await repo.recent_signals(user_id=42)
    assert row.id == ok.id and row.status == "WIN"
    assert row.close_price == bars[-1].close and row.entry_price == bars[-1].open
    [stat] = await repo.candle_statistics(42)
    assert stat["decided"] == 1 and stat["accuracy"] == 100.0
    assert not await repo.candle_statistics(43)
    [unresolved] = await repo.candle_statistics(44)
    assert unresolved["accuracy"] is None


@pytest.mark.asyncio
async def test_signed_dashboard_preferences_seven_markets_and_native_frame(settings, repo):
    settings = replace(settings, subscriptions_enabled=False, telegram_chat_id=None)
    ctx = SimpleNamespace(repo=repo, registry=DataSourceRegistry([FakeProvider()]), inventory=Inventory(), scanner=None)
    app = web.Application()
    api.install(app, settings, lambda: ctx)
    path = "/api/nexus-mini/v1/"
    async with TestClient(TestServer(app)) as client:
        assert (await client.get(path+"dashboard")).status == 401
        headers = {"X-Telegram-Init-Data": signed(settings.telegram_bot_token)}
        body = await (await client.get(path+"dashboard", headers=headers)).json()
        assert {"smarty","football","luxury","ai","cricket","forex","otc"} <= {m["key"] for m in body["markets"]}
        assert all(m["state"] == "unchecked" for m in body["markets"])
        assert body["signals"] == [] and not body["scanner"]["enabled"]
        assert (await client.post(path+"preferences", headers=headers, json={"scanner": "true"})).status == 400
        assert (await client.post(path+"preferences", headers=headers, json={"scanner":True,"mode":"pro"})).status == 200
        assert await repo.scanner_opt_in(42) and not await repo.scanner_opt_in(43)
        assert await repo.get_analysis_mode(42) == "pro"
        response = await client.post(path+"analyze", headers=headers, json={
            "market":"forex","asset":"EUR_USD_FOREX","mode":"fast","frame":"5sec"})
        assert response.status == 400 and (await response.json())["code"] == "FRAME_UNSUPPORTED"


def test_walk_forward_cannot_train_on_overlapping_future_labels():
    from scripts.backtest_next_candle import _walk_forward

    start = datetime(2026, 11, 17, 18, 0, tzinfo=timezone.utc)
    overdue = (start + timedelta(hours=1)).isoformat()
    rows = [{"time": (start+timedelta(seconds=i)).isoformat(), "settled_at": overdue,
             "score": 8, "target": "UP"} for i in range(330)]
    rows.append({**rows[-1], "time": (start+timedelta(hours=2)).isoformat()})
    _, results = _walk_forward(rows)
    assert all(r["prediction"] == "NO TRADE" for r in results[:-1])
    assert results[-1]["prediction"] == "UP"


@pytest.mark.asyncio
async def test_normal_forex_fallback_rejects_otc_and_wrong_duration(eurusd):
    from providers.eobridge import ExpertOptionBridgeProvider, ExpertOptionForexProvider
    async def get(_path, _params):
        return {"market": "forex", "symbol": "EUR/USD", "eo_symbol": "EURUSD_OTC",
                "source": "ExpertOption", "timeframe": "5min"}
    provider = ExpertOptionForexProvider(SimpleNamespace(
        configured=True, _get=get, _check_market=ExpertOptionBridgeProvider._check_market))
    with pytest.raises(DataUnavailable, match="exact instrument"):
        await provider.fetch_candles(eurusd, timeframe("1min"))


@pytest.mark.asyncio
async def test_telegram_scan_panel_uses_personal_preference_and_hides_owner_controls(settings, repo, monkeypatch):
    from bot.handlers import menus

    scanner = SimpleNamespace(running=True, last_run=None, market_selection=lambda: ["OTC", "SMARTY"])
    monkeypatch.setattr(menus, "get_context", lambda: SimpleNamespace(scanner=scanner, repo=repo, settings=settings))
    answers = []
    async def answer(text, reply_markup):
        answers.append((text, [b.callback_data for row in reply_markup.inline_keyboard for b in row]))
    msg = SimpleNamespace(from_user=SimpleNamespace(id=42), answer=answer)
    await menus.cmd_scan(msg)
    assert "متوقفة" in answers[0][0] and "scan:toggle" in answers[0][1]
    assert not any(item.startswith("scan:mk:") for item in answers[0][1])
    await repo.set_scanner_opt_in(42, True)
    await menus.cmd_scan(msg)
    assert "مفعّلة" in answers[1][0]
