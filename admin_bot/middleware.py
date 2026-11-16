"""Reject anyone who is not a configured owner of the admin bot."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger(__name__)


class OwnerOnlyMiddleware(BaseMiddleware):
    def __init__(self, owners: frozenset[int]) -> None:
        self.owners = owners

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        user_id = user.id if user else None
        if user_id in self.owners:
            return await handler(event, data)
        logger.warning("blocked non-owner admin bot access user=%s", user_id)
        text = (
            "⛔ هذا البوت مخصص لمالك النظام فقط.\n"
            f"معرفك: <code>{user_id}</code>"
        )
        if hasattr(event, "answer") and hasattr(event, "data") and not hasattr(event, "text"):
            await event.answer("⛔ غير مصرح لك.", show_alert=True)
            return None
        if hasattr(event, "answer"):
            await event.answer(text, parse_mode="HTML")
        return None
