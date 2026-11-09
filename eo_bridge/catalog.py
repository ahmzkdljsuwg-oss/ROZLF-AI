"""Mapping between ROZLF asset requests and real ExpertOption instruments.

Classification is derived from the live `assets` payload, never assumed:
  * id 240 / symbol SMRTY  -> SMARTY
  * is_otc truthy          -> OTC
  * XAUUSD / XPTUSD etc.   -> GOLD
  * everything else        -> FOREX
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MARKETS = {"otc", "smarty", "gold", "forex"}
GOLD_SYMBOLS = {"XAUUSD", "XPTUSD", "XAGUSD", "GOLD"}
SMARTY_IDS = {240}
SMARTY_SYMBOLS = {"SMRTY", "SMARTY"}

TIMEFRAME_SECONDS = {
    "1min": 60,
    "5min": 300,
    "15min": 900,
    "30min": 1800,
    "1h": 3600,
    # ExpertOption-native expiry frames
    "30sec": 30,
    "2min": 120,
    "3min": 180,
}


def normalise_symbol(value: str) -> str:
    """Uppercase and keep underscores (EURUSD_OTC stays EURUSD_OTC)."""
    return re.sub(r"[^A-Z0-9_]", "", (value or "").upper())


def compact_symbol(value: str) -> str:
    return normalise_symbol(value).replace("_", "")


@dataclass(frozen=True, slots=True)
class Instrument:
    id: int
    symbol: str
    name: str
    market: str
    is_active: bool
    profit: float
    precision: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "name": self.name,
            "market": self.market,
            "is_active": self.is_active,
            "profit": self.profit,
            "precision": self.precision,
        }


def classify(raw: dict[str, Any]) -> str:
    asset_id = int(raw.get("id") or 0)
    symbol = normalise_symbol(str(raw.get("symbol") or raw.get("name") or ""))
    if asset_id in SMARTY_IDS or symbol in SMARTY_SYMBOLS:
        return "smarty"
    if raw.get("is_otc"):
        return "otc"
    if symbol in GOLD_SYMBOLS:
        return "gold"
    return "forex"


def to_instrument(raw: dict[str, Any]) -> Instrument | None:
    try:
        asset_id = int(raw.get("id"))
    except (TypeError, ValueError):
        return None
    symbol = normalise_symbol(str(raw.get("symbol") or raw.get("name") or ""))
    if not symbol:
        return None
    name = str(raw.get("name") or symbol)
    try:
        precision = int(raw.get("precision") or 5)
    except (TypeError, ValueError):
        precision = 5
    try:
        profit = float(raw.get("profit") or 0)
    except (TypeError, ValueError):
        profit = 0.0
    return Instrument(
        id=asset_id,
        symbol=symbol,
        name=name,
        market=classify(raw),
        is_active=bool(raw.get("is_active", 1)),
        profit=profit,
        precision=precision,
    )


def build_instruments(raw_assets: list[dict[str, Any]]) -> list[Instrument]:
    seen: dict[int, Instrument] = {}
    for raw in raw_assets:
        instrument = to_instrument(raw)
        if instrument is None:
            continue
        # Keep the active/highest-payout duplicate for an id.
        previous = seen.get(instrument.id)
        if previous is None or (instrument.is_active and not previous.is_active):
            seen[instrument.id] = instrument
    return sorted(seen.values(), key=lambda item: (item.market, item.symbol, item.id))


def resolve(instruments: list[Instrument], market: str, symbol: str) -> Instrument | None:
    """Find the live instrument for a ROZLF (market, symbol) request.

    OTC requests carry the plain pair (EURUSD) but ExpertOption names the OTC
    instrument EURUSD_OTC, so both spellings and the display name are tried.
    """
    wanted = compact_symbol(symbol)
    market = (market or "").lower()
    if market not in MARKETS:
        return None
    candidates = [item for item in instruments if item.market == market]
    for item in candidates:
        name = compact_symbol(item.name)
        if compact_symbol(item.symbol) in {wanted, f"{wanted}OTC", f"{wanted}OTCR"}:
            return item
        if name in {wanted, f"{wanted}OTC"}:
            return item
    return None


def timeframe_seconds(value: str) -> int | None:
    key = (value or "").strip().lower()
    if key.isdigit():
        seconds = int(key)
        return seconds if seconds > 0 else None
    return TIMEFRAME_SECONDS.get(key)
