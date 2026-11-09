from __future__ import annotations

import asyncio
import math
import time

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, GetMe, SendMessage, SendPhoto
from aiogram.types import Message, User
from aiogram.methods.base import TelegramType

from rozlf.config import Settings
from rozlf.database.repository import SignalRepository
from rozlf.providers.base import Candle


def make_candles(n: int = 200, *, trend: float = 0.0004, start: float = 1.1000, timeframe: int = 300) -> list[Candle]:
    now = int(time.time()) // timeframe * timeframe
    candles: list[Candle] = []
    price = start
    for i in range(n):
        wave = math.sin(i / 5.0) * 0.0020
        open_ = price
        close = price + trend + wave * 0.6
        high = max(open_, close) + abs(wave) * 0.5 + 0.0002
        low = min(open_, close) - abs(wave) * 0.5 - 0.0002
        candles.append(Candle(now - (n - i) * timeframe, open_, high, low, close, 100.0 + i))
        price = close
    # keep the last candle recent so freshness validation passes
    candles[-1] = Candle(
        int(time.time()) // timeframe * timeframe,
        candles[-1].open,
        candles[-1].high,
        candles[-1].low,
        candles[-1].close,
        candles[-1].volume,
    )
    return candles


def flat_candles(n: int = 200, timeframe: int = 300) -> list[Candle]:
    return make_candles(n, trend=0.0, timeframe=timeframe)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        telegram_bot_token="123:TEST",
        telegram_chat_id="42",
        twelve_data_api_key="",
        mistral_api_key="",
    )


@pytest.fixture
def candles() -> list[Candle]:
    return make_candles()


@pytest.fixture
async def repo(tmp_path):
    database = await SignalRepository.create(f"sqlite+aiosqlite:///{tmp_path}/test.db")
    yield database
    await database.close()


class CannedSession(BaseSession):
    """Captures outgoing Telegram calls and returns valid fake objects."""

    def __init__(self):
        super().__init__()
        self.calls: list[tuple[str, dict]] = []

    async def close(self) -> None:
        return None

    async def stream_content(self, *args, **kwargs):  # pragma: no cover - never used in tests
        raise NotImplementedError

    async def make_request(self, bot, method, timeout=None) -> TelegramType:  # type: ignore[override]
        name = method.__class__.__name__
        self.calls.append((name, method.model_dump(exclude_none=True)))
        if isinstance(method, GetMe):
            return User(id=1, is_bot=True, first_name="ROZLF", username="rozlf_test_bot")
        if isinstance(method, (SendMessage, SendPhoto, EditMessageText)):
            chat_id = getattr(method, "chat_id", None) or getattr(getattr(method, "chat", None), "id", 42)
            return Message.model_validate(
                {
                    "message_id": len(self.calls),
                    "date": int(time.time()),
                    "chat": {"id": int(chat_id), "type": "private"},
                    "text": getattr(method, "text", None) or getattr(method, "caption", None) or "",
                }
            )
        if isinstance(method, AnswerCallbackQuery):
            return True
        return True


@pytest.fixture
def bot_session() -> CannedSession:
    return CannedSession()


@pytest.fixture
def bot(bot_session) -> Bot:
    return Bot(token="123:TEST", session=bot_session)
