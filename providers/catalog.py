"""Static market catalogue. Only symbols listed here can be analysed."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Market(str, Enum):
    FOREX = "forex"
    MT5 = "mt5"
    GOLD = "gold"
    OTC = "otc"
    SMARTY = "smarty"
    AI = "ai"
    FOOTBALL = "football"
    LUXURY = "luxury"
    CRICKET = "cricket"

    @property
    def label(self) -> str:
        return {
            Market.FOREX: "FOREX",
            Market.MT5: "MT5",
            Market.GOLD: "GOLD",
            Market.OTC: "OTC",
            Market.SMARTY: "SMARTY",
            Market.AI: "AI INDEX",
            Market.FOOTBALL: "FOOTBALL INDEX",
            Market.LUXURY: "LUXURY INDEX",
            Market.CRICKET: "CRICKET INDEX",
        }[self]

    @property
    def is_expertoption(self) -> bool:
        return self in (Market.OTC, Market.SMARTY, Market.AI, Market.FOOTBALL, Market.LUXURY, Market.CRICKET)


@dataclass(frozen=True, slots=True)
class Timeframe:
    code: str
    label: str
    seconds: int


TIMEFRAMES: dict[str, Timeframe] = {
    "5sec": Timeframe("5sec", "S5", 5),
    "15sec": Timeframe("15sec", "S15", 15),
    "30sec": Timeframe("30sec", "S30", 30),
    "1min": Timeframe("1min", "M1", 60),
    "5min": Timeframe("5min", "M5", 300),
    "15min": Timeframe("15min", "M15", 900),
    "30min": Timeframe("30min", "M30", 1800),
    "1h": Timeframe("1h", "H1", 3600),
}
DEFAULT_TIMEFRAME = "5min"
# Higher frames need more history to compute EMA200 and SMC swings.
TIMEFRAME_MIN_BARS: dict[str, int] = {
    "5sec": 80, "15sec": 80, "30sec": 80,
    "1min": 80, "5min": 120, "15min": 120, "30min": 120, "1h": 120,
}


def timeframe(code: str) -> Timeframe:
    return TIMEFRAMES.get(code, TIMEFRAMES[DEFAULT_TIMEFRAME])


@dataclass(frozen=True, slots=True)
class Expiration:
    seconds: int
    label: str


EXPIRATIONS: tuple[Expiration, ...] = (
    Expiration(30, "30 SEC"),
    Expiration(45, "45 SEC"),
    Expiration(60, "1 MIN"),
    Expiration(105, "1 MIN 45 SEC"),
    Expiration(120, "2 MIN"),
    Expiration(180, "3 MIN"),
    Expiration(300, "5 MIN"),
    Expiration(900, "15 MIN"),
    Expiration(1800, "30 MIN"),
    Expiration(3600, "1 HOUR"),
)


def supported_expirations(tf: Timeframe) -> list[Expiration]:
    """Expirations that can be verified with candles of this timeframe."""
    allowed = [e for e in EXPIRATIONS if tf.seconds <= e.seconds <= tf.seconds * 30]
    return allowed or [EXPIRATIONS[-1]]


def expiration_by_seconds(seconds: int) -> Expiration | None:
    for item in EXPIRATIONS:
        if item.seconds == seconds:
            return item
    return None


def default_expiration(tf: Timeframe, confidence: float) -> Expiration:
    allowed = supported_expirations(tf)
    if confidence >= 78 and len(allowed) > 1:
        return allowed[1]
    return allowed[0]


@dataclass(frozen=True, slots=True)
class Asset:
    key: str
    symbol: str
    market: Market
    price_precision: int = 5
    twelve_data_symbol: str | None = None
    bridge_symbol: str | None = None
    bridge_id: int | None = None
    name: str | None = None

    @property
    def display(self) -> str:
        return f"{self.name or self.symbol} ({self.market.label})"

    @property
    def quote_currency(self) -> str:
        return self.symbol.split("/")[-1] if "/" in self.symbol else ""


def _asset(
    symbol: str,
    market: Market,
    precision: int,
    td: str | None = None,
    bridge: str | None = None,
    bridge_id: int | None = None,
    name: str | None = None,
) -> Asset:
    key = f"{symbol.replace('/', '_')}_{market.value}".upper()
    return Asset(
        key=key,
        symbol=symbol,
        market=market,
        price_precision=precision,
        twelve_data_symbol=td,
        bridge_symbol=bridge or symbol.replace("/", ""),
        bridge_id=bridge_id,
        name=name,
    )


def dynamic_asset(
    symbol: str, market: Market, precision: int = 5, bridge_id: int | None = None, name: str | None = None
) -> Asset:
    """ExpertOption asset discovered from the live bridge (OTC / SMARTY)."""
    key = f"{market.value.upper()}_{bridge_id or symbol}".replace("/", "_").upper()
    return Asset(
        key=key,
        symbol=symbol,
        market=market,
        price_precision=precision,
        bridge_symbol=symbol,
        bridge_id=bridge_id,
        name=name,
    )


_FOREX_SPECS: tuple[tuple[str, int], ...] = (
    ("EUR/USD", 5),
    ("GBP/USD", 5),
    ("USD/JPY", 3),
    ("AUD/USD", 5),
    ("USD/CAD", 5),
    ("USD/CHF", 5),
    ("NZD/USD", 5),
    ("EUR/JPY", 3),
    ("GBP/JPY", 3),
)

FOREX_ASSETS: tuple[Asset, ...] = tuple(
    _asset(symbol, Market.FOREX, precision, td=symbol) for symbol, precision in _FOREX_SPECS
)
GOLD_ASSETS: tuple[Asset, ...] = (_asset("XAU/USD", Market.GOLD, 2, td="XAU/USD"),)

# Canonical MT5 FX pairs the broker normally exposes. The live bridge is the
# authority: it resolves broker suffixes (AUDCAD.a) and may add more pairs.
_MT5_SYMBOLS: tuple[str, ...] = (
    "AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD", "AUDUSD", "CADCHF", "CADJPY",
    "CHFJPY", "EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURJPY", "EURNZD",
    "EURUSD", "GBPAUD", "GBPCAD", "GBPCHF", "GBPJPY", "GBPNZD", "GBPUSD",
    "NZDCAD", "NZDCHF", "NZDJPY", "NZDUSD", "USDCAD", "USDCHF", "USDJPY",
)


def mt5_precision(symbol: str) -> int:
    return 3 if symbol.upper().endswith("JPY") else 5


def mt5_asset(symbol: str, broker_symbol: str | None = None, name: str | None = None) -> Asset:
    canonical = symbol.upper().replace("/", "").replace("-", "")
    display = f"{canonical[:3]}/{canonical[3:]}" if len(canonical) == 6 else canonical
    return Asset(
        key=f"MT5_{canonical}",
        symbol=display,
        market=Market.MT5,
        price_precision=mt5_precision(canonical),
        bridge_symbol=broker_symbol or canonical,
        name=name,
    )


MT5_ASSETS: tuple[Asset, ...] = tuple(mt5_asset(symbol) for symbol in _MT5_SYMBOLS)
# SMARTY is a single ExpertOption instrument (id 240), never a currency list.
SMARTY_ASSET: Asset = _asset(
    "SMRTY", Market.SMARTY, 2, bridge="SMRTY", bridge_id=240, name="SMARTY SMRTY #240"
)
SMARTY_ASSETS: tuple[Asset, ...] = (SMARTY_ASSET,)
# OTC assets are discovered from the operator's own ExpertOption account at
# runtime (`/assets?market=otc` on the bridge); nothing is hardcoded here.
# ExpertOption index assets, verified live by the bridge (ids confirmed 2026-11-10).
AI_ASSETS: tuple[Asset, ...] = (
    _asset("AI_INDEX_OTC_R", Market.AI, 5, bridge="AI_INDEX_OTC_R", bridge_id=285, name="AI Index"),
)
FOOTBALL_ASSETS: tuple[Asset, ...] = (
    _asset("FOOTBALL_INDEX_OTC_R", Market.FOOTBALL, 5, bridge="FOOTBALL_INDEX_OTC_R", bridge_id=278, name="Football Index"),
)
LUXURY_ASSETS: tuple[Asset, ...] = (
    _asset("LUXURY_INDEX_OTC_R", Market.LUXURY, 5, bridge="LUXURY_INDEX_OTC_R", bridge_id=286, name="Luxury Index"),
)
OTC_ASSETS: tuple[Asset, ...] = ()

ASSETS: tuple[Asset, ...] = (
    FOREX_ASSETS + MT5_ASSETS + GOLD_ASSETS + SMARTY_ASSETS + AI_ASSETS
    + FOOTBALL_ASSETS + LUXURY_ASSETS
)
_BY_KEY: dict[str, Asset] = {asset.key: asset for asset in ASSETS}
_BY_SYMBOL: dict[tuple[str, Market], Asset] = {(a.symbol, a.market): a for a in ASSETS}
_DYNAMIC: dict[str, Asset] = {}


def register_dynamic(assets: list[Asset]) -> None:
    for asset in assets:
        _DYNAMIC[asset.key] = asset

MARKET_ORDER: tuple[Market, ...] = (
    Market.FOREX, Market.MT5, Market.SMARTY, Market.AI, Market.FOOTBALL, Market.LUXURY,
    Market.CRICKET, Market.OTC, Market.GOLD,
)


def get_asset(key: str) -> Asset | None:
    return _BY_KEY.get(key) or _DYNAMIC.get(key)


def assets_for(market: Market) -> list[Asset]:
    return [asset for asset in (*ASSETS, *_DYNAMIC.values()) if asset.market == market]


def find_by_symbol(symbol: str, market: Market | None = None) -> Asset | None:
    symbol = symbol.upper().replace("-", "/")
    if market is not None:
        return _BY_SYMBOL.get((symbol, market))
    matches = [asset for asset in (*ASSETS, *_DYNAMIC.values()) if asset.symbol == symbol]
    return matches[0] if matches else None


def all_assets() -> list[Asset]:
    return [*ASSETS, *_DYNAMIC.values()]
