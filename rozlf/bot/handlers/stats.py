from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ...services.container import AppContainer
from .. import keyboards, texts
from ..utils import edit_or_send

log = logging.getLogger(__name__)
router = Router(name="stats")


@router.callback_query(F.data == "stats:show")
async def cb_stats(query: CallbackQuery, container: AppContainer) -> None:
    stats = await container.stats.overview()  # type: ignore[union-attr]
    await edit_or_send(query.message, texts.stats_block(stats), keyboards.back_to_menu())  # type: ignore[arg-type]
    await query.answer()


@router.message(Command("stats"))
async def cmd_stats(message: Message, container: AppContainer) -> None:
    stats = await container.stats.overview()  # type: ignore[union-attr]
    await message.answer(texts.stats_block(stats), reply_markup=keyboards.back_to_menu())
