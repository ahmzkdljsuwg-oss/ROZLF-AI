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
    text, _ = callback.message.edits[0]
    assert "غير معروف" in text


async def test_image_help_callback():
    callback = FakeCallback("img:help")
    await handlers.cb_image_help(callback)
    text, keyboard = callback.message.edits[0]
    assert "PNG" in text and "WEBP" in text
    assert keyboard is not None


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
    assert any(item.startswith("sa:") for item in data)

    chosen = assets[1]
    callback = FakeCallback(f"sa:{chosen.key}")
    await handlers.cb_smarty_asset(callback)
    text, keyboard = callback.message.edits[0]
    assert chosen.key.replace("SMARTY_", "") in text.replace(" ", "") or "SMRTY" in text
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert f"sm:{chosen.key}:60" in data


async def test_smarty_single_asset_opens_durations_immediately(monkeypatch):
    asset = _smarty_assets()[0]
    _fake_context(monkeypatch, inventory=FakeInventory(assets=[asset]))
    callback = FakeCallback("mkt:SMARTY")
    await handlers.cb_market(callback)
    _, keyboard = callback.message.edits[0]
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert f"sm:{asset.key}:60" in data
    assert all(not item.startswith("sa:") for item in data)


async def test_smarty_asset_callback_shows_durations_once(monkeypatch):
    asset = _smarty_assets()[0]
    _fake_context(monkeypatch, inventory=FakeInventory(assets=[asset]))
    callback = FakeCallback(f"ast:{asset.key}")
    await handlers.cb_asset(callback)
    text, keyboard = callback.message.edits[0]
    assert "SMARTY" in text.upper()
    data = [b.callback_data for row in keyboard.inline_keyboard for b in row]
    assert f"sm:{asset.key}:30" in data
    assert "SMARTY_241" not in text
