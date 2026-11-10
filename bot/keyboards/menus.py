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


def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button("🧠 SMARTY MARKET", "mkt:SMARTY"), _button("🌐 OTC MARKET", "mkt:OTC"))
    builder.row(_button("💱 FOREX MARKET", "mkt:FOREX"), _button("🥇 GOLD ANALYSIS", "mkt:GOLD"))
    builder.row(_button("🛰 AUTO SCANNER", "scan:menu"), _button("🖼 AI IMAGE ANALYSIS", "img:help"))
    builder.row(_button("📡 LIVE SIGNALS", "live"), _button("🗂 SIGNAL HISTORY", "hist"))
    builder.row(_button("📊 PERFORMANCE STATISTICS", "stats"), _button("⚙️ SETTINGS", "settings"))
    builder.row(_button("🩺 SYSTEM STATUS", "status"))
    return builder.as_markup()


def market_menu(market: Market, assets: list[Asset] | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for asset in assets if assets is not None else assets_for(market):
        builder.button(text=asset.display, callback_data=f"ast:{asset.key}")
    builder.adjust(2)
    builder.row(
        _button("🔄 REFRESH", f"mkt:{market.value}"),
        _button("🏠 MAIN", "menu:main"),
    )
    return builder.as_markup()


# ExpertOption-native expirations that the bridge can verify with quotes:
# 30s, 1m, 2m, 3m and 5m. 5s/15s are not offered by the bridge data feed, so
# they are deliberately not shown.
SMARTY_TRADE_DURATIONS: tuple[int, ...] = (30, 60, 120, 180, 300)


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
        _button("🥇 GOLD " + ("✅" if "GOLD" in markets else "⬜"), "scan:mk:GOLD"),
        _button("🌐 OTC " + ("✅" if "OTC" in markets else "⬜"), "scan:mk:OTC"),
    )
    builder.row(
        _button("🧠 SMARTY " + ("✅" if "SMARTY" in markets else "⬜"), "scan:mk:SMARTY"),
        _button("🔄 UPDATE", "scan:menu"),
    )
    builder.row(_button("🏠 MAIN", "menu:main"))
    return builder.as_markup()


def settings_menu(min_confidence: float, scanner_enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("MIN CONF 60%", "set:min:60"),
        _button("MIN CONF 65%", "set:min:65"),
        _button("MIN CONF 70%", "set:min:70"),
    )
    builder.row(
        _button("MIN CONF 75%", "set:min:75"),
        _button("MIN CONF 80%", "set:min:80"),
        _button("MIN CONF 85%", "set:min:85"),
    )
    builder.row(
        _button(f"SCANNER {'ON ✅' if scanner_enabled else 'OFF ⬜'}", "set:scan"),
        _button("🔄 UPDATE", "settings"),
    )
    builder.row(_button("🏠 MAIN", "menu:main"))
    return builder.as_markup()


def back_only(target: str = "menu:main", label: str = "🏠 MAIN MENU") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button(label, target))
    return builder.as_markup()


def image_help_back() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button("🖼 AI IMAGE ANALYSIS", "img:help"), _button("🏠 MAIN", "menu:main"))
    return builder.as_markup()
