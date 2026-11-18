"""Auto scanner: ranked, de-duplicated opportunities per market."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from config import Settings
from database.repository import Repository, SignalRecord
from engines.signals.generator import SignalGenerator
from engines.technical.analyzer import AnalysisResult
from engines.technical.delivery_window import can_publish, is_research_only
from providers.base import DataUnavailable, utc_now
from providers.catalog import Asset, Market, assets_for, timeframe
from providers.inventory import MarketInventory
from providers.registry import DataSourceRegistry

logger = logging.getLogger(__name__)

SCAN_PLAN: dict[Market, tuple[str, ...]] = {
    Market.FOREX: ("5min", "15min"),
    Market.GOLD: ("15min",),
    Market.OTC: ("1min",),
    Market.SMARTY: ("1min",),
    Market.AI: ("1min",),
    Market.FOOTBALL: ("1min",),
    Market.LUXURY: ("1min",),
    Market.CRICKET: ("1min",),
}

Notifier = Callable[[SignalRecord], Awaitable[datetime | None]]


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
        self._semaphore = asyncio.Semaphore(3)
        self._delivery_limit = asyncio.Semaphore(3)
        self._scan_lock = asyncio.Lock()
        self._rotation = {}
        self.last_duration_ms = None
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
        label = market.value.upper()
        if self.inventory is None or market not in self.inventory.dynamic_markets:
            return assets_for(market)
        if self.inventory is None:
            self.last_skips[label] = "market inventory not initialised"
            return []
        try:
            return await self.inventory.assets(market)
        except DataUnavailable as exc:
            self.last_skips[label] = exc.message
            return []

    async def scan_once(self, user_ids: list[int] | None = None, min_confidence: float | None = None,
                        *, notify: bool = True) -> list[SignalRecord]:
        async with self._scan_lock:
            return await self._scan_cycle(user_ids, min_confidence, notify)

    async def _scan_cycle(self, user_ids, min_confidence, notify):
        threshold = min_confidence if min_confidence is not None else self.settings.min_confidence
        started = time.monotonic()
        unscoped = user_ids is None
        explicit = self.settings.telegram_chat_id
        targets = list(user_ids or []) if not unscoped else ([explicit] if explicit else [])
        if unscoped:
            targets += await self.repo.scanner_targets()
        targets = list(dict.fromkeys(uid for uid in targets if uid))
        self.last_skips = {}
        now = utc_now()
        self._recent = {key: stamp for key, stamp in self._recent.items()
                        if now-stamp < timedelta(hours=3)}
        limit = max(1, self.settings.max_scan_signals)
        created = []
        publications = set()
        checked = 0

        async def get_job(asset, frame):
            async with self._semaphore:
                try:
                    return await asyncio.wait_for(self.generator.scan_asset(asset,frame,threshold), timeout=21)
                except TimeoutError:
                    self.last_skips.setdefault(asset.market.value.upper(), "تجاوز مهلة قراءة البيانات")
                    return None

        async def publish(target, result):
            if not can_publish(timeframe(result.timeframe).seconds, result.target_open_at, utc_now()):
                return None
            if self.settings.subscriptions_enabled and (target not in self.settings.owner_ids and
                                                        not await self.repo.is_subscribed(target)):
                return None
            if unscoped and target != explicit and not await self.repo.scanner_opt_in(target):
                return None
            if unscoped and self._stop.is_set():
                return None
            try:
                record = await self.generator.create_signal(target, result, timeframe(result.timeframe).seconds,
                                                           candle_target=True)
                if notify and self.notifier is not None:
                    try:
                        receipt = await asyncio.wait_for(self.notifier(record), timeout=6)
                        timely = receipt is not None and can_publish(
                            record.expiry_seconds, result.target_open_at, receipt, acknowledged=True)
                        if timely:
                            await self.repo.mark_candle_delivery(record.id,receipt)
                        logger.info("nexus scanner dispatch asset=%s frame=%s ready_ms=%d on_time=%s",
                            result.asset_key,result.timeframe,round((time.monotonic()-started)*1000),
                            timely)
                    except Exception:
                        logger.exception("scanner notifier failed")
                return record
            except (ValueError, KeyError):
                return None

        admitted = 0
        async def consume(result):
            nonlocal admitted
            if not result or admitted >= limit or not targets:
                return
            checked_at = utc_now()
            if not can_publish(timeframe(result.timeframe).seconds, result.target_open_at, checked_at):
                return
            if is_research_only(Market(result.market), False):
                return
            signature = f"{result.asset_key}:{result.timeframe}"
            cooldown = timedelta(seconds=max(300,timeframe(result.timeframe).seconds*2))
            last = self._recent.get(signature)
            if (last and checked_at-last<cooldown) or await self.repo.recent_signal_exists(
                    result.asset_key,checked_at-cooldown):
                return
            self._recent[signature] = checked_at
            admitted += 1
            # Isolate the Telegram/API/DB path from candle collection. Limit
            # simultaneous sends to avoid exhausting Telegram on a large list.
            async def limited(uid):
                async with self._delivery_limit:
                    return await publish(uid,result)
            publications.update(asyncio.create_task(limited(uid)) for uid in targets)

        discoveries = {asyncio.create_task(self.market_assets(market)):market for market in self.enabled_markets()}
        jobs = set()
        all_tasks = set(discoveries)
        waiters = set(discoveries)
        try:
            while waiters:
                done, waiters = await asyncio.wait(waiters,return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if task in discoveries:
                        market = discoveries[task]
                        try:
                            assets = task.result()
                        except Exception:
                            logger.exception("scanner inventory failed for %s",market.value)
                            continue
                        if unscoped and len(assets)>4:
                            offset = self._rotation.get(market,0)
                            assets = [assets[(offset+i)%len(assets)] for i in range(4)]
                            self._rotation[market] = offset+4
                        for asset in assets:
                            for frame in SCAN_PLAN[market]:
                                work = asyncio.create_task(get_job(asset,frame))
                                waiters.add(work); jobs.add(work); all_tasks.add(work)
                    elif task in jobs:
                        checked += 1
                        try:
                            await consume(task.result())
                        except Exception:
                            logger.exception("isolated scanner item failed")
            if publications:
                created = [r for r in await asyncio.gather(*publications,return_exceptions=True) if isinstance(r,SignalRecord)]
        finally:
            for task in all_tasks | publications:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*(all_tasks | publications),return_exceptions=True)
        self.last_run = utc_now()
        self.last_found = len(created)
        self.last_duration_ms = round((time.monotonic()-started)*1000)
        logger.info("nexus scanner completed checked=%d issued=%d wall_ms=%d targets=%d",
                    checked,self.last_found,self.last_duration_ms,len(targets))
        return created
