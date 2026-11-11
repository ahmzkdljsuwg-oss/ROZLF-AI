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

    async def fetch_and_analyse(self, asset, tf):
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
        (Market.SMARTY, 240, "SMARTY"),
        (Market.AI, 285, "AI INDEX"),
        (Market.LUXURY, 286, "LUXURY INDEX"),
    ],
)
async def test_market_routes_to_real_asset_id(monkeypatch, market, bridge_id, label):
    asset = dynamic_asset(f"ASSET_{bridge_id}", market, bridge_id=bridge_id, name=label)
    _context(monkeypatch, FakeInventory([asset]))
    callback = FakeCallback(f"mkt:{market.value.upper()}")
    await handlers.cb_market(callback)
    text, keyboard = callback.message.edits[0]
    assert str(bridge_id) in text
    assert label in text
    assert f"dur:auto:{asset.key}" in _ids(keyboard)


async def test_cricket_comes_from_catalog_not_guessed_id(monkeypatch):
    cricket = dynamic_asset("CRICKET_INDEX_OTC_R", Market.CRICKET, bridge_id=276, name="Cricket Index")
    _context(monkeypatch, FakeInventory([cricket]))
    callback = FakeCallback("mkt:CRICKET")
    await handlers.cb_market(callback)
    text, keyboard = callback.message.edits[0]
    assert "CRICKET INDEX" in text and "276" in text
    assert f"dur:manual:{cricket.key}" in _ids(keyboard)


async def test_cricket_unavailable_keeps_market_visible(monkeypatch):
    error = DataUnavailable("CRICKET_UNAVAILABLE", "no active Cricket instrument")
    _context(monkeypatch, FakeInventory(error=error))
    callback = FakeCallback("mkt:CRICKET")
    await handlers.cb_market(callback)
    text, keyboard = callback.message.edits[0]
    assert "CRICKET INDEX UNAVAILABLE" in text
    assert "mkt:cricket" in _ids(keyboard)


async def test_otc_unavailable_never_substitutes_forex(monkeypatch):
    error = DataUnavailable("OTC_UNAVAILABLE", "no verified OTC feed")
    _context(monkeypatch, FakeInventory(error=error))
    callback = FakeCallback("mkt:OTC")
    await handlers.cb_market(callback)
    text, keyboard = callback.message.edits[0]
    assert "OTC UNAVAILABLE" in text
    assert "EUR/USD" not in text
    assert "mkt:otc" in _ids(keyboard)


def test_forex_selector_uses_real_pairs():
    data = _ids(handlers.menus.market_menu(Market.FOREX))
    assert "pick:EUR_USD_FOREX" in data
    assert all(item.startswith(("pick:", "mkt:", "menu:", "markets")) for item in data)


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
    assert durations == [30, 45, 60, 105, 300]
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
    assert "TRADE TIME" in text and "1 MIN" in text
    assert "SIGNAL: <b>BUY" in text


async def test_auto_duration_chooses_supported_value_and_explains(monkeypatch):
    asset = dynamic_asset("AI_INDEX_OTC_R", Market.AI, bridge_id=285, name="AI Index")
    generator = FakeGenerator(asset)
    _context(monkeypatch, FakeInventory([asset]), generator)
    callback = FakeCallback(f"dur:auto:{asset.key}")
    await handlers.cb_duration_mode(callback)
    text = callback.message.edits[-1][0]
    assert "TRADE TIME" in text
    assert "TRADE CONFIDENCE" in text
    _, _, note = handlers._LAST_ANALYSIS[(callback.from_user.id, asset.key)]
    assert "SMART DURATION" in note
    assert "volatility NORMAL" in note
    assert generator.calls


async def test_auto_duration_no_trade_does_not_create_signal(monkeypatch):
    asset = dynamic_asset("AI_INDEX_OTC_R", Market.AI, bridge_id=285, name="AI Index")
    generator = FakeGenerator(asset)
    generator.fetch_and_analyse = lambda asset, tf: _no_trade(asset)
    _context(monkeypatch, FakeInventory([asset]), generator)
    callback = FakeCallback(f"dur:auto:{asset.key}")
    await handlers.cb_duration_mode(callback)
    text = callback.message.edits[-1][0]
    assert "NO TRADE" in text
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
    football = dynamic_asset("FOOTBALL_INDEX_OTC_R", Market.FOOTBALL, bridge_id=278, name="Football Index")
    ai = dynamic_asset("AI_INDEX_OTC_R", Market.AI, bridge_id=285, name="AI Index")
    _context(monkeypatch, FakeInventory([football, ai]))
    for market, asset, other in ((Market.FOOTBALL, football, ai), (Market.AI, ai, football)):
        callback = FakeCallback(f"mkt:{market.value.upper()}")
        await handlers.cb_market(callback)
        text = callback.message.edits[0][0]
        assert str(asset.bridge_id) in text
        assert str(other.bridge_id) not in text
