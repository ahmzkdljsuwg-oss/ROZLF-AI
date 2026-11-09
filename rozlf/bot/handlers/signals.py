from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery

from ...services.container import AppContainer
from .. import keyboards, texts
from ..utils import edit_or_send

log = logging.getLogger(__name__)
router = Router(name="signals")

PER_PAGE = 8


@router.callback_query(F.data == "live:list")
async def cb_live(query: CallbackQuery, container: AppContainer) -> None:
    rows = await container.repo.list(status="OPEN", limit=15)  # type: ignore[union-attr]
    await edit_or_send(
        query.message,  # type: ignore[arg-type]
        texts.live_block([r.as_dict() for r in rows]),
        keyboards.back_to_menu(),
    )
    await query.answer()


@router.message(Command("live"))
async def cmd_live(message, container: AppContainer) -> None:
    rows = await container.repo.list(status="OPEN", limit=15)  # type: ignore[union-attr]
    await message.answer(texts.live_block([r.as_dict() for r in rows]), reply_markup=keyboards.back_to_menu())


@router.callback_query(F.data.startswith("hist:"))
async def cb_history(query: CallbackQuery, container: AppContainer) -> None:
    page = max(1, int((query.data or "hist:1").split(":")[1]))
    rows = await container.repo.list(limit=PER_PAGE * page + 1)  # type: ignore[union-attr]
    has_more = len(rows) > PER_PAGE * page
    chunk = [r.as_dict() for r in rows[(page - 1) * PER_PAGE : page * PER_PAGE]]
    await edit_or_send(
        query.message,  # type: ignore[arg-type]
        texts.history_block(chunk, page, PER_PAGE),
        keyboards.history_nav(page, has_more),
    )
    await query.answer()
