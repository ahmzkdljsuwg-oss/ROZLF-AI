"""Access control: only the configured chat/user ids may use the bot."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import Settings

logger = logging.getLogger(__name__)


class AccessMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings) -> None:
        self.allowed = settings.allowed_chat_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self.allowed:
            return await handler(event, data)

        user_id = None
        chat_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id if event.from_user else None
            chat_id = event.chat.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id if event.from_user else None
            chat_id = event.message.chat.id if event.message else None

        if user_id in self.allowed or chat_id in self.allowed:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            await event.answer("⛔ غير مصرح لك باستخدام هذا البوت.", show_alert=True)
            return None
        if isinstance(event, Message):
            await event.answer(
                f"⛔ غير مصرح.\nCHAT ID: <code>{chat_id}</code>\n"
                "أضف هذا المعرف إلى TELEGRAM_CHAT_ID لتشغيل ROZLF AI.",
                parse_mode="HTML",
            )
        logger.warning("blocked unauthorized access user=%s chat=%s", user_id, chat_id)
        return None
