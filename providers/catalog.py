"""Static market catalogue. Only symbols listed here can be analysed."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Market(str, Enum):
    FOREX = "forex"
    GOLD = "gold"
    OTC = "otc"
    SMARTY = "smarty"

    @property
    def label(self) -> str:
        return {
            Market.FOREX: "FOREX",
            Market.GOLD: "GOLD",
            Market.OTC: "OTC",
            Market.SMARTY: "SMARTY",
        }[self]

    @property
    def is_expertoption(self) -> bool:
        return self in (Market.OTC, Market.SMARTY)


@dataclass(frozen=True, slots=True)
class Timeframe:
    code: str
    label: str
    seconds: int


TIMEFRAMES: dict[str, Timeframe] = {
    "1min": Timeframe("1min", "M1", 60),
    "5min": Timeframe("5min", "M5", 300),
    "15min": Timeframe("15min", "M15", 900),
    "30min": Timeframe("30min", "M30", 1800),
    "1h": Timeframe("1h", "H1", 3600),
}
DEFAULT_TIMEFRAME = "5min"
# Higher frames need more history to compute EMA200 and SMC swings.
TIMEFRAME_MIN_BARS: dict[str, int] = {"1min": 80, "5min": 120, "15min": 120, "30min": 120, "1h": 120}


def timeframe(code: str) -> Timeframe:
    return TIMEFRAMES.get(code, TIMEFRAMES[DEFAULT_TIMEFRAME])


@dataclass(frozen=True, slots=True)
class Expiration:
    seconds: int
    label: str


EXPIRATIONS: tuple[Expiration, ...] = (
    Expiration(30, "30 SEC"),
    Expiration(60, "1 MIN"),
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

    @property
    def display(self) -> str:
        return f"{self.symbol} ({self.market.label})"

    @property
    def quote_currency(self) -> str:
        return self.symbol.split("/")[-1] if "/" in self.symbol else ""


def _asset(symbol: str, market: Market, precision: int, td: str | None = None, bridge: str | None = None) -> Asset:
    key = f"{symbol.replace('/', '_')}_{market.value}".upper()
    return Asset(
        key=key,
        symbol=symbol,
        market=market,
        price_precision=precision,
        twelve_data_symbol=td,
        bridge_symbol=bridge or symbol.replace("/", ""),
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
# No public, licence-compatible ExpertOption OTC/Smarty feed exists; these assets
# are only usable when the operator supplies a verified read-only bridge.
OTC_ASSETS: tuple[Asset, ...] = tuple(
    _asset(symbol, Market.OTC, precision) for symbol, precision in _FOREX_SPECS[:6]
) + (_asset("XAU/USD", Market.OTC, 2), _asset("BTC/USD", Market.OTC, 2))
SMARTY_ASSETS: tuple[Asset, ...] = tuple(
    _asset(symbol, Market.SMARTY, precision) for symbol, precision in _FOREX_SPECS[:6]
) + (_asset("XAU/USD", Market.SMARTY, 2),)

ASSETS: tuple[Asset, ...] = FOREX_ASSETS + GOLD_ASSETS + OTC_ASSETS + SMARTY_ASSETS
_BY_KEY: dict[str, Asset] = {asset.key: asset for asset in ASSETS}
_BY_SYMBOL: dict[tuple[str, Market], Asset] = {(a.symbol, a.market): a for a in ASSETS}

MARKET_ORDER: tuple[Market, ...] = (Market.SMARTY, Market.OTC, Market.FOREX, Market.GOLD)


def get_asset(key: str) -> Asset | None:
    return _BY_KEY.get(key)


def assets_for(market: Market) -> list[Asset]:
    return [asset for asset in ASSETS if asset.market == market]


def find_by_symbol(symbol: str, market: Market | None = None) -> Asset | None:
    symbol = symbol.upper().replace("-", "/")
    if market is not None:
        return _BY_SYMBOL.get((symbol, market))
    matches = [asset for asset in ASSETS if asset.symbol == symbol]
    return matches[0] if matches else None


def all_assets() -> list[Asset]:
    return list(ASSETS)
