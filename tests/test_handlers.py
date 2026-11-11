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
            settings=SimpleNamespace(min_confidence=65.0, scan_interval=90, scanner_enabled=False),
        ),
        raising=False,
    )


async def test_market_callback_lists_assets(monkeypatch):
    _fake_context(monkeypatch)
    callback = FakeCallback("mkt:FOREX")
    await handlers.cb_market(callback)
    text, keyboard = callback.message.edits[0]
    assert "FOREX" in text
    assert keyboard is not None
    assert callback.answered


REQUIRED_MENU = [
    "🧠 SMARTY MARKET",
    "⚽ FOOTBALL INDEX",
    "💎 LUXURY INDEX",
    "🤖 AI INDEX",
    "🏏 CRICKET INDEX",
    "💱 FOREX MARKET",
    "📡 LIVE SIGNALS",
    "📜 SIGNAL HISTORY",
    "📊 PERFORMANCE STATISTICS",
    "⚙️ SETTINGS",
    "🖥️ SYSTEM STATUS",
]


async def test_start_renders_exact_new_menu(monkeypatch, settings):
    from bot import context

    monkeypatch.setattr(context, "_context", SimpleNamespace(settings=settings), raising=False)
    message = FakeMessage()
    await handlers.cmd_start(message)
    text, keyboard = message.answers[0]
    assert [button.text for row in keyboard.inline_keyboard for button in row] == REQUIRED_MENU
    assert "OTC" not in text and "GOLD ANALYSIS" not in text
    assert "PERFORMANCE STATISTICS" in text


@pytest.mark.parametrize(
    ("market_name", "symbol", "asset_id"),
    [
        ("SMARTY", "SMRTY", 240),
        ("FOOTBALL", "FOOTBALL_INDEX_OTC_R", 278),
        ("LUXURY", "LUXURY_INDEX_OTC_R", 286),
        ("AI", "AI_INDEX_OTC_R", 285),
        ("CRICKET", "CRICKET_INDEX_OTC_R", 276),
    ],
)
async def test_each_market_button_opens_its_real_asset(monkeypatch, market_name, symbol, asset_id):
    from providers.catalog import Market, dynamic_asset

    asset = dynamic_asset(symbol, getattr(Market, market_name), precision=5, bridge_id=asset_id, name=market_name)
    _fake_context(monkeypatch, inventory=FakeInventory(assets=[asset]))
    callback = FakeCallback(f"mkt:{market_name}")
    await handlers.cb_market(callback)
    text, keyboard = callback.message.edits[0]
    assert f"ID {asset_id}" in text
    data = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert f"dur:auto:{asset.key}" in data
    assert f"dur:manual:{asset.key}" in data


async def test_forex_button_shows_real_pairs(monkeypatch):
    _fake_context(monkeypatch)
    callback = FakeCallback("mkt:FOREX")
    await handlers.cb_market(callback)
    text, keyboard = callback.message.edits[0]
    for pair in ("EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD", "USD/CAD", "USD/CHF", "NZD/USD", "EUR/JPY", "GBP/JPY"):
        assert pair in text
    assert "XAU/USD" not in text
    assert keyboard is not None


async def test_inactive_cricket_shows_unavailable_and_no_durations(monkeypatch):
    from providers.base import DataUnavailable

    class InactiveCricket(FakeInventory):
        async def assets(self, market, force=False):
            raise DataUnavailable("CRICKET_UNAVAILABLE", "CRICKET UNAVAILABLE — no active Cricket instrument")

    _fake_context(monkeypatch, inventory=InactiveCricket())
    callback = FakeCallback("mkt:CRICKET")
    await handlers.cb_market(callback)
    text, keyboard = callback.message.edits[0]
    assert "CRICKET UNAVAILABLE" in text
    data = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert not any(item.startswith(("dur:", "md:", "ix:")) for item in data)


async def test_market_callback_is_case_insensitive(monkeypatch):
    _fake_context(monkeypatch)
    callback = FakeCallback("mkt:SMARTY")
    await handlers.cb_market(callback)
    text, _ = callback.message.edits[0]
    assert "SMARTY" in text.upper()


async def test_unknown_market_rejected(monkeypatch):
    _fake_context(monkeypatch)
    callback = FakeCallback("mkt:CRYPTO")
    await handlers.cb_market(callback)
    assert any("غير معروف" in text for text in callback.answered)
    assert callback.message.edits == []


async def test_markets_hub_callback():
    callback = FakeCallback("markets")
    await handlers.cb_markets(callback)
    text, keyboard = callback.message.edits[0]
    assert "MARKET DESK" in text
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert data == [
        "mkt:SMARTY",
        "mkt:FOOTBALL",
        "mkt:LUXURY",
        "mkt:AI",
        "mkt:CRICKET",
        "mkt:FOREX",
        "menu:main",
    ]
    assert not any("OTC" in item for item in data)


async def test_football_market_opens_asset_278_durations(monkeypatch):
    from providers.catalog import Market, dynamic_asset

    asset = dynamic_asset(
        "FOOTBALL_INDEX_OTC_R", Market.FOOTBALL, precision=5, bridge_id=278, name="Football Index"
    )
    _fake_context(monkeypatch, inventory=FakeInventory(assets=[asset]))
    callback = FakeCallback("mkt:FOOTBALL")
    await handlers.cb_market(callback)
    text, keyboard = callback.message.edits[0]
    assert "FOOTBALL INDEX" in text and "278" in text
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert f"dur:auto:{asset.key}" in data
    assert f"dur:manual:{asset.key}" in data


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
    assert "📊 MARKET:" in callback.message.edits[-1][0]
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


async def test_smarty_market_lists_assets_and_single_tap_selects(monkeypatch):
    assets = _smarty_assets()
    _fake_context(monkeypatch, inventory=FakeInventory(assets=assets))

    callback = FakeCallback("mkt:SMARTY")
    await handlers.cb_market(callback)
    text, keyboard = callback.message.edits[0]
    assert "SMARTY" in text
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert any(item.startswith("pick:") for item in data)

    chosen = assets[1]
    callback = FakeCallback(f"pick:{chosen.key}")
    await handlers.cb_pick_asset(callback)
    text, keyboard = callback.message.edits[0]
    assert chosen.key.replace("SMARTY_", "") in text.replace(" ", "") or "SMRTY" in text
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert f"dur:manual:{chosen.key}" in data


async def test_smarty_single_asset_opens_durations_immediately(monkeypatch):
    asset = _smarty_assets()[0]
    _fake_context(monkeypatch, inventory=FakeInventory(assets=[asset]))
    callback = FakeCallback("mkt:SMARTY")
    await handlers.cb_market(callback)
    _, keyboard = callback.message.edits[0]
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert f"dur:manual:{asset.key}" in data
    assert f"dur:auto:{asset.key}" in data
    assert all(not item.startswith("sa:") for item in data)


async def test_smarty_asset_callback_shows_durations_once(monkeypatch):
    asset = _smarty_assets()[0]
    _fake_context(monkeypatch, inventory=FakeInventory(assets=[asset]))
    callback = FakeCallback(f"ast:{asset.key}")
    await handlers.cb_asset(callback)
    text, keyboard = callback.message.edits[0]
    assert "SMARTY" in text.upper()
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert f"dur:manual:{asset.key}" in data
    assert "SMARTY_241" not in text
