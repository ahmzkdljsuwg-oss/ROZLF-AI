"""Inline keyboard builders. Every button maps to a real callback handler."""
from __future__ import annotations

import re
from collections.abc import Iterable

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from engines.signals.generator import DURATION_LABELS, supported_durations
from providers.catalog import Asset, Market, assets_for, timeframe


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def back_to_main() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button("🏠 الرئيسية", "nx:home"), _button("🛠 أدوات إضافية", "nx:more"))
    return builder.as_markup()


INDEX_MARKETS: tuple[Market, ...] = (
    Market.FOOTBALL, Market.SMARTY, Market.LUXURY, Market.AI, Market.CRICKET,
)


MT5_DURATIONS: tuple[int, ...] = (60, 300, 900, 1800, 3600)


MT5_DURATION_LABELS: dict[int, str] = {
    60: "⏱️ 1 MINUTE",
    300: "⏱️ 5 MINUTES",
    900: "⏱️ 15 MINUTES",
    1800: "⏱️ 30 MINUTES",
    3600: "⏱️ 1 HOUR",
}


TRADE_DURATION_LABELS: dict[int, str] = {
    30: "⏱️ 30 SECONDS",
    60: "⏱️ 1 MINUTE",
    120: "⏱️ 2 MINUTES",
    180: "⏱️ 3 MINUTES",
    300: "⏱️ 5 MINUTES",
}


NEXUS_MENU_VERSION = "TELEGRAM-CLASSIC-2"

NEXUS_MARKET_ORDER: tuple[tuple[str, str], ...] = (
    ("Football Index ⚽", "nx:market:FOOTBALL"),
    ("Smarty 🧠", "nx:classic:smarty"),
    ("Gold 🪙", "nx:market:GOLD"),
    ("OTC 🌙", "nx:market:OTC"),
    ("Luxury Index 💎", "nx:market:LUXURY"),
    ("AI Index 🤖", "nx:market:AI"),
    ("Cricket Index 🏏", "nx:market:CRICKET"),
    ("Forex 💱", "nx:market:FOREX"),
    ("MT5 📈", "mt5:list"),
)

# Video order, using only matches from the active bridge inventory.
_CLASSIC_ASSETS = (
    ("USD/NGN (OTC) 🇳🇬", ("USDNGN",)),
    ("EUR/USD (OTC) 🇪🇺", ("EURUSD",)),
    ("GBP/USD (OTC) 🇬🇧", ("GBPUSD",)),
    ("USD/JPY (OTC) 🇯🇵", ("USDJPY",)),
    ("Silver ⚪", ("SILVER", "XAGUSD", "XAG")),
    ("Bitcoin/USD ⚡", ("BITCOINUSD", "BTCUSD", "BITCOIN", "BTC")),
    ("Ethereum/USD 💎", ("ETHEREUMUSD", "ETHUSD", "ETHEREUM", "ETH")),
    ("Apple 🍎", ("APPLE", "APPLEINC", "AAPL")),
    ("Google 🔍 (Alphabet)", ("GOOGLE", "ALPHABET", "GOOGLEALPHABET", "GOOG", "GOOGL")),
    ("Facebook 👤", ("FACEBOOK", "META", "METAPLATFORMS", "FB")),
    ("Amazon 📦", ("AMAZON", "AMAZONCOM", "AMZN")),
    ("Tesla 🚗", ("TESLA", "TESLAINC", "TSLA")),
    ("Brent Oil 🛢️", ("BRENTOIL", "BRENT", "UKOIL", "XBRUSD")),
    ("EUR/JPY 💵", ("EURJPY",)),
    ("AUD/CAD 🇦🇺", ("AUDCAD",)),
    ("Intel (OTC) 💻", ("INTEL", "INTELCORP", "INTC")),
    ("Netflix 🎬", ("NETFLIX", "NFLX")),
    ("Boeing ✈️", ("BOEING", "THEBOEINGCOMPANY", "BA")),
    ("McDonald's 🍔", ("MCDONALDS", "MCD")),
)


def _classic_key(value: str) -> str:
    value = re.sub(r"\bOTC\b(?:[ _.-]+[RD])?", "", value.upper().replace("_", " "))
    value = re.sub(r"OTC$", "", value)
    return re.sub(r"[^A-Z0-9]", "", value)


def _classic_asset_labels(assets: Iterable[Asset]) -> dict[str, Asset]:
    by_key: dict[str, Asset] = {}
    for asset in assets:
        if asset.market is not Market.OTC:
            continue
        for value in (asset.symbol, asset.name, asset.bridge_symbol):
            if value:
                by_key.setdefault(_classic_key(value), asset)
    result: dict[str, Asset] = {}
    for label, aliases in _CLASSIC_ASSETS:
        for alias in aliases:
            if alias in by_key:
                result[label] = by_key[alias]
                break
    return result


def nexus_favorite(index: int, assets: Iterable[Asset]) -> tuple[str, Asset | None]:
    label, _ = _CLASSIC_ASSETS[index]
    return label, _classic_asset_labels(assets).get(label)


