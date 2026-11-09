from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, Message

log = logging.getLogger(__name__)


async def edit_or_send(
    message: Message,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    try:
        await message.edit_text(text, reply_markup=keyboard, disable_web_page_preview=True)
    except TelegramBadRequest:
        await message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)
