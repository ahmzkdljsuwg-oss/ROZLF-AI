"""Per-market truth probe.

The system-status panel must never print CONNECTED based only on an environment
variable: every market is probed against its real provider and the failure
reason is reported verbatim.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime

from providers.catalog import Market, get_asset
from providers.inventory import MarketInventory
from providers.registry import DataSourceRegistry

logger = logging.getLogger(__name__)

PROBE_PLAN: dict[Market, tuple[str | None, str]] = {
    Market.FOREX: ("EUR_USD_FOREX", "5min"),
    Market.GOLD: ("XAU_USD_GOLD", "15min"),
    Market.SMARTY: (None, "1min"),
    Market.AI: (None, "1min"),
    Market.FOOTBALL: (None, "1min"),
    Market.LUXURY: (None, "1min"),
    Market.CRICKET: (None, "1min"),
}
HEALTH_TTL = 45.0


@dataclass(slots=True)
class MarketHealth:
    market: Market
    ok: bool
    source: str | None
    asset: str | None = None
    error: str | None = None
    detail: str | None = None
    last_time: datetime | None = None
    at: datetime | None = None


class MarketHealthService:
    def __init__(
        self,
        registry: DataSourceRegistry,
        inventory: MarketInventory,
        ttl: float = HEALTH_TTL,
    ) -> None:
        self.registry = registry
        self.inventory = inventory
        self._ttl = ttl
        self._cache: dict[Market, tuple[float, MarketHealth]] = {}

    def cached(self) -> dict[str, MarketHealth]:
        return {market.value: entry[1] for market, entry in self._cache.items()}

    async def snapshot(self, force: bool = False) -> dict[str, MarketHealth]:
        now = time.monotonic()
        pending = [
            market
            for market in PROBE_PLAN
            if force or market not in self._cache or self._cache[market][0] <= now
        ]
        if pending:
            results = await asyncio.gather(*(self._probe(market) for market in pending))
            for market, health in zip(pending, results):
                self._cache[market] = (now + self._ttl, health)
        return {market.value: self._cache[market][1] for market in PROBE_PLAN if market in self._cache}

    async def _probe(self, market: Market) -> MarketHealth:
        asset_key, frame = PROBE_PLAN[market]
        try:
            if asset_key is None:
                assets = await self.inventory.assets(market)
                asset = assets[0]
            else:
                asset = get_asset(asset_key)
                if asset is None:
                    return MarketHealth(market, False, None, error=f"{asset_key} missing from catalog")
            probe = await self.registry.probe(asset, frame)
        except Exception as exc:  # noqa: BLE001 - status must always render
            from providers.base import DataUnavailable

            if isinstance(exc, DataUnavailable):
                return MarketHealth(market, False, None, error=exc.message, detail=exc.detail)
            logger.exception("health probe crashed for %s", market.value)
            return MarketHealth(market, False, None, error=f"probe error: {exc}")
        if not probe.get("ok"):
            return MarketHealth(
                market,
                False,
                None,
                asset=str(probe.get("asset") or ""),
                error=str(probe.get("error") or "unavailable"),
                detail=str(probe.get("detail") or "") or None,
            )
        return MarketHealth(
            market,
            True,
            str(probe.get("source") or ""),
            asset=str(probe.get("asset") or ""),
            last_time=probe.get("last_time"),  # type: ignore[arg-type]
        )
