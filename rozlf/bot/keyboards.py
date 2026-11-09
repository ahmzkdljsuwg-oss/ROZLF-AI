"""Inline keyboards — every button is wired to a real handler."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from ..providers.base import MARKET_FOREX, MARKET_OTC, MARKET_SMARTY, Asset
from ..providers.catalog import assets_for, timeframe_label


def main_menu(auto_enabled: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="1 · تحليل سمارتي", callback_data="m:SMARTY"))
    b.row(InlineKeyboardButton(text="2 · تحليل OTC", callback_data="m:OTC"))
    b.row(InlineKeyboardButton(text="3 · تحليل فوركس", callback_data="m:FOREX"))
    b.row(
        InlineKeyboardButton(text="4 · الماسح الآلي", callback_data="auto:menu"),
        InlineKeyboardButton(text="5 · تحليل صورة", callback_data="img:start"),
    )
    b.row(
        InlineKeyboardButton(text="6 · الإشارات الحية", callback_data="live:list"),
        InlineKeyboardButton(text="7 · سجل الإشارات", callback_data="hist:1"),
    )
    b.row(
        InlineKeyboardButton(text="8 · إحصاء الدقة", callback_data="stats:show"),
        InlineKeyboardButton(text="9 · الإعدادات", callback_data="set:menu"),
    )
    toggle = "إيقاف المسح الآلي" if auto_enabled else "تشغيل المسح الآلي"
    b.row(InlineKeyboardButton(text=f"⚡ {toggle}", callback_data="auto:toggle"))
    return b.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⟵ القائمة الرئيسية", callback_data="menu:main"))
    return b.as_markup()


def markets_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="FOREX · فوركس", callback_data="m:FOREX"))
    b.row(InlineKeyboardButton(text="OTC · أوقات الإغلاق", callback_data="m:OTC"))
    b.row(InlineKeyboardButton(text="SMARTY · سمارتي", callback_data="m:SMARTY"))
    b.row(InlineKeyboardButton(text="⟵ رجوع", callback_data="menu:main"))
    return b.as_markup()


def assets_menu(market: str, page: int = 0, per_page: int = 6) -> InlineKeyboardMarkup:
    items = assets_for(market)
    b = InlineKeyboardBuilder()
    start = page * per_page
    for asset in items[start : start + per_page]:
        b.row(InlineKeyboardButton(text=f"{asset.symbol} · {asset.market}", callback_data=f"a:{market}:{asset.symbol}"))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀ السابق", callback_data=f"p:{market}:{page - 1}"))
    if start + per_page < len(items):
        nav.append(InlineKeyboardButton(text="التالي ▶", callback_data=f"p:{market}:{page + 1}"))
    if nav:
        b.row(*nav)
    b.row(
        InlineKeyboardButton(text="⟵ الأسواق", callback_data="menu:markets"),
        InlineKeyboardButton(text="⌂ القائمة", callback_data="menu:main"),
    )
    return b.as_markup()


def timeframes_menu(asset: Asset) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    frames = asset.timeframes or ()
    for tf in frames:
        b.button(text=timeframe_label(tf), callback_data=f"t:{asset.symbol}:{tf}")
    b.adjust(3)
    b.row(
        InlineKeyboardButton(text="⟵ الأصول", callback_data=f"m:{asset.market}"),
        InlineKeyboardButton(text="⌂ القائمة", callback_data="menu:main"),
    )
    return b.as_markup()


def after_analysis(symbol: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🔄 تحليل فريم آخر", callback_data=f"a:REFRESH:{symbol}"))
    b.row(
        InlineKeyboardButton(text="📊 الإحصائيات", callback_data="stats:show"),
        InlineKeyboardButton(text="⌂ القائمة", callback_data="menu:main"),
    )
    return b.as_markup()


def auto_menu(enabled: bool, interval: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="▶ مسح الآن", callback_data="auto:scan"))
    b.row(
        InlineKeyboardButton(
            text="⏸ إيقاف" if enabled else "▶ تشغيل",
            callback_data="auto:toggle",
        ),
        InlineKeyboardButton(text=f"⏱ كل {interval}ث", callback_data="auto:interval"),
    )
    b.row(InlineKeyboardButton(text="⌂ القائمة", callback_data="menu:main"))
    return b.as_markup()


def expiry_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for seconds, label in ((60, "1m"), (300, "5m"), (900, "15m"), (1800, "30m"), (3600, "1h")):
        b.button(text=label, callback_data=f"set:expiry:{seconds}")
    b.adjust(5)
    b.row(InlineKeyboardButton(text="⟵ الإعدادات", callback_data="set:menu"))
    return b.as_markup()


def history_nav(page: int, has_more: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="◀ الأحدث", callback_data=f"hist:{page - 1}"))
    if has_more:
        nav.append(InlineKeyboardButton(text="الأقدم ▶", callback_data=f"hist:{page + 1}"))
    if nav:
        b.row(*nav)
    b.row(
        InlineKeyboardButton(text="📈 الإحصائيات", callback_data="stats:show"),
        InlineKeyboardButton(text="⌂ القائمة", callback_data="menu:main"),
    )
    return b.as_markup()


def settings_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📡 مصادر البيانات", callback_data="set:sources"))
    b.row(InlineKeyboardButton(text="📦 الكتالوج", callback_data="set:catalog:0"))
    b.row(InlineKeyboardButton(text="🧠 حالة Mistral", callback_data="set:ai"))
    b.row(InlineKeyboardButton(text="⏱ مدة الإشارة", callback_data="set:expiry"))
    b.row(InlineKeyboardButton(text="⌂ القائمة", callback_data="menu:main"))
    return b.as_markup()


def catalog_nav(page: int, has_more: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"set:catalog:{page - 1}"))
    if has_more:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"set:catalog:{page + 1}"))
    if nav:
        b.row(*nav)
    b.row(InlineKeyboardButton(text="⟵ الإعدادات", callback_data="set:menu"))
    return b.as_markup()


def image_prompt() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="⌂ القائمة", callback_data="menu:main"))
    return b.as_markup()


MARKET_ORDER = (MARKET_SMARTY, MARKET_OTC, MARKET_FOREX)
