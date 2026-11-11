"""Inline keyboard builders. Every button maps to a real callback handler."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from engines.signals.generator import DURATION_LABELS, supported_durations
from providers.catalog import Asset, Market, assets_for, timeframe


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def back_to_main() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button("🏠 MAIN MENU", "menu:main"), _button("🔄 REFRESH", "menu:refresh"))
    return builder.as_markup()


INDEX_MARKETS: tuple[Market, ...] = (
    Market.FOOTBALL, Market.SMARTY, Market.LUXURY, Market.AI, Market.CRICKET,
)


MARKET_BUTTONS: tuple[tuple[str, str], ...] = (
    ("🧠 SMARTY MARKET", "mkt:SMARTY"),
    ("⚽ FOOTBALL INDEX", "mkt:FOOTBALL"),
    ("💎 LUXURY INDEX", "mkt:LUXURY"),
    ("🤖 AI INDEX", "mkt:AI"),
    ("🏏 CRICKET INDEX", "mkt:CRICKET"),
    ("💱 FOREX MARKET", "mkt:FOREX"),
)


def main_menu() -> InlineKeyboardMarkup:
    """القائمة الرئيسية — 3 أزرار كبيرة."""
    builder = InlineKeyboardBuilder()
    builder.row(_button("📉 ANALYSIS", "menu:analysis"))
    builder.row(_button("⚙️ SETTINGS", "settings"))
    builder.row(_button("🏆 RECOMMENDATIONS", "menu:recommendations"))
    return builder.as_markup()


def analysis_menu() -> InlineKeyboardMarkup:
    """قائمة الأسواق الستة بأسمائها الكاملة."""
    builder = InlineKeyboardBuilder()
    builder.row(_button("🧠 SMARTY MARKET", "mkt:SMARTY"))
    builder.row(_button("⚽ FOOTBALL INDEX", "mkt:FOOTBALL"))
    builder.row(_button("💎 LUXURY INDEX", "mkt:LUXURY"))
    builder.row(_button("🤖 AI INDEX", "mkt:AI"))
    builder.row(_button("🏏 CRICKET INDEX", "mkt:CRICKET"))
    builder.row(_button("💱 FOREX MARKET", "mkt:FOREX"))
    builder.row(_button("🔙 BACK", "menu:main"))
    return builder.as_markup()


def markets_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index in range(0, len(MARKET_BUTTONS), 2):
        builder.row(*[_button(text, data) for text, data in MARKET_BUTTONS[index:index + 2]])
    builder.row(_button("🏠 MAIN MENU", "menu:main"))
    return builder.as_markup()


def trend_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button("📈 تحديث ملخص الترند", "trend:refresh"))
    builder.row(_button("🏠 الرئيسية", "menu:main"))
    return builder.as_markup()


def market_menu(market: Market, assets: list[Asset] | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for asset in assets if assets is not None else assets_for(market):
        builder.button(text=f"🎯 {asset.display}", callback_data=f"pick:{asset.key}")
    builder.adjust(1)
    builder.row(
        _button("🔄 REFRESH", f"mkt:{market.value}"),
        _button("🌐 MARKETS", "markets"),
        _button("🏠 MAIN", "menu:main"),
    )
    return builder.as_markup()


def duration_method_menu(asset: Asset) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button("🤖 SMART DURATION · BOT SELECTS", f"dur:auto:{asset.key}"))
    builder.row(_button("✋ MANUAL DURATION · I SELECT", f"dur:manual:{asset.key}"))
    builder.row(
        _button("🔙 BACK", f"mkt:{asset.market.value}"),
        _button("🏠 MAIN", "menu:main"),
    )
    return builder.as_markup()


def manual_duration_menu(asset: Asset, durations: list[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for seconds in durations:
        builder.button(
            text=f"⚡ {DURATION_LABELS.get(seconds, f'{seconds}s')}",
            callback_data=f"md:{asset.key}:{seconds}",
        )
    builder.adjust(3)
    builder.row(
        _button("🔙 DURATION MODE", f"pick:{asset.key}"),
        _button("🏠 MAIN", "menu:main"),
    )
    return builder.as_markup()


# ExpertOption-native expirations that the bridge can verify with quotes:
# 30s, 1m, 2m, 3m and 5m. 5s/15s are not offered by the bridge data feed, so
# they are deliberately not shown.
SMARTY_TRADE_DURATIONS: tuple[int, ...] = (5, 15, 30, 45, 60, 105, 300)


def smarty_assets_menu(assets: list[Asset]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for asset in assets:
        builder.button(text=f"🎯 {asset.display}", callback_data=f"sa:{asset.key}")
    builder.adjust(1)
    builder.row(
        _button("🔄 REFRESH", "mkt:SMARTY"),
        _button("🏠 MAIN", "menu:main"),
    )
    return builder.as_markup()


def smarty_menu(asset: Asset, durations: tuple[int, ...] | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for seconds in durations or SMARTY_TRADE_DURATIONS:
        builder.button(
            text=f"⚡ {DURATION_LABELS[seconds]}",
            callback_data=f"sm:{asset.key}:{seconds}",
        )
    builder.adjust(2)
    builder.row(
        _button("🔙 ASSETS", "mkt:SMARTY"),
        _button("🏠 MAIN", "menu:main"),
    )
    return builder.as_markup()


def index_assets_menu(market: Market, assets: list[Asset]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for asset in assets:
        builder.button(text=f"🎯 {asset.display}", callback_data=f"ia:{asset.key}")
    builder.adjust(1)
    builder.row(
        _button("🔄 REFRESH", f"mkt:{market.value}"),
        _button("🏠 MAIN", "menu:main"),
    )
    return builder.as_markup()


def index_menu(asset: Asset, durations: tuple[int, ...] | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for seconds in durations or SMARTY_TRADE_DURATIONS:
        builder.button(
            text=f"⚡ {DURATION_LABELS[seconds]}",
            callback_data=f"ix:{asset.key}:{seconds}",
        )
    builder.adjust(2)
    builder.row(
        _button("🔙 ASSETS", f"mkt:{asset.market.value}"),
        _button("🏠 MAIN", "menu:main"),
    )
    return builder.as_markup()


def unavailable_menu(market: Market) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("🔄 RETRY", f"mkt:{market.value}"),
        _button("🏠 MAIN", "menu:main"),
    )
    return builder.as_markup()


def asset_menu(asset: Asset) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    frames = ("1min", "5min", "15min", "30min", "1h")
    for code in frames:
        builder.button(text=TIMEFRAME_LABELS[code], callback_data=f"tf:{asset.key}:{code}")
    builder.adjust(2, 2, 1)
    builder.row(
        _button("🔙 BACK", f"mkt:{asset.market.value}"),
        _button("🏠 MAIN", "menu:main"),
    )
    return builder.as_markup()


TIMEFRAME_LABELS = {
    "1min": "⏱ M1",
    "5min": "⏱ M5",
    "15min": "⏱ M15",
    "30min": "⏱ M30",
    "1h": "⏱ H1",
}


def analysis_actions(asset: Asset, frame_code: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    tf = timeframe(frame_code)
    for duration in supported_durations(asset, tf):
        builder.button(
            text=f"⚡ {DURATION_LABELS[duration]}",
            callback_data=f"sg:{asset.key}:{frame_code}:{duration}",
        )
    builder.adjust(3)
    builder.row(
        _button("🔄 RE-ANALYSE", f"an:{asset.key}:{frame_code}"),
        _button("🔙 BACK", f"ast:{asset.key}"),
    )
    return builder.as_markup()


def scanner_menu(running: bool, markets: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("⏹ STOP SCANNER" if running else "▶️ START SCANNER", "scan:toggle"),
        _button("⚡ SCAN NOW", "scan:now"),
    )
    builder.row(
        _button("💱 FOREX " + ("✅" if "FOREX" in markets else "⬜"), "scan:mk:FOREX"),
        _button("🧠 SMARTY " + ("✅" if "SMARTY" in markets else "⬜"), "scan:mk:SMARTY"),
    )
    builder.row(
        _button("🤖 AI " + ("✅" if "AI" in markets else "⬜"), "scan:mk:AI"),
        _button("⚽ FOOTBALL " + ("✅" if "FOOTBALL" in markets else "⬜"), "scan:mk:FOOTBALL"),
    )
    builder.row(
        _button("💎 LUXURY " + ("✅" if "LUXURY" in markets else "⬜"), "scan:mk:LUXURY"),
        _button("🏏 CRICKET " + ("✅" if "CRICKET" in markets else "⬜"), "scan:mk:CRICKET"),
    )
    builder.row(_button("🔄 UPDATE", "scan:menu"))
    builder.row(_button("🏠 MAIN", "menu:main"))
    return builder.as_markup()


def settings_menu(min_confidence: float, scanner_enabled: bool) -> InlineKeyboardMarkup:
    """إعدادات الثقة من 50% إلى 90%."""
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("50%" + (" ✅" if min_confidence == 50 else ""), "set:min:50"),
        _button("55%" + (" ✅" if min_confidence == 55 else ""), "set:min:55"),
        _button("60%" + (" ✅" if min_confidence == 60 else ""), "set:min:60"),
    )
    builder.row(
        _button("65%" + (" ✅" if min_confidence == 65 else ""), "set:min:65"),
        _button("70%" + (" ✅" if min_confidence == 70 else ""), "set:min:70"),
        _button("75%" + (" ✅" if min_confidence == 75 else ""), "set:min:75"),
    )
    builder.row(
        _button("80%" + (" ✅" if min_confidence == 80 else ""), "set:min:80"),
        _button("85%" + (" ✅" if min_confidence == 85 else ""), "set:min:85"),
        _button("90%" + (" ✅" if min_confidence == 90 else ""), "set:min:90"),
    )
    builder.row(
        _button(f"SCANNER {'ON ✅' if scanner_enabled else 'OFF ⬜'}", "set:scan"),
        _button("🔄 UPDATE", "settings"),
    )
    builder.row(_button("🏠 MAIN MENU", "menu:main"))
    return builder.as_markup()


def back_only(target: str = "menu:main", label: str = "🏠 MAIN MENU") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button(label, target))
    return builder.as_markup()
