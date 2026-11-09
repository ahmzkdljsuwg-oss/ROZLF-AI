"""Live market inventory.

FOREX/GOLD assets come from the static catalog. OTC and SMARTY assets are read
from the operator's own ExpertOption account through the bridge, so the menu can
only ever show instruments that really exist on that account.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

from providers.base import DataUnavailable, utc_now
from providers.catalog import (
    SMARTY_ASSET,
    Asset,
    Market,
    assets_for,
    dynamic_asset,
    register_dynamic,
)
from providers.eobridge import ExpertOptionBridgeProvider

logger = logging.getLogger(__name__)

DISCOVERY_TTL = 120.0


@dataclass(slots=True)
class Discovery:
    market: Market
    ok: bool
    assets: list[Asset]
    error: str | None = None
    code: str | None = None
    at: datetime | None = None


class MarketInventory:
    def __init__(self, bridge: ExpertOptionBridgeProvider, ttl: float = DISCOVERY_TTL) -> None:
        self._bridge = bridge
        self._ttl = ttl
        self._cache: dict[Market, tuple[float, Discovery]] = {}

    @property
    def dynamic_markets(self) -> tuple[Market, ...]:
        return (Market.OTC, Market.SMARTY)

    def cached(self, market: Market) -> Discovery | None:
        entry = self._cache.get(market)
        return entry[1] if entry else None

    def cached_assets(self, market: Market) -> list[Asset]:
        if market not in self.dynamic_markets:
            return assets_for(market)
        entry = self._cache.get(market)
        return entry[1].assets if entry else []

    async def discover(self, market: Market, force: bool = False) -> Discovery:
        if market not in self.dynamic_markets:
            assets = assets_for(market)
            return Discovery(market=market, ok=bool(assets), assets=assets, at=utc_now())
        now = time.monotonic()
        entry = self._cache.get(market)
        if entry and not force and entry[0] > now:
            return entry[1]
        try:
            try:
                rows = await self._bridge.fetch_assets(market)
            except DataUnavailable as exc:
                auth_codes = {"TOKEN_INVALID", "AUTH_FAILED", "SESSION_INVALID", "EO_TOKEN_MISSING"}
                if market is not Market.SMARTY or exc.code in auth_codes:
                    raise
                rows = await self._smarty_rows()
            assets = self._to_assets(rows, market)
        except DataUnavailable as exc:
            discovery = Discovery(
                market=market, ok=False, assets=[], error=exc.message, code=exc.code, at=utc_now()
            )
            logger.warning("discovery failed for %s: %s", market.value, exc.message)
        except Exception as exc:  # noqa: BLE001 - discovery must never crash a handler
            logger.exception("discovery crashed for %s", market.value)
            discovery = Discovery(
                market=market, ok=False, assets=[], error=f"discovery error: {exc}", code="ERROR", at=utc_now()
            )
        else:
            discovery = Discovery(market=market, ok=bool(assets), assets=assets, at=utc_now())
            if not assets:
                discovery.code = "EMPTY"
                discovery.error = f"ExpertOption account exposes no {market.label} instruments"
            register_dynamic(assets)
        self._cache[market] = (now + self._ttl, discovery)
        return discovery

    async def _smarty_rows(self) -> list[dict]:
        payload = await self._bridge.smarty()
        asset = payload.get("asset")
        if not isinstance(asset, dict):
            raise DataUnavailable("SMARTY_UNAVAILABLE", "Bridge returned no SMARTY instrument")
        row = dict(asset)
        row["market"] = Market.SMARTY.value
        row.setdefault("id", payload.get("asset_id"))
        return [row]

    async def assets(self, market: Market, force: bool = False) -> list[Asset]:
        discovery = await self.discover(market, force=force)
        if not discovery.ok:
            reason = discovery.error or f"no verified {market.label} source"
            raise DataUnavailable(
                discovery.code or "MARKET_UNAVAILABLE",
                f"{market.value.upper()} UNAVAILABLE — {reason}",
                reason,
            )
        return discovery.assets

    async def resolve(self, key: str) -> Asset | None:
        from providers.catalog import get_asset

        asset = get_asset(key)
        if asset is not None:
            return asset
        for market in self.dynamic_markets:
            if self.cached(market) is None:
                await self.discover(market)
            asset = get_asset(key)
            if asset is not None:
                return asset
        return None

    @staticmethod
    def _to_assets(rows: list[dict], market: Market) -> list[Asset]:
        assets: list[Asset] = []
        seen: set[str] = set()
        for row in rows:
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            try:
                precision = int(row.get("precision") or 5)
            except (TypeError, ValueError):
                precision = 5
            try:
                bridge_id = int(row["id"]) if row.get("id") is not None else None
            except (TypeError, ValueError):
                bridge_id = None
            name = str(row.get("name") or "").strip() or None
            assets.append(
                dynamic_asset(symbol, market, precision=precision, bridge_id=bridge_id, name=name)
            )
        return assets

    def smarty_asset(self) -> Asset:
        return SMARTY_ASSET
