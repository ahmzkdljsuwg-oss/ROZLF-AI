"""Owner-only activation-code and subscription management bot."""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from admin_bot import keyboards
from admin_bot.states import AdminStates
from bot import formatting as fmt
from database.repository import Repository

logger = logging.getLogger(__name__)
router = Router(name="admin")


async def _panel_text(repo: Repository) -> str:
    available = len(await repo.list_codes(status="AVAILABLE"))
    used = len(await repo.list_codes(status="USED"))
    customers = await repo.list_subscriptions()
    active = sum(1 for customer in customers if customer.active)
    return (
        "👑 <b>ROZLF AI — ADMIN PANEL</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"📋 أكواد متاحة: <b>{available}</b>\n"
        f"🗂 أكواد مستخدمة: <b>{used}</b>\n"
        f"👥 عملاء: <b>{len(customers)}</b> — نشطون: <b>{active}</b>\n\n"
        "اختر إجراءً من الأزرار."
    )


async def _edit(callback: CallbackQuery, text: str, keyboard) -> None:
    if callback.message is None:
        return
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, disable_web_page_preview=True)
    except TelegramBadRequest as exc:
        if "not modified" not in str(exc):
            await callback.message.answer(text, reply_markup=keyboard, disable_web_page_preview=True)


@router.message(CommandStart())
@router.message(Command("admin"))
async def cmd_start(message: Message, repo: Repository) -> None:
    await message.answer(await _panel_text(repo), reply_markup=keyboards.admin_home_menu())


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(f"OWNER ID: <code>{message.from_user.id}</code>")


@router.callback_query(F.data == "adm:home")
async def cb_home(callback: CallbackQuery, repo: Repository) -> None:
    await callback.answer()
    await _edit(callback, await _panel_text(repo), keyboards.admin_home_menu())


@router.callback_query(F.data == "adm:new")
async def cb_new(callback: CallbackQuery) -> None:
    await callback.answer()
    await _edit(
        callback,
        "➍ <b>اختر مدة الاشتراك</b>\n"
        "سيتم إنشاء كود عشوائي فريد صالح لتفعيل واحد فقط.",
        keyboards.duration_menu(),
    )


@router.callback_query(F.data.startswith("adm:days:"))
async def cb_days(callback: CallbackQuery, repo: Repository) -> None:
    duration = int(callback.data.split(":", 2)[2])
    if duration not in (1, 7, 30, 90, 365):
        await callback.answer("مدة غير مدعومة", show_alert=True)
        return
    await callback.answer("جارٍ إنشاء الكود…")
    record = await repo.create_activation_code(duration, callback.from_user.id)
    await _edit(callback, fmt.admin_code_text(record), keyboards.code_created_menu())


@router.callback_query(F.data.startswith("adm:codes:"))
async def cb_codes(callback: CallbackQuery, repo: Repository) -> None:
    used = callback.data.endswith("used")
    await callback.answer()
    status = "USED" if used else "AVAILABLE"
    records = await repo.list_codes(status=status)
    await _edit(
        callback,
        fmt.admin_codes_text(records, used=used),
        keyboards.codes_menu(records, status),
    )


@router.callback_query(F.data.startswith("adm:disable:"))
async def cb_disable_code(callback: CallbackQuery, repo: Repository) -> None:
    code_id = int(callback.data.rsplit(":", 1)[1])
    done = await repo.disable_code(code_id)
    await callback.answer("تم إلغاء الكود" if done else "الكود غير متاح للإلغاء", show_alert=True)
    records = await repo.list_codes(status="AVAILABLE")
    await _edit(callback, fmt.admin_codes_text(records, used=False), keyboards.codes_menu(records))


@router.callback_query(F.data == "adm:cust")
async def cb_customers(callback: CallbackQuery, repo: Repository) -> None:
    await callback.answer()
    records = await repo.list_subscriptions()
    await _edit(callback, fmt.admin_customers_text(records), keyboards.customers_menu(records))


