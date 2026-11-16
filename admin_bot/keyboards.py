"""Owner-only admin bot keyboards."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_home_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ إصدار كود تفعيل", callback_data="adm:new")],
            [
                InlineKeyboardButton(text="📋 الأكواد النشطة", callback_data="adm:codes:avail"),
                InlineKeyboardButton(text="🗂 الأكواد المستخدمة", callback_data="adm:codes:used"),
            ],
            [InlineKeyboardButton(text="👥 الاشتراكات الحالية", callback_data="adm:cust")],
            [InlineKeyboardButton(text="🔎 بحث بواسطة Telegram ID", callback_data="adm:search")],
            [InlineKeyboardButton(text="🔄 تحديث اللوحة", callback_data="adm:home")],
        ]
    )


def duration_menu() -> InlineKeyboardMarkup:
    labels = [
        ("1️⃣ يوم واحد", 1),
        ("2️⃣ 7 أيام", 7),
        ("3️⃣ 30 يوماً", 30),
        ("4️⃣ 90 يوماً", 90),
        ("5️⃣ سنة واحدة", 365),
    ]
    rows = [[InlineKeyboardButton(text=label, callback_data=f"adm:days:{days}")] for label, days in labels]
    rows.append([InlineKeyboardButton(text="🔙 رجوع", callback_data="adm:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def code_created_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ كود آخر", callback_data="adm:new")],
            [
                InlineKeyboardButton(text="📋 الأكواد المتاحة", callback_data="adm:codes:avail"),
                InlineKeyboardButton(text="🏠 اللوحة", callback_data="adm:home"),
            ],
        ]
    )


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ كود جديد", callback_data="adm:new")],
            [InlineKeyboardButton(text="🏠 اللوحة", callback_data="adm:home")],
        ]
    )


def customers_menu(records) -> InlineKeyboardMarkup:
    rows = []
    for record in records[:6]:
        state = "ACTIVE" if record.active else record.status
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"👤 {record.telegram_id} ({state})"[:64],
                    callback_data=f"adm:view:{record.telegram_id}",
                ),
                InlineKeyboardButton(text="⏳ تمديد", callback_data=f"adm:ext:{record.telegram_id}"),
                InlineKeyboardButton(text="🚫 حظر", callback_data=f"adm:ban:{record.telegram_id}"),
            ]
        )
    rows.append([InlineKeyboardButton(text="🏠 اللوحة", callback_data="adm:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def customer_actions_menu(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⏳ تمديد الاشتراك", callback_data=f"adm:ext:{telegram_id}"),
                InlineKeyboardButton(text="🚫 حظر العميل", callback_data=f"adm:ban:{telegram_id}"),
            ],
            [InlineKeyboardButton(text="🗑 إلغاء الاشتراك", callback_data=f"adm:revoke:{telegram_id}")],
            [InlineKeyboardButton(text="🔙 العملاء", callback_data="adm:cust")],
        ]
    )


def extend_duration_menu(telegram_id: int) -> InlineKeyboardMarkup:
    labels = [
        ("➕ يوم", 1),
        ("➕ 7 أيام", 7),
        ("➕ 30 يوماً", 30),
        ("➕ 90 يوماً", 90),
        ("➕ سنة", 365),
    ]
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"adm:extdays:{telegram_id}:{days}")]
        for label, days in labels
    ]
    rows.append([InlineKeyboardButton(text="🔙 رجوع", callback_data=f"adm:view:{telegram_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def revoke_confirm_menu(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ نعم، إلغاء الاشتراك", callback_data=f"adm:revoke:yes:{telegram_id}")],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data=f"adm:view:{telegram_id}")],
        ]
    )


def ban_confirm_menu(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ نعم، حظر نهائي", callback_data=f"adm:ban:yes:{telegram_id}")],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data=f"adm:view:{telegram_id}")],
        ]
    )


def codes_menu(records, status: str = "AVAILABLE") -> InlineKeyboardMarkup:
    rows = []
    if status == "AVAILABLE":
        for record in records[:8]:
            rows.append(
                [InlineKeyboardButton(text=f"🗑 إلغاء الكود #{record.id}", callback_data=f"adm:disable:{record.id}")]
            )
    rows.append(
        [
            InlineKeyboardButton(text="📋 الأكواد النشطة", callback_data="adm:codes:avail"),
            InlineKeyboardButton(text="🏠 اللوحة", callback_data="adm:home"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def search_cancel_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 إلغاء", callback_data="adm:home")]]
    )
