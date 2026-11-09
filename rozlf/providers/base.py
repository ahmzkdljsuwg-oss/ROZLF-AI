"""Provider contracts shared by every market data source."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable

MARKET_FOREX = "FOREX"
MARKET_OTC = "OTC"
MARKET_SMARTY = "SMARTY"


class ProviderError(RuntimeError):
    """Any failure while talking to a data source."""

    def __init__(self, message: str, *, code: str = "PROVIDER_ERROR", retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class SourceNotConfigured(ProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="SOURCE_NOT_CONFIGURED")


class DataUnavailable(ProviderError):
    def __init__(self, message: str, *, code: str = "DATA_UNAVAILABLE") -> None:
        super().__init__(message, code=code)


@dataclass(frozen=True)
class Asset:
    symbol: str
    name: str
    market: str
    provider: str
    source_id: str = ""
    timeframes: tuple[int, ...] = ()
    note: str = ""

    @property
    def is_synthetic(self) -> bool:
        return self.market in (MARKET_OTC, MARKET_SMARTY)

    def label(self) -> str:
        return f"{self.symbol} · {self.market}"


@dataclass(frozen=True)
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "time": self.time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float
    time: int
    source: str
    bid: float | None = None
    ask: float | None = None

    @property
    def spread(self) -> float | None:
        if self.bid is None or self.ask is None:
            return None
        return round(self.ask - self.bid, 8)


@dataclass
class ProviderStatus:
    name: str
    title: str
    configured: bool
    connected: bool
    markets: tuple[str, ...] = ()
    assets: int = 0
    last_update: int | None = None
    detail: str = ""
    quality: str = "unknown"
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "configured": self.configured,
            "connected": self.connected,
            "markets": list(self.markets),
            "assets": self.assets,
            "last_update": self.last_update,
            "detail": self.detail,
            "quality": self.quality,
            **self.extra,
        }


def now_ts() -> int:
    return int(time.time())


class MarketProvider(ABC):
    """Read-only market data source.

    Implementations must never synthesise prices: when a symbol, timeframe or
    upstream feed is missing they raise :class:`DataUnavailable`.
    """

    name: str = "provider"
    title: str = "Provider"
    markets: tuple[str, ...] = ()
    read_only: bool = True
    can_serve_candles: bool = True

    @abstractmethod
    def supports(self, asset: Asset) -> bool: ...

    @abstractmethod
    async def candles(self, asset: Asset, timeframe: int, limit: int = 200) -> list[Candle]: ...

    async def quote(self, asset: Asset) -> Quote:
        rows = await self.candles(asset, self.best_timeframe(asset), limit=3)
        last = rows[-1]
        return Quote(symbol=asset.symbol, price=last.close, time=last.time, source=self.name)

    @abstractmethod
    async def status(self) -> ProviderStatus: ...

    async def close(self) -> None:
        return None

    def best_timeframe(self, asset: Asset) -> int:
        if asset.timeframes:
            return asset.timeframes[0]
        raise DataUnavailable(f"{asset.symbol}: لا توجد فريمات مدعومة لهذا المصدر.", code="NO_TIMEFRAME")

    def supported_timeframes(self, asset: Asset) -> tuple[int, ...]:
        return asset.timeframes

    async def assets(self) -> Iterable[Asset]:
        return ()