@router.callback_query(F.data == "adm:search")
async def cb_search(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(AdminStates.waiting_customer_id)
    await _edit(callback, fmt.admin_search_prompt_text(), keyboards.search_cancel_menu())


@router.message(AdminStates.waiting_customer_id)
async def msg_search_customer(message: Message, repo: Repository, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer("⚠️ أرسل Telegram ID رقمياً فقط.", reply_markup=keyboards.search_cancel_menu())
        return
    telegram_id = int(raw)
    await state.clear()
    record = await repo.subscription_for(telegram_id)
    await message.answer(
        fmt.admin_customer_profile_text(record),
        reply_markup=keyboards.customer_actions_menu(telegram_id),
    )


@router.callback_query(F.data.startswith("adm:view:"))
async def cb_view_customer(callback: CallbackQuery, repo: Repository) -> None:
    telegram_id = int(callback.data.rsplit(":", 1)[1])
    await callback.answer()
    record = await repo.subscription_for(telegram_id)
    await _edit(
        callback,
        fmt.admin_customer_profile_text(record),
        keyboards.customer_actions_menu(telegram_id),
    )


@router.callback_query(F.data.startswith("adm:ext:"))
async def cb_extend(callback: CallbackQuery) -> None:
    telegram_id = int(callback.data.rsplit(":", 1)[1])
    await callback.answer()
    await _edit(
        callback,
        f"⏳ <b>تمديد اشتراك</b> <code>{telegram_id}</code>\nاختر مدة الإضافة:",
        keyboards.extend_duration_menu(telegram_id),
    )


@router.callback_query(F.data.startswith("adm:extdays:"))
async def cb_extend_days(callback: CallbackQuery, repo: Repository) -> None:
    _, _, raw_id, raw_days = callback.data.split(":")
    telegram_id, days = int(raw_id), int(raw_days)
    if days not in (1, 7, 30, 90, 365):
        await callback.answer("مدة غير مدعومة", show_alert=True)
        return
    record = await repo.extend_subscription(telegram_id, days)
    if record is None:
        await callback.answer("لا يمكن تمديد هذا الحساب", show_alert=True)
        return
    await callback.answer(f"تمت إضافة {days} يوم")
    await _edit(
        callback,
        "✅ <b>تم تمديد الاشتراك</b>\n\n" + fmt.admin_customer_profile_text(record),
        keyboards.customer_actions_menu(telegram_id),
    )


@router.callback_query(F.data.startswith("adm:ban:"))
async def cb_ban(callback: CallbackQuery, repo: Repository) -> None:
    parts = callback.data.split(":")
    if len(parts) == 4 and parts[2] == "yes":
        telegram_id = int(parts[3])
        done = await repo.ban_subscription(telegram_id)
        await callback.answer("تم الحظر" if done else "غير موجود", show_alert=True)
        record = await repo.subscription_for(telegram_id)
        await _edit(
            callback,
            ("🚫 <b>تم حظر العميل ومنع جميع صلاحياته</b>\n\n" if done else "⚠️ <b>العميل غير موجود</b>\n\n")
            + fmt.admin_customer_profile_text(record),
            keyboards.customer_actions_menu(telegram_id),
        )
        return
    telegram_id = int(parts[2])
    await callback.answer()
    await _edit(
        callback,
        f"⚠️ هل تريد حظر <code>{telegram_id}</code> نهائياً؟\n"
        "سيتوقف التحليل فوراً ولن يستطيع تفعيل أي كود جديد.",
        keyboards.ban_confirm_menu(telegram_id),
    )


@router.callback_query(F.data.startswith("adm:revoke:"))
async def cb_revoke(callback: CallbackQuery, repo: Repository) -> None:
    parts = callback.data.split(":")
    if len(parts) == 4 and parts[2] == "yes":
        telegram_id = int(parts[3])
        done = await repo.revoke_subscription(telegram_id)
        await callback.answer("تم الإلغاء" if done else "غير موجود", show_alert=True)
        records = await repo.list_subscriptions()
        await _edit(
            callback,
            ("✅ <b>تم إلغاء الاشتراك</b>\n" if done else "⚠️ <b>العميل غير موجود</b>\n")
            + f"<code>{telegram_id}</code>\n\n"
            + fmt.admin_customers_text(records),
            keyboards.customers_menu(records),
        )
        return
    telegram_id = int(parts[2])
    await callback.answer()
    await _edit(
        callback,
        f"⚠️ هل تريد إلغاء اشتراك <code>{telegram_id}</code>؟\n"
        "سيتوقف التحليل لهذا المستخدم فوراً.",
        keyboards.revoke_confirm_menu(telegram_id),
    )
