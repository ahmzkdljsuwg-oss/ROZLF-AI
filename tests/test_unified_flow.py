"""Unified selector + duration flow tests (local logic only, no live Telegram)."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from bot import context
from bot.handlers import menus as handlers
from engines.technical.analyzer import AnalysisResult
from providers.base import DataUnavailable
from providers.catalog import Market, dynamic_asset


def _result(asset, direction="UP", confidence=82.0) -> AnalysisResult:
    return AnalysisResult(
        asset_key=asset.key,
        asset_display=asset.display,
        market=asset.market.value,
        timeframe="1min",
        direction=direction,
        confidence=confidence,
        score_up=3.0,
        score_down=1.0,
        price=1234.5,
        source="eo_bridge",
        generated_at=datetime.now(timezone.utc),
        reasons=["Bullish structure", "EMA confirmation"],
        indicators={"volatility": "NORMAL"},
        trend_summary="BULLISH",
        momentum_strength="STRONG",
        data_confidence={"score": 90, "level": "HIGH"},
        confirmed_strategies=[{"name": "BOS"}],
        invalidation=["Close below structure"],
    )


class FakeMessage:
    def __init__(self):
        self.edits = []

    async def edit_text(self, text, reply_markup=None, **kwargs):
        self.edits.append((text, reply_markup))


class FakeCallback:
    def __init__(self, data, user_id=7):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMessage()
        self.answered = []

    async def answer(self, text="", show_alert=False, **kwargs):
        self.answered.append(text)


class FakeRepo:
    async def get_user_settings(self, user_id, defaults=None):
        return dict(defaults or {"min_confidence": 65.0})


class FakeGenerator:
    def __init__(self, asset, record_id=11, error=None):
        self.asset = asset
        self.record_id = record_id
        self.error = error
        self.calls = []

    async def fetch_and_analyse(self, asset, tf, duration_seconds=None):
        self.calls.append((asset.key, tf))
        if self.error:
            raise self.error
        return SimpleNamespace(), _result(asset)

    async def generate(self, user_id, asset, tf, duration_seconds=None, min_confidence=None):
        self.calls.append((asset.key, tf, duration_seconds))
        if self.error:
            raise self.error
        return _result(asset), SimpleNamespace(
            id=self.record_id,
            direction="UP",
            expiry_seconds=duration_seconds,
            confidence=82.0,
        )

    async def create_signal(self, user_id, result, duration):
        return SimpleNamespace(
            id=self.record_id,
            direction="UP",
            expiry_seconds=duration,
            confidence=result.confidence,
        )


class FakeInventory:
    def __init__(self, assets=None, error=None):
        self.assets_list = assets or []
        self.error = error

    async def assets(self, market, force=False):
        if self.error:
            raise self.error
        return [a for a in self.assets_list if a.market is market]

    async def resolve(self, key):
        return next((a for a in self.assets_list if a.key == key), None)


def _context(monkeypatch, inventory, generator=None):
    monkeypatch.setattr(
        context,
        "_context",
        SimpleNamespace(
            registry=SimpleNamespace(source_summary=lambda asset: "eo_bridge"),
            inventory=inventory,
            generator=generator,
            repo=FakeRepo(),
            settings=SimpleNamespace(min_confidence=65.0),
        ),
        raising=False,
    )


def _ids(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


@pytest.mark.parametrize(
    ("market", "bridge_id", "label"),
    [
        (Market.FOOTBALL, 278, "FOOTBALL INDEX"),
        (Market.AI, 285, "AI INDEX"),
        (Market.LUXURY, 286, "LUXURY INDEX"),
    ],
)
async def test_market_routes_to_the_unified_analysis(monkeypatch, market, bridge_id, label):
    asset = dynamic_asset(f"ASSET_{bridge_id}", market, bridge_id=bridge_id, name=label)
    _context(monkeypatch, FakeInventory([asset]))
    callback = FakeCallback(f"nx:market:{market.value.upper()}")
    await handlers._nexus_analyse(callback, market.value.upper())
    text = callback.message.edits[-1][0]
    assert label in text


async def test_smarty_and_otc_use_the_real_asset_picker(monkeypatch):
    smarty = dynamic_asset("SMRTY", Market.SMARTY, bridge_id=240, name="SMARTY")
    _context(monkeypatch, FakeInventory([smarty]))
    callback = FakeCallback("nx:market:SMARTY")
    await handlers._nexus_assets(callback, "SMARTY", 0)
    text, keyboard = callback.message.edits[0]
    assert "1 أصل نشط" in text
    labels = [b.text for row in keyboard.inline_keyboard for b in row]
    assert any("SMRTY" in label for label in labels)
    assert "nx:pick:SMARTY:0" in _ids(keyboard)
    assert not any(item.startswith("mkt:") for item in _ids(keyboard))


async def test_cricket_comes_from_catalog_not_guessed_id(monkeypatch):
    cricket = dynamic_asset("CRICKET_INDEX_OTC_R", Market.CRICKET, bridge_id=276, name="Cricket Index")
    _context(monkeypatch, FakeInventory([cricket]))
    seen = []

    async def fake_analyse(callback, name, asset_key=None):
        seen.append(name)

    monkeypatch.setattr(handlers, "_nexus_analyse", fake_analyse)
    callback = FakeCallback("nx:market:CRICKET")
    await handlers.cb_nx_market(callback)
    assert seen == ["CRICKET"]


async def test_cricket_unavailable_keeps_market_visible(monkeypatch):
    error = DataUnavailable("CRICKET_UNAVAILABLE", "no active Cricket instrument")
    _context(monkeypatch, FakeInventory(error=error))
    callback = FakeCallback("nx:market:CRICKET")
    await handlers._nexus_analyse(callback, "CRICKET")
    text, keyboard = callback.message.edits[-1]
    assert "DATA UNAVAILABLE" in text
    assert "CRICKET" in text.upper()
    assert "nx:analyse" in _ids(keyboard)


async def test_otc_unavailable_never_substitutes_forex(monkeypatch):
    error = DataUnavailable("OTC_UNAVAILABLE", "no verified OTC feed")
    _context(monkeypatch, FakeInventory(error=error))
    callback = FakeCallback("nx:market:OTC")
    await handlers._nexus_assets(callback, "OTC", 0)
    text, keyboard = callback.message.edits[-1]
    assert "DATA UNAVAILABLE" in text
    assert "EUR/USD" not in text
    assert "nx:analyse" in _ids(keyboard)


def test_markets_hub_uses_only_the_canonical_callbacks():
    data = _ids(handlers.menus.nexus_markets_menu())
    assert "nx:market:FOREX" in data and "nx:market:OTC" in data
    assert all(item.startswith(("nx:market:", "nx:more")) for item in data)


async def test_manual_duration_lists_only_supported_values(monkeypatch):
    asset = dynamic_asset("FOOTBALL_INDEX_OTC_R", Market.FOOTBALL, bridge_id=278, name="Football Index")
    _context(monkeypatch, FakeInventory([asset]))
    callback = FakeCallback(f"dur:manual:{asset.key}")
    await handlers.cb_duration_mode(callback)
    durations = [
        int(b.callback_data.split(":")[2])
        for row in callback.message.edits[0][1].inline_keyboard
        for b in row
        if b.callback_data.startswith("md:")
    ]
    assert durations == [30, 60, 120, 180, 300]
    assert 999 not in durations


async def test_manual_unsupported_duration_is_rejected(monkeypatch):
    asset = dynamic_asset("FOOTBALL_INDEX_OTC_R", Market.FOOTBALL, bridge_id=278, name="Football Index")
    generator = FakeGenerator(asset)
    _context(monkeypatch, FakeInventory([asset]), generator)
    callback = FakeCallback(f"md:{asset.key}:999")
    await handlers.cb_manual_duration(callback)
    assert any("غير مدعومة" in text for text in callback.answered)
    assert generator.calls == []


async def test_manual_duration_runs_analysis_with_chosen_duration(monkeypatch):
    asset = dynamic_asset("FOOTBALL_INDEX_OTC_R", Market.FOOTBALL, bridge_id=278, name="Football Index")
    generator = FakeGenerator(asset)
    _context(monkeypatch, FakeInventory([asset]), generator)
    callback = FakeCallback(f"md:{asset.key}:60")
    await handlers.cb_manual_duration(callback)
    text = callback.message.edits[-1][0]
    assert generator.calls == [(asset.key, "1min", 60)]
    assert "مدة الصفقة" in text and "دقيقة واحدة" in text
    assert "الإشارة: <b>شراء" in text


async def test_auto_duration_chooses_supported_value_and_explains(monkeypatch):
    asset = dynamic_asset("AI_INDEX_OTC_R", Market.AI, bridge_id=285, name="AI Index")
    generator = FakeGenerator(asset)
    _context(monkeypatch, FakeInventory([asset]), generator)
    callback = FakeCallback(f"dur:auto:{asset.key}")
    await handlers.cb_duration_mode(callback)
    text = callback.message.edits[-1][0]
    assert "مدة الصفقة" in text
    assert "قوة الإشارة" in text
    _, _, note = handlers._LAST_ANALYSIS[(callback.from_user.id, asset.key)]
    assert "SMART DURATION" in note
    assert "volatility NORMAL" in note
    assert generator.calls


async def test_auto_duration_no_trade_does_not_create_signal(monkeypatch):
    asset = dynamic_asset("AI_INDEX_OTC_R", Market.AI, bridge_id=285, name="AI Index")
    generator = FakeGenerator(asset)
    generator.fetch_and_analyse = lambda asset, tf, duration_seconds=None: _no_trade(asset)
    _context(monkeypatch, FakeInventory([asset]), generator)
    callback = FakeCallback(f"dur:auto:{asset.key}")
    await handlers.cb_duration_mode(callback)
    text = callback.message.edits[-1][0]
    assert "لا توجد فرصة تداول" in text
    assert "SIGNAL ID" not in text


async def _no_trade(asset):
    return SimpleNamespace(), _result(asset, direction="NO TRADE", confidence=20.0)


async def test_repeated_press_does_not_run_analysis_twice(monkeypatch):
    asset = dynamic_asset("AI_INDEX_OTC_R", Market.AI, bridge_id=285, name="AI Index")
    generator = FakeGenerator(asset)
    _context(monkeypatch, FakeInventory([asset]), generator)
    lock = handlers._analysis_lock(7)
    await lock.acquire()
    try:
        callback = FakeCallback(f"dur:auto:{asset.key}")
        await handlers.cb_duration_mode(callback)
    finally:
        lock.release()
    assert any("قيد التنفيذ" in text for text in callback.answered)
    assert generator.calls == []


async def test_market_data_isolated_between_indices(monkeypatch):
    _context(monkeypatch, FakeInventory([]))
    seen = []

    async def fake_analyse(callback, name, asset_key=None):
        seen.append(name)

    monkeypatch.setattr(handlers, "_nexus_analyse", fake_analyse)
    for market in (Market.FOOTBALL, Market.AI):
        await handlers.cb_nx_market(FakeCallback(f"nx:market:{market.value.upper()}"))
    assert seen == ["FOOTBALL", "AI"]
