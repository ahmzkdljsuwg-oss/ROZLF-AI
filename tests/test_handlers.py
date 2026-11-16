from types import SimpleNamespace

import pytest

from bot.handlers import menus as handlers


class FakeMessage:
    def __init__(self) -> None:
        self.edits: list[tuple[str, object]] = []
        self.answers: list[tuple[str, object]] = []

    async def edit_text(self, text, reply_markup=None, **kwargs):
        self.edits.append((text, reply_markup))

    async def answer(self, text, reply_markup=None, **kwargs):
        self.answers.append((text, reply_markup))


class FakeCallback:
    def __init__(self, data: str, user_id: int = 42) -> None:
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMessage()
        self.answered: list[str] = []

    async def answer(self, text: str = "", show_alert: bool = False, **kwargs):
        self.answered.append(text)


class FakeRegistry:
    def source_summary(self, asset):
        return "NONE"


class _FakeRepo:
    async def get_analysis_mode(self, user_id):
        return "strong"

    async def add_signal(self, **kwargs):
        return 1


class FakeInventory:
    def __init__(self, assets=None, error=None):
        self.assets_list = assets or []
        self.error = error

    async def assets(self, market, force=False):
        if self.error is not None:
            from providers.base import DataUnavailable

            raise DataUnavailable("EO_BRIDGE_NOT_CONFIGURED", self.error, "bridge not configured")
        return self.assets_list

    async def resolve(self, key):
        return next((asset for asset in self.assets_list if asset.key == key), None)


def _fake_context(monkeypatch, inventory=None):
    from bot import context

    monkeypatch.setattr(
        context,
        "_context",
        SimpleNamespace(
            registry=FakeRegistry(),
            inventory=inventory or FakeInventory(),
            repo=_FakeRepo(),
            settings=SimpleNamespace(min_confidence=65.0, scan_interval=90, scanner_enabled=False),
        ),
        raising=False,
    )


async def test_market_callback_lists_assets(monkeypatch):
    from providers.catalog import Market, dynamic_asset

    asset = dynamic_asset("SMRTY", Market.SMARTY, precision=2, bridge_id=240, name="SMRTY")
    _fake_context(monkeypatch, inventory=FakeInventory(assets=[asset]))
    callback = FakeCallback("nx:market:SMARTY")
    await handlers._nexus_assets(callback, "SMARTY", 0)
    text, keyboard = callback.message.edits[0]
    assert "SMARTY" in text
    assert "nx:pick:SMARTY:0" in [b.callback_data for row in keyboard.inline_keyboard for b in row]


REQUIRED_MENU = ["ابدأ استلام الإشارات 🚀"]


async def test_start_renders_exact_new_menu(monkeypatch, settings):
    from bot import context

    monkeypatch.setattr(context, "_context", SimpleNamespace(settings=settings), raising=False)
    message = FakeMessage()
    await handlers.cmd_start(message)
    text, keyboard = message.answers[0]
    assert [button.text for row in keyboard.inline_keyboard for button in row] == REQUIRED_MENU
    assert "NEXUS AI" in text
    assert "أهلاً بك" in text


@pytest.mark.parametrize("market_name", ["OTC", "SMARTY", "FOOTBALL", "LUXURY", "AI", "CRICKET", "FOREX", "GOLD"])
async def test_every_market_button_dispatches_to_the_unified_flow(monkeypatch, market_name):
    _fake_context(monkeypatch)
    seen = []

    async def fake_analyse(callback, name, asset_key=None):
        seen.append(("analysis", name))

    async def fake_assets(callback, name, page):
        seen.append(("picker", name))

    monkeypatch.setattr(handlers, "_nexus_analyse", fake_analyse)
    monkeypatch.setattr(handlers, "_nexus_assets", fake_assets)
    callback = FakeCallback(f"nx:market:{market_name}")
    await handlers.cb_nx_market(callback)
    expected = "picker" if market_name in handlers.ASSET_PICK_MARKETS else "analysis"
    assert seen == [(expected, market_name)]


async def test_forex_button_shows_real_pairs(monkeypatch):
    _fake_context(monkeypatch)
    callback = FakeCallback("nx:market:FOREX")
    await handlers._nexus_analyse(callback, "FOREX")
    text, keyboard = callback.message.edits[-1]
    assert "FOREX" in text.upper()
    assert keyboard is not None


