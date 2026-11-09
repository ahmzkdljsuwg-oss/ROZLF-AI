from __future__ import annotations

import time

import pytest
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from rozlf.bot.app import build_dispatcher
from rozlf.services.container import AppContainer


def message_update(text: str, chat_id: int = 42, command: bool = True) -> Update:
    msg = Message.model_validate(
        {
            "message_id": 1,
            "date": int(time.time()),
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": chat_id, "is_bot": False, "first_name": "Owner"},
            "text": text,
            "entities": [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}] if command else [],
        }
    )
    return Update.model_validate({"update_id": 1, "message": msg.model_dump()})


def callback_update(data: str, chat_id: int = 42) -> Update:
    payload = {
        "id": "cb1",
        "from": {"id": chat_id, "is_bot": False, "first_name": "Owner"},
        "chat_instance": "1",
        "data": data,
        "message": {
            "message_id": 2,
            "date": int(time.time()),
            "chat": {"id": chat_id, "type": "private"},
            "text": "menu",
        },
    }
    return Update.model_validate({"update_id": 2, "callback_query": payload})


@pytest.fixture
def dp(container, bot):
    from rozlf.bot.handlers import ROUTERS

    for router in ROUTERS:
        router._parent_router = None
    return build_dispatcher(container)


@pytest.fixture
async def container(settings, tmp_path):
    settings.database_url = f"sqlite+aiosqlite:///{tmp_path}/bot.db"
    app = AppContainer(settings)
    await app.startup(None)
    yield app
    await app.shutdown()


async def test_start_shows_main_menu(dp, container, bot, bot_session):
    await dp.feed_update(bot, message_update("/start"))
    names = [c[0] for c in bot_session.calls]
    assert "SendMessage" in names
    text = next(c[1]["text"] for c in bot_session.calls if c[0] == "SendMessage")
    assert "ROZLF AI" in text


async def test_stats_and_history_callbacks(dp, container, bot, bot_session):
    await dp.feed_update(bot, callback_update("stats:show"))
    await dp.feed_update(bot, callback_update("hist:1"))
    names = [c[0] for c in bot_session.calls]
    assert "EditMessageText" in names or "SendMessage" in names
    assert "AnswerCallbackQuery" in names


async def test_sources_listing(dp, container, bot, bot_session):
    await dp.feed_update(bot, callback_update("set:sources"))
    text = next(c[1]["text"] for c in bot_session.calls if c[0] == "EditMessageText")
    assert "Twelve" in text or "مصدر" in text


async def test_foreign_chat_is_blocked(dp, container, bot, bot_session):
    await dp.feed_update(bot, message_update("/start", chat_id=999))
    texts = [c[1].get("text", "") for c in bot_session.calls]
    assert any("مخصص لمالكه" in t for t in texts)
    assert not any("ROZLF AI" in t for t in texts)


async def test_auto_toggle_changes_state(dp, container, bot, bot_session):
    await dp.feed_update(bot, callback_update("auto:toggle"))
    assert container.state.auto_enabled is True


async def test_health_command(dp, container, bot, bot_session):
    await dp.feed_update(bot, message_update("/health"))
    text = next(c[1]["text"] for c in bot_session.calls if c[0] == "SendMessage")
    assert "FOREX" in text
