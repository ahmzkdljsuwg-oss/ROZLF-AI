from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from providers.catalog import Asset, Market, Timeframe


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "time", ensure_utc(self.time))


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    bid: float
    ask: float
    time: datetime
    source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "time", ensure_utc(self.time))

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def spread(self) -> float:
        return abs(self.ask - self.bid)

    @property
    def spread_pct(self) -> float:
        mid = self.mid
        return (self.spread / mid) * 100 if mid else 0.0

    def age_seconds(self, now: datetime | None = None) -> float:
        return ((now or utc_now()) - self.time).total_seconds()


@dataclass(frozen=True, slots=True)
class ValidationReport:
    ok: bool
    bar_count: int
    issues: tuple[str, ...] = ()
    stale: bool = False
    age_seconds: float | None = None
    last_candle_time: datetime | None = None
    max_gap_seconds: float | None = None

    @property
    def is_tradeable(self) -> bool:
        return self.ok and not self.stale

    @property
    def summary(self) -> str:
        if self.is_tradeable:
            return f"OK ({self.bar_count} bars)"
        parts = list(self.issues)
        if self.stale:
            parts.append("stale data")
        return "; ".join(parts) or "invalid data"


@dataclass(slots=True)
class MarketData:
    asset: Asset
    timeframe: Timeframe
    candles: list[Candle]
    source: str
    quote: Quote | None
    validation: ValidationReport
    fetched_at: datetime = field(default_factory=utc_now)

    @property
    def last_close(self) -> float:
        return self.candles[-1].close if self.candles else 0.0

    @property
    def last_time(self) -> datetime | None:
        return self.candles[-1].time if self.candles else None


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    id: str
    name: str
    configured: bool
    can_serve_candles: bool
    markets: tuple[str, ...]
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "configured": self.configured,
            "can_serve_candles": self.can_serve_candles,
            "markets": list(self.markets),
            "detail": self.detail,
        }


class DataUnavailable(Exception):
    """Raised whenever real, usable data cannot be supplied for an asset."""

    def __init__(self, code: str, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        return self.message


class BaseProvider(ABC):
    id: str = "base"
    name: str = "Base"
    markets: frozenset[Market] = frozenset()
    can_serve_candles: bool = True

    @property
    def configured(self) -> bool:
        return True

    def supports(self, asset: Asset) -> bool:
        return asset.market in self.markets and self._supports(asset)

    def _supports(self, asset: Asset) -> bool:  # pragma: no cover - overridden
        return True

    @abstractmethod
    async def fetch_candles(self, asset: Asset, timeframe: Timeframe, limit: int = 300) -> list[Candle]:
        raise NotImplementedError

    async def fetch_quote(self, asset: Asset) -> Quote:
        raise DataUnavailable("QUOTE_UNAVAILABLE", f"{self.name} cannot supply quotes")

    async def close(self) -> None:
        return None

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            id=self.id,
            name=self.name,
            configured=self.configured,
            can_serve_candles=self.can_serve_candles,
            markets=tuple(sorted(market.label for market in self.markets)),
        )