def nexus_home_menu(chat=None) -> InlineKeyboardMarkup:
    rows = [[_button("ابدأ استلام الإشارات 🚀", "nx:analyse")]]
    url = settings.mini_app_link
    if url and getattr(chat, "type", None) == "private":
        rows.append([InlineKeyboardButton(text="Mini App ⚡", web_app=WebAppInfo(url=url))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nexus_markets_menu(
    otc_assets: Iterable[Asset] = (), available: set[str] | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    def add(label: str, data: str) -> None:
        if available is None or data in available:
            builder.row(_button(label, data))

    for label, data in NEXUS_MARKET_ORDER[:2]:
        add(label, data)
    verified_otc = _classic_asset_labels(otc_assets)
    for index, (label, _) in enumerate(_CLASSIC_ASSETS):
        if index == 4:
            add(*NEXUS_MARKET_ORDER[2])
        if label in verified_otc or (label == "EUR/JPY 💵" and
                                     (available is None or "nx:market:FOREX" in available)):
            builder.row(_button(label, f"nx:favorite:{index}"))
    for label, data in NEXUS_MARKET_ORDER[3:]:
        add(label, data)
    builder.row(_button("أدوات إضافية 🛠️", "nx:more"))
    return builder.as_markup()


def nexus_assets_menu(market: Market, assets, page: int = 0, per_page: int = 20) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    start = page * per_page
    classic_labels = {asset.key: label for label, asset in _classic_asset_labels(assets).items()}
    for index, asset in enumerate(assets[start:start + per_page], start=start):
        label = asset.name or asset.symbol
        if asset.name and asset.name.upper() != asset.symbol.upper():
            label = f"{asset.name} · {asset.symbol}"
        builder.row(_button(classic_labels.get(asset.key, label), f"nx:pick:{market.value.upper()}:{index}"))
    nav = []
    if page > 0:
        nav.append(_button("⬅️ السابق", f"nx:assets:{market.value.upper()}:{page - 1}"))
    if start + per_page < len(assets):
        nav.append(_button("التالي ➡️", f"nx:assets:{market.value.upper()}:{page + 1}"))
    if nav:
        builder.row(*nav)
    builder.row(_button("🔙 الأسواق", "nx:analyse"), _button("🏠 الرئيسية", "nx:home"))
    return builder.as_markup()


def nexus_result_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button("خذ صفقة أخرى 🔄", "nx:analyse"))
    return builder.as_markup()


def nexus_market_tools_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button("🔙 الأسواق", "nx:analyse"), _button("🏠 الرئيسية", "nx:home"))
    return builder.as_markup()


NEXUS_TOOL_BUTTONS: tuple[tuple[str, str], ...] = (
    ("🤖 AUTO SCANNER", "scan:menu"),
    ("🖼️ AI IMAGE ANALYSIS", "image:info"),
    ("📡 LIVE SIGNALS", "live"),
    ("🕘 SIGNAL HISTORY", "hist"),
    ("📊 PERFORMANCE STATISTICS", "stats"),
    ("⚙️ SETTINGS", "settings"),
    ("🖥️ SYSTEM STATUS", "status"),
)


def nexus_tools_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index in range(0, len(NEXUS_TOOL_BUTTONS), 2):
        builder.row(*[_button(text, data) for text, data in NEXUS_TOOL_BUTTONS[index:index + 2]])
    builder.row(_button("⚡ سريع", "nx:mode:fast"), _button("🎯 قوي", "nx:mode:pro"))
    builder.row(_button("🔙 الأسواق", "nx:analyse"), _button("🏠 الرئيسية", "nx:home"))
    return builder.as_markup()


def trade_duration_menu(asset: Asset, durations: list[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for seconds in durations:
        builder.button(
            text=TRADE_DURATION_LABELS.get(seconds, f"⏱️ {DURATION_LABELS.get(seconds, f'{seconds}s')}"),
            callback_data=f"td:{asset.key}:{seconds}",
        )
    builder.adjust(2)
    if durations:
        builder.row(_button("🧠 ANALYZE TRADE TIME", f"td:smart:{asset.key}"))
    builder.row(
        _button("🔙 BACK", "menu:analysis"),
        _button("🏠 MAIN MENU", "nx:home"),
    )
    return builder.as_markup()


def trend_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button("📈 تحديث ملخص الترند", "trend:refresh"))
    builder.row(_button("🏠 الرئيسية", "nx:home"))
    return builder.as_markup()


def market_menu(market: Market, assets: list[Asset] | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for asset in assets if assets is not None else assets_for(market):
        builder.button(text=f"🎯 {asset.display}", callback_data=f"pick:{asset.key}")
    builder.adjust(1)
    if market is Market.FOREX:
        builder.row(_button("📊 MT5 MARKET ANALYSIS", "mt5:list"))
    builder.row(
        _button("🔄 REFRESH", f"mkt:{market.value}"),
        _button("🌐 MARKETS", "markets"),
        _button("🏠 الرئيسية", "nx:home"),
    )
    return builder.as_markup()


def duration_method_menu(asset: Asset) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button("🤖 SMART DURATION · BOT SELECTS", f"dur:auto:{asset.key}"))
    builder.row(_button("✋ MANUAL DURATION · I SELECT", f"dur:manual:{asset.key}"))
    builder.row(
        _button("🔙 BACK", f"mkt:{asset.market.value}"),
        _button("🏠 الرئيسية", "nx:home"),
    )
    return builder.as_markup()


def signal_result_menu(asset: Asset, frame_code: str, has_details: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_details:
        builder.row(_button("🔍 WHY THIS SIGNAL", f"whyd:{asset.key}:{frame_code}"))
    builder.row(_button("🔄 RE-ANALYSE", f"an:{asset.key}:{frame_code}"))
    builder.row(
        _button("🔙 BACK", f"ast:{asset.key}"),
        _button("🏠 MAIN MENU", "nx:home"),
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
        _button("🏠 الرئيسية", "nx:home"),
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
        _button("🏠 الرئيسية", "nx:home"),
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
        _button("🏠 الرئيسية", "nx:home"),
    )
    return builder.as_markup()


def index_assets_menu(market: Market, assets: list[Asset]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for asset in assets:
        builder.button(text=f"🎯 {asset.display}", callback_data=f"ia:{asset.key}")
    builder.adjust(1)
    if market is Market.FOREX:
        builder.row(_button("📊 MT5 MARKET ANALYSIS", "mt5:list"))
    builder.row(
        _button("🔄 REFRESH", f"mkt:{market.value}"),
        _button("🏠 الرئيسية", "nx:home"),
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
        _button("🏠 الرئيسية", "nx:home"),
    )
    return builder.as_markup()


def unavailable_menu(market: Market) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("🔄 RETRY", f"mkt:{market.value}"),
        _button("🏠 الرئيسية", "nx:home"),
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
        _button("🏠 الرئيسية", "nx:home"),
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


def scanner_menu(running: bool, markets: list[str], *, can_manage: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("⏹ إيقاف التوصيات" if running else "▶️ تشغيل التوصيات", "scan:toggle"),
        _button("⚡ فحص الآن", "scan:now"),
    )
    if can_manage:
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
        builder.row(
            _button("💱 OTC " + ("✅" if "OTC" in markets else "⬜"), "scan:mk:OTC"),
            _button("🥇 GOLD " + ("✅" if "GOLD" in markets else "⬜"), "scan:mk:GOLD"),
        )
    builder.row(_button("🔄 تحديث", "scan:menu"))
    builder.row(_button("🏠 الرئيسية", "nx:home"))
    return builder.as_markup()


def settings_menu(min_confidence: float, scanner_enabled: bool = False) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    values = (50, 60, 70, 80, 90)
    for value in values:
        mark = "✅ " if abs(min_confidence - value) < 1 else ""
        builder.button(text=f"{mark}{value}%", callback_data=f"set:pick:{value}")
    builder.adjust(3)
    builder.row(_button("💾 SAVE SETTINGS", "set:save"))
    builder.row(_button("🔙 BACK", "nx:home"), _button("🏠 MAIN MENU", "nx:home"))
    return builder.as_markup()


def back_only(target: str = "nx:home", label: str = "🏠 MAIN MENU") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button(label, target))
    return builder.as_markup()


def mt5_pairs_menu(assets: list[Asset], page: int = 0, per_page: int = 20) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    pages = max(1, (len(assets) + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    start = page * per_page
    for asset in assets[start:start + per_page]:
        builder.button(text=f"🎯 {asset.symbol}", callback_data=f"mt5p:{asset.key}")
    builder.adjust(2)
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(_button("⬅️ PREV", f"mt5:page:{page - 1}"))
        nav.append(_button(f"{page + 1}/{pages}", "mt5:noop"))
        if page + 1 < pages:
            nav.append(_button("NEXT ➡️", f"mt5:page:{page + 1}"))
        builder.row(*nav)
    builder.row(
        _button("🔄 REFRESH", "mt5:list"),
        _button("🏠 الرئيسية", "nx:home"),
    )
    return builder.as_markup()


def mt5_duration_menu(asset: Asset) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for seconds in MT5_DURATIONS:
        builder.button(text=MT5_DURATION_LABELS[seconds], callback_data=f"mt5d:{asset.key}:{seconds}")
    builder.adjust(2)
    builder.row(
        _button("🔙 BACK", "mt5:list"),
        _button("🏠 الرئيسية", "nx:home"),
    )
    return builder.as_markup()


def mt5_result_menu(asset: Asset) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button("🔄 RE-ANALYSE", f"mt5p:{asset.key}"))
    builder.row(
        _button("🔙 PAIRS", "mt5:list"),
        _button("🏠 الرئيسية", "nx:home"),
    )
    return builder.as_markup()
