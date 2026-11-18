"""Expiry verification against a live quote; unverifiable means UNVERIFIED."""
from __future__ import annotations

import asyncio
import logging
from math import isfinite
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
from providers.catalog import get_asset, timeframe
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
            entry = None
            if signal.target_open_at is not None:
                candle_outcome = await self._resolve_candle(signal, now)
                if candle_outcome is None:
                    continue
                result, close_price, source, entry = candle_outcome
                outcome = result, close_price, source
                if entry is not None:
                    signal.entry_price = entry
            else:
                outcome = await self._resolve(signal, now)
            if outcome is None:
                continue
            result, close_price, source = outcome
            reason = self._result_reason(signal, result, close_price)
            if signal.target_open_at is not None:
                await self.repo.finish_signal(signal.id,result,close_price,now,source,reason,entry_price=entry)
            else:
                await self.repo.finish_signal(signal.id, result, close_price, now, source, reason)
            signal.status = result
            signal.close_price = close_price
            signal.verification_source = source
            signal.result_reason = reason
            verified += 1
            if self.notifier is not None:
                try:
                    await self.notifier(signal)
                except Exception:
                    logger.exception("verification notifier failed for signal %s", signal.id)
        return verified

    @staticmethod
    def _result_reason(signal: SignalRecord, result: str, close_price: float | None) -> str:
        setup = signal.reasons[0] if signal.reasons else "no recorded setup"
        if signal.target_open_at is not None:
            return ("تعذّر التحقق من نفس الشمعة المستهدفة من المصدر نفسه"
                    if result == STATUS_UNVERIFIED else "تم التحقق من افتتاح وإغلاق الشمعة المستهدفة نفسها")
        if result == STATUS_UNVERIFIED or close_price is None:
            return f"No reliable expiry quote was available to settle the {signal.direction} setup ({setup})."
        delta = close_price - signal.entry_price
        direction = "with" if (delta > 0) == (signal.direction == "UP") else "against"
        return (
            f"Expiry price closed {delta:+.8f} {direction} the {signal.direction} entry; "
            f"recorded setup: {setup}"
        )

    async def _resolve_candle(self, signal, now):
        if signal.delivered_at is None or signal.delivered_at >= signal.target_open_at:
            return STATUS_UNVERIFIED, None, None, None
        tf = timeframe(signal.timeframe)
        if signal.expiry_seconds != tf.seconds or signal.target_open_at + timedelta(seconds=tf.seconds) > now:
            return None
        try:
            asset = get_asset(signal.asset_key)
            if asset is None:
                raise DataUnavailable("ASSET_UNKNOWN", "Original instrument is not in the inventory")
            data = await asyncio.wait_for(self.registry.fetch(asset,tf,with_quote=False),timeout=5)
            if data.source == signal.source:
                bar = next((b for b in data.candles if b.time == signal.target_open_at),None)
                if (bar and bar.time + timedelta(seconds=tf.seconds) <= data.closure_cutoff
                        and all(isfinite(v) and v > 0 for v in (bar.open,bar.close))):
                    delta = bar.close-bar.open
                    status = (STATUS_DRAW if delta == 0 else STATUS_WIN
                              if (delta > 0) == (signal.direction == "UP") else STATUS_LOSS)
                    return status, bar.close, data.source, bar.open
        except (KeyError,DataUnavailable,TimeoutError):
            pass
        if now >= signal.expires_at + timedelta(seconds=self.grace_seconds):
            return STATUS_UNVERIFIED,None,None,None
        return None

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
        if signal.expiry_seconds <= 60:
            max_age = max(15.0, signal.expiry_seconds * 0.75)
        else:
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
