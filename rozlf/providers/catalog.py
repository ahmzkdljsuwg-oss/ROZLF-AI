"""Static asset catalog.

Identifiers come from the platform documentation and previously verified
account listings. Anything marked ``note`` must be re-checked against the live
asset list before it is trusted for OTC/SMARTY analysis.
"""

from __future__ import annotations

from ..providers.base import MARKET_FOREX, MARKET_OTC, MARKET_SMARTY, Asset

TIMEFRAMES: dict[str, int] = {
    "S30": 30,
    "M1": 60,
    "M2": 120,
    "M3": 180,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
}

TIMEFRAME_LABELS: dict[int, str] = {
    30: "30 ثانية",
    60: "دقيقة",
    120: "دقيقتان",
    180: "3 دقائق",
    300: "5 دقائق",
    900: "15 دقيقة",
    1800: "30 دقيقة",
    3600: "ساعة",
}

TWELVE_TIMEFRAMES: tuple[int, ...] = (60, 300, 900, 1800, 3600)
DAILY_TIMEFRAMES: tuple[int, ...] = ()
BRIDGE_TIMEFRAMES: tuple[int, ...] = (30, 60, 120, 180, 300, 900, 1800, 3600)

FOREX_SYMBOLS: tuple[tuple[str, str], ...] = (
    ("EURUSD", "EUR/USD"),
    ("GBPUSD", "GBP/USD"),
    ("USDJPY", "USD/JPY"),
    ("AUDUSD", "AUD/USD"),
    ("USDCAD", "USD/CAD"),
    ("NZDUSD", "NZD/USD"),
    ("USDCHF", "USD/CHF"),
    ("XAUUSD", "الذهب XAU/USD"),
)

SMARTY_ASSETS: tuple[tuple[str, str, str], ...] = (
    ("SMRTY", "Smarty", "240"),
    ("CRICKET", "Cricket Index", "276"),
    ("FOOTBALL", "Football Index", "278"),
    ("AIIDX", "AI Index", "285"),
    ("LUXURY", "Luxury Index", "286"),
)


def _forex() -> list[Asset]:
    return [
        Asset(symbol=sym, name=name, market=MARKET_FOREX, provider="twelvedata", timeframes=TWELVE_TIMEFRAMES)
        for sym, name in FOREX_SYMBOLS
    ]


def _otc() -> list[Asset]:
    return [
        Asset(
            symbol=f"{sym}-OTC",
            name=f"{name} OTC",
            market=MARKET_OTC,
            provider="expertoption",
            source_id=sym,
            timeframes=BRIDGE_TIMEFRAMES,
            note="تحتاج جلسة ExpertOption حقيقية عبر الجسر.",
        )
        for sym, name in FOREX_SYMBOLS
    ]


def _smarty() -> list[Asset]:
    return [
        Asset(
            symbol=sym,
            name=name,
            market=MARKET_SMARTY,
            provider="expertoption",
            source_id=sid,
            timeframes=BRIDGE_TIMEFRAMES,
            note="المعرّف أولي ويجب مطابقته بالقائمة الفعلية للحساب.",
        )
        for sym, name, sid in SMARTY_ASSETS
    ]


ASSETS: tuple[Asset, ...] = tuple(_forex() + _otc() + _smarty())

_BY_SYMBOL = {a.symbol: a for a in ASSETS}


def all_assets() -> tuple[Asset, ...]:
    return ASSETS


def assets_for(market: str) -> tuple[Asset, ...]:
    market = market.upper()
    return tuple(a for a in ASSETS if a.market == market)


def find(symbol: str) -> Asset | None:
    return _BY_SYMBOL.get(symbol.upper())


def timeframe_label(seconds: int) -> str:
    return TIMEFRAME_LABELS.get(seconds, f"{seconds}s")


def market_label(market: str) -> str:
    return {
        MARKET_FOREX: "FOREX",
        MARKET_OTC: "OTC",
        MARKET_SMARTY: "SMARTY",
    }.get(market.upper(), market.upper())
