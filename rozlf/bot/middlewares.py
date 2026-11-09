from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from ..config import Settings

log = logging.getLogger(__name__)

MIN_INTERVAL = 0.8


class AccessMiddleware(BaseMiddleware):
    """Only the operator chat may use the bot (when TELEGRAM_CHAT_ID is set)."""

    def __init__(self, settings: Settings):
        self.allowed = str(settings.telegram_chat_id or "").strip()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self.allowed:
            return await handler(event, data)
        chat_id = _chat_id(event)
        if chat_id is not None and str(chat_id) == self.allowed:
            return await handler(event, data)
        if isinstance(event, CallbackQuery):
            await event.answer("هذا البوت مخصص لمالكه.", show_alert=True)
        elif isinstance(event, Message):
            await event.answer("هذا البوت مخصص لمالكه.")
        log.warning("blocked access from chat %s", chat_id)
        return None


def _chat_id(event: TelegramObject) -> int | None:
    chat = getattr(event, "chat", None)
    if chat is not None:
        return getattr(chat, "id", None)
    message = getattr(event, "message", None)
    if message is not None:
        return getattr(getattr(message, "chat", None), "id", None)
    return getattr(getattr(event, "from_user", None), "id", None)


class ThrottleMiddleware(BaseMiddleware):
    def __init__(self, interval: float = MIN_INTERVAL):
        self.interval = interval
        self._last: dict[int, float] = defaultdict(float)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        uid = getattr(user, "id", None)
        if uid:
            now = time.monotonic()
            if now - self._last[uid] < self.interval:
                if isinstance(event, CallbackQuery):
                    await event.answer("تمهّل لحظة…")
                return None
            self._last[uid] = now
        return await handler(event, data)
