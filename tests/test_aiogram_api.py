import inspect
import pathlib

from aiogram import Bot
from aiogram.types import BotCommand, CallbackQuery, Message


def test_bot_command_registration_api_exists() -> None:
    assert hasattr(Bot, "set_my_commands")
    assert not hasattr(Bot, "set_my_bot_commands")


def test_main_registers_commands_with_aiogram3_method() -> None:
    source = pathlib.Path("main.py").read_text()
    assert "set_my_commands(" in source
    assert "set_my_bot_commands" not in source


async def test_set_my_commands_sends_setmycommands() -> None:
    bot = Bot(token="123456:AAHtestTOKENtestTOKENtestTOKENtestTOK")
    sent: dict = {}

    async def fake_make_request(_bot, method, timeout=None):
        sent["method"] = method.__api_method__
        sent["commands"] = [item.command for item in method.commands]
        return True

    bot.session.make_request = fake_make_request
    await bot.set_my_commands([BotCommand(command="start", description="بدء")])
    await bot.session.close()
    assert sent == {"method": "setMyCommands", "commands": ["start"]}


def test_handlers_use_existing_types() -> None:
    assert "reply_markup" in inspect.signature(Message.answer).parameters
    assert "disable_web_page_preview" in inspect.signature(Message.answer).parameters
    assert "show_alert" in inspect.signature(CallbackQuery.answer).parameters
