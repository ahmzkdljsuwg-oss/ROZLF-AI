"""Expiry verification against a live quote; unverifiable means UNVERIFIED."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from database.repository import (
    STATUS_DRAW,
    STATUS_LOSS,
    STATUS_UNVERIFIED,
    STATUS_WIN,
    Repository,
    SignalRecord,
)
from providers.base import DataUnavailable, utc_now
from providers.catalog import get_asset
from providers.registry import DataSourceRegistry

logger = logging.getLogger(__name__)

Notifier = Callable[[SignalRecord], Awaitable[None]]


class SignalTracker:
    def __init__(
        self,
        repo: Repository,
        registry: DataSourceRegistry,
        notifier: Notifier | None = None,
        grace_seconds: int = 600,
    ) -> None:
        self.repo = repo
        self.registry = registry
        self.notifier = notifier
        self.grace_seconds = grace_seconds

    async def verify_due(self, now: datetime | None = None) -> int:
        now = now or utc_now()
        due = await self.repo.due_signals(now)
        verified = 0
        for signal in due:
            outcome = await self._resolve(signal, now)
            if outcome is None:
                continue
            result, close_price, source = outcome
            await self.repo.finish_signal(signal.id, result, close_price, now, source)
            signal.status = result
            signal.close_price = close_price
            signal.verification_source = source
            verified += 1
            if self.notifier is not None:
                try:
                    await self.notifier(signal)
                except Exception:
                    logger.exception("verification notifier failed for signal %s", signal.id)
        return verified

    async def _resolve(self, signal: SignalRecord, now: datetime) -> tuple[str, float | None, str | None] | None:
        asset = get_asset(signal.asset_key)
        try:
            quote = await self.registry.fetch_quote(asset)
        except DataUnavailable as exc:
            if now - signal.expires_at >= timedelta(seconds=self.grace_seconds):
                logger.info("signal %s unverifiable: %s", signal.id, exc.message)
                return STATUS_UNVERIFIED, None, None
            return None

        # A quote older than the expiry cannot prove the closing price.
        max_age = max(60.0, signal.expiry_seconds * 0.5)
        if quote.age_seconds(now) > max_age:
            if now - signal.expires_at >= timedelta(seconds=self.grace_seconds):
                return STATUS_UNVERIFIED, None, quote.source
            return None

        close = quote.mid
        tolerance = max(quote.spread * 0.5, abs(signal.entry_price) * 1e-6)
        delta = close - signal.entry_price
        if abs(delta) <= tolerance:
            result = STATUS_DRAW
        elif (delta > 0 and signal.direction == "UP") or (delta < 0 and signal.direction == "DOWN"):
            result = STATUS_WIN
        else:
            result = STATUS_LOSS
        return result, round(close, 8), quote.source
