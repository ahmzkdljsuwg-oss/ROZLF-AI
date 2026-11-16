"""Block every NEXUS analysis route for users without an active subscription."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import Settings
from database.repository import Repository

logger = logging.getLogger(__name__)

PUBLIC_COMMANDS = {"start", "menu", "activate", "status", "help", "id"}
PUBLIC_CALLBACKS = {"nx:home", "nx:more", "menu:main", "menu:refresh"}


def _command_of(message: Message) -> str | None:
    text = (message.text or "").strip()
    if not text.startswith("/"):
        return None
    return text.split()[0].lstrip("/").split("@", 1)[0].lower()


class SubscriptionMiddleware(BaseMiddleware):
    def __init__(self, settings: Settings, repo: Repository) -> None:
        self.settings = settings
        self.repo = repo
        self.enabled = settings.subscriptions_enabled
        self.owners = settings.owner_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self.enabled:
            return await handler(event, data)

        user = getattr(event, "from_user", None)
        user_id = user.id if user else None
        if user_id is None:
            return await handler(event, data)
        if user_id in self.owners:
            return await handler(event, data)

        if hasattr(event, "data") and not hasattr(event, "text"):
            if event.data in PUBLIC_CALLBACKS:
                return await handler(event, data)
        else:
            command = _command_of(event)
            if command is not None and command in PUBLIC_COMMANDS:
                return await handler(event, data)

        try:
            active = await self.repo.is_subscribed(user_id)
        except Exception:
            logger.exception("subscription lookup failed for %s", user_id)
            active = False

        if active:
            return await handler(event, data)

        text = (
            "⛔ الاشتراك غير نشط.\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "أرسل كود التفعيل بالأمر:\n"
            "<code>/activate NX-XXXX-XXXX-XXXX-XXXX</code>\n"
            "ولمعرفة حالتك: /status"
        )
        if hasattr(event, "data") and hasattr(event, "answer") and not hasattr(event, "text"):
            await event.answer("⛔ الاشتراك غير نشط — فعّل الكود أولاً.", show_alert=True)
            if event.message is not None:
                try:
                    await event.message.answer(text, parse_mode="HTML")
                except Exception:
                    logger.info("could not send subscription notice to %s", user_id)
            return None
        if hasattr(event, "answer"):
            await event.answer(text, parse_mode="HTML")
        return None