async def test_inactive_cricket_shows_unavailable_and_no_durations(monkeypatch):
    from providers.base import DataUnavailable

    class InactiveCricket(FakeInventory):
        async def assets(self, market, force=False):
            raise DataUnavailable("CRICKET_UNAVAILABLE", "CRICKET UNAVAILABLE — no active Cricket instrument")

    _fake_context(monkeypatch, inventory=InactiveCricket())
    callback = FakeCallback("nx:market:CRICKET")
    await handlers._nexus_analyse(callback, "CRICKET")
    text, keyboard = callback.message.edits[-1]
    assert "DATA UNAVAILABLE" in text
    data = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert not any(item.startswith(("dur:", "md:", "ix:")) for item in data)


async def test_unknown_market_rejected(monkeypatch):
    _fake_context(monkeypatch)
    callback = FakeCallback("nx:market:CRYPTO")
    await handlers.cb_nx_market(callback)
    assert any("غير معروف" in text for text in callback.answered)
    assert callback.message.edits == []


async def test_markets_hub_callback():
    callback = FakeCallback("markets")
    await handlers.cb_markets(callback)
    text, keyboard = callback.message.edits[0]
    assert text == "📊 اختر السوق المراد تحليله:"
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert data[:9] == [
        "nx:market:FOOTBALL", "nx:classic:smarty", "nx:market:GOLD", "nx:market:OTC",
        "nx:market:LUXURY", "nx:market:AI", "nx:market:CRICKET", "nx:market:FOREX", "mt5:list",
    ]
    assert data[-1] == "nx:more"


async def test_football_duration_reaches_asset_278_analysis(monkeypatch):
    from bot import context
    from providers.catalog import Market, dynamic_asset

    asset = dynamic_asset(
        "FOOTBALL_INDEX_OTC_R", Market.FOOTBALL, precision=5, bridge_id=278, name="Football Index"
    )
    calls = []

    class FakeGenerator:
        async def generate(self, user_id, chosen, tf, duration_seconds=None, min_confidence=None):
            calls.append((chosen, tf, duration_seconds))
            return object(), None

    class FakeRepo:
        async def get_user_settings(self, user_id, defaults=None):
            return {"min_confidence": 65.0}

    monkeypatch.setattr(
        context,
        "_context",
        SimpleNamespace(
            registry=FakeRegistry(),
            inventory=FakeInventory(assets=[asset]),
            generator=FakeGenerator(),
            repo=FakeRepo(),
            settings=SimpleNamespace(min_confidence=65.0),
        ),
        raising=False,
    )
    callback = FakeCallback(f"ix:{asset.key}:30")
    await handlers.cb_index_signal(callback)
    assert "📊 السوق:" in callback.message.edits[-1][0]
    assert len(calls) == 1
    assert calls[0][0].bridge_id == 278
    assert calls[0][0].market is Market.FOOTBALL
    assert calls[0][2] == 30


async def test_asset_callback_needs_context(monkeypatch):
    from bot import context

    class FakeRegistry:
        def source_summary(self, asset):
            return "NONE"

    monkeypatch.setattr(context, "_context", SimpleNamespace(registry=FakeRegistry(), settings=None), raising=False)
    callback = FakeCallback("ast:EUR_USD_FOREX")
    await handlers.cb_asset(callback)
    text, keyboard = callback.message.edits[0]
    assert "EUR/USD" in text and "NONE" in text
    assert keyboard is not None


def _smarty_assets():
    from providers.catalog import Market, dynamic_asset

    return [
        dynamic_asset("SMRTY", Market.SMARTY, precision=2, bridge_id=240, name="SMRTY"),
        dynamic_asset("SMRTY2", Market.SMARTY, precision=2, bridge_id=241, name="SMRTY 2"),
    ]


async def test_smarty_market_lists_assets_in_the_unified_picker(monkeypatch):
    assets = _smarty_assets()
    _fake_context(monkeypatch, inventory=FakeInventory(assets=assets))
    callback = FakeCallback("nx:market:SMARTY")
    await handlers._nexus_assets(callback, "SMARTY", 0)
    text, keyboard = callback.message.edits[0]
    assert "SMARTY" in text
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert "nx:pick:SMARTY:0" in data and "nx:pick:SMARTY:1" in data
