"""Auto scanner: ranked, de-duplicated opportunities per market."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from config import Settings
from database.repository import Repository, SignalRecord
from engines.signals.generator import SignalGenerator
from engines.technical.analyzer import AnalysisResult
from providers.base import DataUnavailable, utc_now
from providers.catalog import Asset, Market, assets_for, timeframe
from providers.inventory import MarketInventory
from providers.registry import DataSourceRegistry

logger = logging.getLogger(__name__)

SCAN_PLAN: dict[Market, tuple[str, ...]] = {
    Market.FOREX: ("5min", "15min"),
    Market.GOLD: ("15min",),
    Market.SMARTY: ("1min",),
    Market.AI: ("1min",),
    Market.FOOTBALL: ("1min",),
    Market.LUXURY: ("1min",),
    Market.CRICKET: ("1min",),
}

Notifier = Callable[[SignalRecord], Awaitable[None]]


class AutoScanner:
    def __init__(
        self,
        generator: SignalGenerator,
        repo: Repository,
        registry: DataSourceRegistry,
        settings: Settings,
        notifier: Notifier | None = None,
        inventory: MarketInventory | None = None,
    ) -> None:
        self.generator = generator
        self.repo = repo
        self.registry = registry
        self.settings = settings
        self.inventory = inventory
        self.last_skips: dict[str, str] = {}
        self.notifier = notifier
        self.running = False
        self.last_run: datetime | None = None
        self.last_found: int = 0
        self.last_error: str | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._semaphore = asyncio.Semaphore(4)
        self._recent: dict[str, datetime] = {}
        self._override: set[str] | None = None

    def market_selection(self) -> list[str]:
        if self._override is not None:
            return sorted(self._override)
        return [
            name.strip().upper()
            for name in (self.settings.scan_markets or "").split(",")
            if name.strip()
        ]

    def toggle_market(self, market: str) -> list[str]:
        market = market.upper()
        if market not in {item.value.upper() for item in SCAN_PLAN}:
            return self.market_selection()
        current = set(self.market_selection())
        if market in current:
            current.discard(market)
        else:
            current.add(market)
        if not current:
            current = {Market.FOREX.value.upper()}
        self._override = current
        return sorted(current)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self.running = True
        self._task = asyncio.create_task(self._loop(), name="rozlf-auto-scanner")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        self.running = False

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # keep the loop alive
                self.last_error = str(exc)
                logger.exception("auto scanner cycle failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(60, self.settings.scan_interval))
            except asyncio.TimeoutError:
                continue

    def enabled_markets(self) -> list[Market]:
        wanted = {name.upper() for name in self.market_selection()}
        markets = [market for market in SCAN_PLAN if market.value.upper() in wanted]
        return markets or [Market.FOREX, Market.SMARTY]

    async def market_assets(self, market: Market) -> list[Asset]:
        if market not in (Market.SMARTY, Market.CRICKET):
            return assets_for(market)
        label = market.value.upper()
        if self.inventory is None:
            self.last_skips[label] = "market inventory not initialised"
            return []
        try:
            return await self.inventory.assets(market)
        except DataUnavailable as exc:
            self.last_skips[label] = exc.message
            return []

    async def scan_once(self, user_ids: list[int] | None = None, min_confidence: float | None = None) -> list[SignalRecord]:
        threshold = min_confidence if min_confidence is not None else self.settings.min_confidence
        now = utc_now()
        markets = self.enabled_markets()
        found: list[AnalysisResult] = []
        self.last_skips = {}

        async def analyse(asset: Asset, frame_code: str) -> AnalysisResult | None:
            async with self._semaphore:
                result = await self.generator.scan_asset(asset, frame_code, threshold)
            if result is None:
                return None
            signature = f"{asset.key}:{frame_code}"
            last = self._recent.get(signature)
            cooldown = max(300, timeframe(frame_code).seconds * 2)
            if last is not None and (now - last).total_seconds() < cooldown:
                return None
            if await self.repo.recent_signal_exists(asset.key, now - timedelta(seconds=cooldown)):
                return None
            self._recent[signature] = now
            return result

        tasks = []
        for market in markets:
            for asset in await self.market_assets(market):
                for frame_code in SCAN_PLAN[market]:
                    tasks.append(analyse(asset, frame_code))
        if not tasks:
            self.last_run = now
            self.last_found = 0
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for item in results:
            if isinstance(item, AnalysisResult):
                found.append(item)
            elif isinstance(item, Exception) and not isinstance(item, asyncio.CancelledError):
                logger.debug("scan item failed: %s", item)

        found.sort(key=lambda result: result.confidence, reverse=True)
        top = found[: max(1, self.settings.max_scan_signals)]
        targets = user_ids if user_ids is not None else [self.settings.telegram_chat_id] if self.settings.telegram_chat_id else []
        created: list[SignalRecord] = []
        for result in top:
            for user_id in targets:
                if not user_id:
                    continue
                try:
                    record = await self.generator.create_signal(user_id, result, result.suggested_expiry_seconds, now)
                except (ValueError, KeyError) as exc:
                    logger.warning("scan signal rejected: %s", exc)
                    continue
                created.append(record)
                if self.notifier is not None:
                    try:
                        await self.notifier(record)
                    except Exception:
                        logger.exception("scanner notifier failed")

        self.last_run = utc_now()
        self.last_found = len(created)
        return created
