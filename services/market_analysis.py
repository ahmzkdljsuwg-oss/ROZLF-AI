"""One automatic, market-isolated analysis for the NEXUS Telegram flow."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from config import Settings
from engines.signals.duration import auto_frames, choose_auto_duration
from engines.technical.analyzer import AnalysisResult, analyze_market_data
from providers.base import DataUnavailable
from providers.catalog import Asset, Market, assets_for, timeframe
from providers.registry import DataSourceRegistry

logger = logging.getLogger(__name__)

MAX_ASSETS = 8
FETCH_TIMEOUT = 18.0
ANALYSIS_TIMEOUT = 22.0


@dataclass(slots=True)
class MarketAnalysis:
    market: Market
    result: AnalysisResult | None = None
    duration_seconds: int | None = None
    duration_reason: str = ""
    errors: list[str] = field(default_factory=list)
    conflict: str | None = None
    attempted: int = 0
    fetched: int = 0

    @property
    def actionable(self) -> bool:
        return (
            self.result is not None
            and self.result.direction in ("UP", "DOWN")
            and self.duration_seconds is not None
            and self.conflict is None
        )


class MarketAnalysisService:
    def __init__(self, registry: DataSourceRegistry, settings: Settings, inventory=None) -> None:
        self.registry = registry
        self.settings = settings
        self.inventory = inventory

    async def assets_for(self, market: Market) -> list[Asset]:
        if market in (Market.FOREX, Market.GOLD):
            return list(assets_for(market))[:MAX_ASSETS]
        if self.inventory is not None:
            return list(await self.inventory.assets(market, force=True))[:MAX_ASSETS]
        return list(assets_for(market))[:MAX_ASSETS]

    async def analyse(self, market: Market) -> MarketAnalysis:
        outcome = MarketAnalysis(market=market)
        try:
            assets = await self.assets_for(market)
        except DataUnavailable as exc:
            outcome.errors.append(exc.detail or exc.message)
            return outcome
        if not assets:
            outcome.errors.append(f"no verified {market.label} instruments")
            return outcome

        jobs: list[tuple[Asset, str]] = []
        for asset in assets:
            for frame in auto_frames(asset):
                jobs.append((asset, frame))
        outcome.attempted = len(jobs)
        semaphore = asyncio.Semaphore(4)
        gathered = await asyncio.gather(
            *(self._one(asset, frame, semaphore) for asset, frame in jobs),
            return_exceptions=True,
        )
        results: list[tuple[AnalysisResult, str]] = []
        for item in gathered:
            if isinstance(item, Exception):
                outcome.errors.append(str(item))
            elif item is not None:
                results.append(item)
        outcome.fetched = len(results)
        if not results:
            if not outcome.errors:
                outcome.errors.append("no verified candles were returned")
            return outcome

        actionable = [item for item in results if item[0].direction in ("UP", "DOWN")]
        if actionable:
            actionable.sort(key=lambda item: item[0].confidence, reverse=True)
            best, frame = actionable[0]
            opposing = [
                other for other, _ in actionable[1:]
                if other.direction != best.direction
                and other.confidence >= max(52.0, best.confidence - 8.0)
            ]
            if opposing:
                outcome.result = best
                outcome.conflict = (
                    f"{best.direction} {best.confidence:.0f}% on {frame} conflicts with "
                    f"{opposing[0].direction} {opposing[0].confidence:.0f}% on "
                    f"{opposing[0].timeframe}"
                )
                return outcome
            duration, reason = choose_auto_duration(best, _asset_by_key(assets, best.asset_key))
            if duration is not None and best.confidence >= max(52.0, self.settings.min_confidence - 8.0):
                outcome.result = best
                outcome.duration_seconds = duration
                outcome.duration_reason = reason
                return outcome
            outcome.errors.append("best setup did not pass the confidence or duration filter")
        results.sort(key=lambda item: item[0].confidence, reverse=True)
        outcome.result = results[0][0]
        return outcome

    async def _one(self, asset: Asset, frame: str, semaphore: asyncio.Semaphore):
        async with semaphore:
            try:
                data = await asyncio.wait_for(
                    self.registry.fetch(asset, timeframe(frame)), timeout=FETCH_TIMEOUT
                )
                result = await asyncio.wait_for(
                    asyncio.to_thread(analyze_market_data, data), timeout=ANALYSIS_TIMEOUT
                )
                return result, frame
            except (DataUnavailable, asyncio.TimeoutError) as exc:
                logger.info("NEXUS analysis skipped %s %s: %s", asset.key, frame, exc)
                return None
            except Exception:
                logger.exception("NEXUS analysis failed for %s %s", asset.key, frame)
                return None


def _asset_by_key(assets: list[Asset], key: str) -> Asset:
    return next((asset for asset in assets if asset.key == key), assets[0])
