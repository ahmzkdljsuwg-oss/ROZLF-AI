"""Task Q: Telegram UX redesign (3-button home, ANALYSIS, durations, settings, recommendations)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from bot import formatting as fmt
from bot.handlers import menus as handlers
from bot.keyboards import menus
from providers.base import DataUnavailable
from providers.catalog import Market, assets_for, dynamic_asset

FULL_MARKETS = [
    ("🧠 SMARTY MARKET", "mkt:SMARTY"),
    ("⚽ FOOTBALL INDEX", "mkt:FOOTBALL"),
    ("💎 LUXURY INDEX", "mkt:LUXURY"),
    ("🤖 AI INDEX", "mkt:AI"),
    ("🏏 CRICKET INDEX", "mkt:CRICKET"),
    ("💱 FOREX MARKET", "mkt:FOREX"),
]


class FakeMessage:
    def __init__(self):
        self.edits = []
        self.answers = []

    async def edit_text(self, text, reply_markup=None, **kwargs):
        self.edits.append((text, reply_markup))

    async def answer(self, text, reply_markup=None, **kwargs):
        self.answers.append((text, reply_markup))


class FakeCallback:
    def __init__(self, data, user_id=42):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMessage()
        self.answered = []

    async def answer(self, text="", show_alert=False, **kwargs):
        self.answered.append(text)


def get_asset_dynamic(key):
    from providers.catalog import get_asset
    return get_asset(key)


def _ids(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_home_has_exactly_three_buttons():
    markup = menus.main_menu()
    assert len(markup.inline_keyboard) == 2
    assert [b.text for row in markup.inline_keyboard for b in row] == [
        "📉 ANALYSIS", "⚙️ SETTINGS", "🏆 RECOMMENDATIONS",
    ]
    assert [b.callback_data for row in markup.inline_keyboard for b in row] == ["analysis", "settings", "recs"]


def test_analysis_lists_six_full_market_names_without_home_clutter():
    markup = menus.markets_menu()
    texts = [b.text for row in markup.inline_keyboard for b in row]
    for label, _ in FULL_MARKETS:
        assert label in texts
    assert not any("OTC" in t or "GOLD" in t for t in texts)
    assert "live" not in _ids(markup)


def test_duration_menu_uses_requested_labels_and_supported_only():
    asset = dynamic_asset("SMRTY", Market.SMARTY, bridge_id=240, name="SMARTY")
    markup = menus.trade_duration_menu(asset, [30, 60, 300])
    texts = [b.text for row in markup.inline_keyboard for b in row]
    for label in ("⏱️ 30 SECONDS", "⏱️ 1 MINUTE", "⏱️ 5 MINUTES"):
        assert label in texts
    assert "⏱️ 2 MINUTES" not in texts
    assert "🧠 ANALYZE TRADE TIME" in texts
    data = _ids(markup)
    assert f"td:{asset.key}:30" in data and f"td:smart:{asset.key}" in data
    assert "menu:analysis" in data and "menu:main" in data


def test_trade_duration_labels_do_not_mix_candle_frame():
    assert fmt.trade_duration_label(60) == "⏱️ 1 MINUTE"
    text = fmt.trade_duration_text(
        dynamic_asset("SMRTY", Market.SMARTY, bridge_id=240), "LIVE", [30, 60, 300]
    )
    assert "Candle Timeframe" in text and "Trade Expiry" in text


def _fake_context(monkeypatch, ctx):
    from bot import context

    monkeypatch.setattr(context, "_context", ctx, raising=False)


class _Result:
    def __init__(self, direction, confidence, evidence):
        self.direction = direction
        self.confidence = confidence
        self.evidence_score = evidence
        self.data_quality_score = evidence
        self.source = "LIVE"
        self.timeframe = "1min"
        self.indicators = {"volatility": "NORMAL"}
        self.momentum_strength = "STRONG"


class _Generator:
    def __init__(self, results, duration=60):
        self.results = results
        self.duration = duration
        self.generated = []
        self.fetched = []

    async def fetch_and_analyse(self, asset, frame, duration_seconds=None):
        self.fetched.append(asset.key)
        if asset.key not in self.results:
            raise DataUnavailable("NO_DATA", "no fake data")
        return None, self.results[asset.key]

    async def generate(self, user_id, asset, tf, duration_seconds=None, min_confidence=None):
        self.generated.append(asset.key)
        return self.results[asset.key], object()


class _Repo:
    def __init__(self):
        self.saved = {}

    async def get_user_settings(self, user_id, defaults=None):
        return dict(self.saved.get(user_id, defaults or {"min_confidence": 60.0}))

    async def save_user_settings(self, user_id, settings):
        self.saved[user_id] = dict(settings)


class _Inventory:
    def __init__(self, mapping):
        self.mapping = mapping

    async def assets(self, market, force=False):
        return self.mapping.get(market, [])

    async def resolve(self, key):
        for group in self.mapping.values():
            for item in group:
                if item.key == key:
                    return item
        return get_asset_dynamic(key)


def _ctx(results, inventory, repo):
    return SimpleNamespace(
        settings=SimpleNamespace(min_confidence=50.0),
        registry=SimpleNamespace(source_summary=lambda asset: "LIVE"),
        inventory=inventory,
        generator=_Generator(results),
        repo=repo,
    )


async def test_analyze_trade_time_picks_best_without_issuing_signal(monkeypatch):
    asset = dynamic_asset("SMRTY", Market.SMARTY, bridge_id=240, name="SMARTY")
    results = {asset.key: _Result("UP", 62.0, 0.9)}
    generator = _Generator(results)
    inventory = _Inventory({Market.SMARTY: [asset]})
    ctx = SimpleNamespace(
        settings=SimpleNamespace(min_confidence=50.0),
        registry=SimpleNamespace(source_summary=lambda asset: "LIVE"),
        inventory=inventory,
        generator=generator,
        repo=_Repo(),
    )
    _fake_context(monkeypatch, ctx)
    callback = FakeCallback(f"td:smart:{asset.key}")
    await handlers.cb_trade_duration(callback)
    text = callback.message.edits[-1][0]
    assert "ANALYZE TRADE TIME" in text
    assert "المدة المقترحة" in text
    assert generator.generated == []  # no signal before the user confirms a duration


async def test_selected_duration_drives_signal_with_user_threshold(monkeypatch):
    asset = dynamic_asset("SMRTY", Market.SMARTY, bridge_id=240, name="SMARTY")
    results = {asset.key: _Result("DOWN", 74.0, 0.8)}
    generator = _Generator(results)
    ctx = SimpleNamespace(
        settings=SimpleNamespace(min_confidence=50.0),
        registry=SimpleNamespace(source_summary=lambda asset: "LIVE"),
        inventory=_Inventory({Market.SMARTY: [asset]}),
        generator=generator,
        repo=_Repo(),
    )
    _fake_context(monkeypatch, ctx)
    callback = FakeCallback(f"td:{asset.key}:60")
    await handlers.cb_trade_duration(callback)
    assert generator.generated == [asset.key]
    text = callback.message.edits[-1][0]
    assert "📊 MARKET:" in text and "SIGNAL:" in text


async def test_recommendations_skip_below_threshold_and_order_by_evidence(monkeypatch):
    smarty = dynamic_asset("SMRTY", Market.SMARTY, bridge_id=240, name="SMARTY")
    football = dynamic_asset("FOOTBALL_INDEX_OTC_R", Market.FOOTBALL, bridge_id=278, name="Football Index")
    results = {
        smarty.key: _Result("UP", 55.0, 0.4),    # below threshold 70
        football.key: _Result("DOWN", 80.0, 0.9),
        assets_for(Market.FOREX)[0].key: _Result("UP", 72.0, 0.6),
    }
    repo = _Repo()
    repo.saved[555] = {"min_confidence": 70.0}
    ctx = SimpleNamespace(
        settings=SimpleNamespace(min_confidence=50.0),
        registry=SimpleNamespace(source_summary=lambda asset: "LIVE"),
        inventory=_Inventory({Market.SMARTY: [smarty], Market.FOOTBALL: [football]}),
        generator=_Generator(results),
        repo=repo,
    )
    _fake_context(monkeypatch, ctx)
    monkeypatch.setattr(handlers, "choose_auto_duration", lambda result, asset: (60, "evidence"))
    handlers._RECS_CACHE.pop(555, None)
    callback = FakeCallback("recs", user_id=555)
    await handlers.cb_recommendations(callback)
    text = callback.message.edits[-1][0]
    assert "FOOTBALL INDEX" in text
    assert "80%" in text
    recommendations = text.split("SKIPPED")[0]
    assert "55%" not in recommendations


@pytest.mark.asyncio
async def test_recommendations_fall_back_to_no_valid(monkeypatch):
    smarty = dynamic_asset("SMRTY", Market.SMARTY, bridge_id=240, name="SMARTY")
    results = {smarty.key: _Result("UP", 49.0, 0.2)}
    ctx = SimpleNamespace(
        settings=SimpleNamespace(min_confidence=50.0),
        registry=SimpleNamespace(source_summary=lambda asset: "LIVE"),
        inventory=_Inventory({Market.SMARTY: [smarty]}),
        generator=_Generator(results),
        repo=_Repo(),
    )
    _fake_context(monkeypatch, ctx)
    monkeypatch.setattr(handlers, "choose_auto_duration", lambda result, asset: (60, "evidence"))
    callback = FakeCallback("recs", user_id=777)
    await handlers.cb_recommendations(callback)
    text = callback.message.edits[-1][0]
    assert "NO VALID RECOMMENDATIONS RIGHT NOW." in text


async def test_settings_saves_threshold_per_user(monkeypatch):
    ctx = SimpleNamespace(settings=SimpleNamespace(min_confidence=50.0), repo=_Repo())
    _fake_context(monkeypatch, ctx)
    callback = FakeCallback("set:pick:80")
    await handlers.cb_set_pick(callback)
    assert handlers._PENDING_MIN[callback.from_user.id] == 80.0
    await handlers.cb_set_save(FakeCallback("set:save"))
    assert ctx.repo.saved[42]["min_confidence"] == 80.0
