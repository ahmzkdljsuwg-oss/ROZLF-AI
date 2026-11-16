"""Owner-only admin bot keyboards."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def admin_home_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ إنشاء كود تفعيل", callback_data="adm:new")],
            [
                InlineKeyboardButton(text="📋 الأكواد المتاحة", callback_data="adm:codes:avail"),
                InlineKeyboardButton(text="🗂 الأكواد المستخدمة", callback_data="adm:codes:used"),
            ],
            [InlineKeyboardButton(text="👥 العملاء والاشتراكات", callback_data="adm:cust")],
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
    for record in records[:10]:
        state = "ACTIVE" if record.active else record.status
        label = f"🚫 إلغاء {record.telegram_id} ({state})"
        rows.append([InlineKeyboardButton(text=label[:64], callback_data=f"adm:revoke:{record.telegram_id}")])
    rows.append([InlineKeyboardButton(text="🏠 اللوحة", callback_data="adm:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def revoke_confirm_menu(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ نعم، إلغاء الاشتراك", callback_data=f"adm:revoke:yes:{telegram_id}")],
            [InlineKeyboardButton(text="🔙 رجوع", callback_data="adm:cust")],
        ]
    )
