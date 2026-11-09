from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ... import __version__
from ...services.container import AppContainer
from .. import keyboards, texts

log = logging.getLogger(__name__)
router = Router(name="menu")


async def show_main(message: Message, container: AppContainer) -> None:
    ready = await container.readiness()
    await message.answer(
        texts.welcome(
            __version__,
            ai_ready=ready["ai_ready"],
            forex_ready=ready["forex_ready"],
            otc_ready=ready["otc_ready"],
        ),
        reply_markup=keyboards.main_menu(container.state.auto_enabled),
        disable_web_page_preview=True,
    )


@router.message(Command("start", "menu"))
async def cmd_start(message: Message, container: AppContainer) -> None:
    await show_main(message, container)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        "<b>الأوامر</b>\n"
        "/start · القائمة\n"
        "/scan · مسح السوق الآن\n"
        "/status · حالة المصادر\n"
        "/stats · إحصاء الدقة\n"
        "/stop · إيقاف المسح الآلي\n\n"
        "أرسل صورة شارت بعد ضغط «تحليل صورة» للحصول على قراءة بصرية.",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data == "menu:main")
async def cb_menu_main(query: CallbackQuery, container: AppContainer) -> None:
    ready = await container.readiness()
    await query.message.edit_text(  # type: ignore[union-attr]
        texts.welcome(
            __version__,
            ai_ready=ready["ai_ready"],
            forex_ready=ready["forex_ready"],
            otc_ready=ready["otc_ready"],
        ),
        reply_markup=keyboards.main_menu(container.state.auto_enabled),
        disable_web_page_preview=True,
    )
    await query.answer()


@router.callback_query(F.data == "menu:markets")
async def cb_menu_markets(query: CallbackQuery) -> None:
    await query.message.edit_text(  # type: ignore[union-attr]
        "<b>اختر السوق</b>\nكل سوق يستخدم مصدره الحقيقي الخاص.",
        reply_markup=keyboards.markets_menu(),
    )
    await query.answer()
