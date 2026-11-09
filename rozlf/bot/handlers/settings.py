from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ...services.container import AppContainer
from .. import keyboards, texts
from ..utils import edit_or_send

log = logging.getLogger(__name__)
router = Router(name="settings")

CATALOG_PER_PAGE = 6


@router.callback_query(F.data == "set:menu")
async def cb_settings(query: CallbackQuery, container: AppContainer) -> None:
    text = (
        "<b>الإعدادات</b>\n\n"
        f"Mistral: {'مضبوط' if container.ai.configured else 'غير مضبوط'}\n"
        f"Telegram target: {'مضبوط' if container.notifier.enabled else 'غير مضبوط'}\n"
        f"delivery: {container.settings.delivery_mode}\n"
        f"مدة الإشارة الافتراضية: {container.settings.default_expiry_seconds} ثانية\n\n"
        "كل الميزات متاحة، ولا توجد ميزة مقفلة."
    )
    await edit_or_send(query.message, text, keyboards.settings_menu())  # type: ignore[arg-type]
    await query.answer()


@router.callback_query(F.data == "set:sources")
async def cb_sources(query: CallbackQuery, container: AppContainer) -> None:
    statuses = await container.registry.statuses()
    markets = await container.registry.market_overview()
    await edit_or_send(  # type: ignore[arg-type]
        query.message, texts.sources_block(statuses, markets), keyboards.back_to_menu()
    )
    await query.answer()


@router.callback_query(F.data.startswith("set:catalog:"))
async def cb_catalog(query: CallbackQuery, container: AppContainer) -> None:
    page = int((query.data or "set:catalog:0").split(":")[2])
    rows = container.registry.catalog_rows()
    has_more = (page + 1) * CATALOG_PER_PAGE < len(rows)
    await edit_or_send(  # type: ignore[arg-type]
        query.message,
        texts.catalog_block(rows, page, CATALOG_PER_PAGE),
        keyboards.catalog_nav(page, has_more),
    )
    await query.answer()


@router.callback_query(F.data == "set:ai")
async def cb_ai(query: CallbackQuery, container: AppContainer) -> None:
    s = container.settings
    text = (
        "<b>Mistral AI</b>\n\n"
        f"الحالة: {'مضبوط' if container.ai.configured else 'غير مضبوط (MISTRAL_API_KEY)'}\n"
        f"موديل النص: <code>{s.mistral_model}</code>\n"
        f"موديل الصور: <code>{s.mistral_vision_model}</code>\n"
        f"دعم الصور مُتحقق: {'نعم' if container.ai.supports_vision() else 'لا — لن تُرسل الصور'}\n\n"
        "إذا تعطل Mistral يستمر التحليل الفني المحلي، ويُذكر بوضوح أنه ليس تحليل Mistral."
    )
    await edit_or_send(query.message, text, keyboards.back_to_menu())  # type: ignore[arg-type]
    await query.answer()


@router.callback_query(F.data == "set:expiry")
async def cb_expiry_menu(query: CallbackQuery, container: AppContainer) -> None:
    await edit_or_send(  # type: ignore[arg-type]
        query.message,
        f"<b>مدة الإشارة</b>\nالحالي: {container.settings.default_expiry_seconds} ثانية\n"
        "تُقترح المدة تلقائياً بحيث تغطي الفريم المستخدم.",
        keyboards.expiry_menu(),
    )
    await query.answer()


@router.callback_query(F.data.startswith("set:expiry:"))
async def cb_expiry_set(query: CallbackQuery, container: AppContainer) -> None:
    seconds = int((query.data or "set:expiry:300").split(":")[2])
    container.settings.default_expiry_seconds = seconds
    await query.answer(f"تم التعيين: {seconds} ثانية")


@router.message(Command("status"))
async def cmd_status(message: Message, container: AppContainer) -> None:
    statuses = await container.registry.statuses()
    markets = await container.registry.market_overview()
    await message.answer(texts.sources_block(statuses, markets), reply_markup=keyboards.back_to_menu())
