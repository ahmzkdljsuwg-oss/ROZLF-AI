"""Expiry tracker: a signal is only ever settled with a real observed price."""

from __future__ import annotations

import logging
import time

from ...database.repository import SignalRepository
from ...providers.base import ProviderError
from ...providers.registry import DataSourceRegistry

log = logging.getLogger(__name__)

DRAW_TOLERANCE = 0.0


class SignalTracker:
    def __init__(self, repo: SignalRepository, registry: DataSourceRegistry, on_resolved=None):
        self.repo = repo
        self.registry = registry
        self.on_resolved = on_resolved

    async def resolve_due(self, now: int | None = None) -> list[dict]:
        now = now or int(time.time())
        rows = await self.repo.due_for_resolution(now)
        resolved: list[dict] = []
        for row in rows:
            asset = self.registry.asset(row.symbol)
            provider = self.registry.provider_for(asset)
            try:
                quote = await provider.quote(asset)
            except ProviderError as exc:
                log.info("resolve deferred for signal %s: %s", row.id, exc.code)
                await self.repo.mark_attempt(row.id)
                continue
            if quote.time < row.expires_at - 5:
                # the feed has not printed a price at/after expiry yet
                await self.repo.mark_attempt(row.id)
                continue

            candles = []
            try:
                candles, _ = await self.registry.candles(asset, row.timeframe, limit=80)
            except ProviderError:
                pass

            result = _classify(row.direction, row.entry, quote.price)
            await self.repo.resolve(row.id, result=result, exit_price=round(quote.price, 8))
            payload = {
                "id": row.id,
                "symbol": row.symbol,
                "market": row.market,
                "direction": row.direction,
                "entry": row.entry,
                "exit": round(quote.price, 8),
                "result": result,
                "expiry_seconds": row.expiry_seconds,
                "created_at": row.created_at,
                "resolved_at": int(time.time()),
                "source": quote.source,
                "candles": candles,
            }
            resolved.append(payload)
            if self.on_resolved:
                await self.on_resolved(payload)
        return resolved


def _classify(direction: str, entry: float, exit_price: float) -> str:
    if entry <= 0:
        return "UNVERIFIED"
    delta = exit_price - entry
    if abs(delta) <= abs(entry) * 1e-9:
        return "DRAW"
    if direction == "UP":
        return "WIN" if delta > 0 else "LOSS"
    if direction == "DOWN":
        return "WIN" if delta < 0 else "LOSS"
    return "UNVERIFIED"
