"""Market scanner: walks the catalog and produces validated signal drafts."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from ...providers.base import MARKET_FOREX, MARKET_OTC, MARKET_SMARTY, Asset, DataUnavailable, ProviderError
from ...providers.catalog import assets_for, timeframe_label
from ...providers.registry import DataSourceRegistry
from ..technical.analyzer import NO_TRADE, analyze
from .generator import RiskPolicy, SignalDraft

log = logging.getLogger(__name__)

MARKET_TIMEFRAMES: dict[str, tuple[int, ...]] = {
    MARKET_FOREX: (300, 900, 1800),
    MARKET_OTC: (60, 300),
    MARKET_SMARTY: (60, 300),
}


@dataclass
class ScanResult:
    market: str
    signals: list[SignalDraft] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    started: int = 0
    finished: int = 0
    available: bool = True
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "market": self.market,
            "signals": [d.asset.symbol for d in self.signals],
            "skipped": len(self.skipped),
            "available": self.available,
            "detail": self.detail,
            "duration_ms": (self.finished - self.started) * 1000 if self.started else 0,
        }


class SignalScanner:
    def __init__(self, registry: DataSourceRegistry, policy: RiskPolicy, max_assets: int = 6):
        self.registry = registry
        self.policy = policy
        self.max_assets = max_assets

    async def scan_market(self, market: str, *, timeframes: tuple[int, ...] | None = None) -> ScanResult:
        market = market.upper()
        result = ScanResult(market=market, started=int(time.time()))
        assets = assets_for(market)[: self.max_assets]
        if not assets:
            result.available = False
            result.detail = "لا يوجد أصول مسجلة لهذا السوق."
            result.finished = int(time.time())
            return result

        overview = {row["market"]: row for row in await self.registry.market_overview()}
        row = overview.get(market, {})
        if not row.get("available"):
            result.available = False
            result.detail = str(row.get("detail") or "المصدر غير متاح لهذا السوق.")
            result.finished = int(time.time())
            return result

        frames = timeframes or MARKET_TIMEFRAMES.get(market, (300,))
        for asset in assets:
            best = await self._best_for_asset(asset, frames, result)
            if best is not None:
                result.signals.append(best)
        result.signals.sort(key=lambda d: d.analysis.score, reverse=True)
        result.signals = result.signals[: self.policy.max_per_scan]
        result.finished = int(time.time())
        return result

    async def _best_for_asset(self, asset: Asset, frames: tuple[int, ...], result: ScanResult) -> SignalDraft | None:
        best: SignalDraft | None = None
        for timeframe in frames:
            try:
                candles, report = await self.registry.candles(asset, timeframe, limit=220)
            except (DataUnavailable, ProviderError) as exc:
                result.skipped.append(
                    {"symbol": asset.symbol, "timeframe": timeframe_label(timeframe), "code": exc.code, "detail": str(exc)}
                )
                continue

            spread = None
            cross = await self.registry.cross_check(asset, candles[-1])
            if cross.get("checked"):
                spread = cross.get("spread")

            analysis = analyze(
                candles,
                timeframe,
                min_score=self.policy.min_score,
                validation=report,
                spread=spread,
            )
            if analysis.direction == NO_TRADE:
                result.skipped.append(
                    {
                        "symbol": asset.symbol,
                        "timeframe": timeframe_label(timeframe),
                        "code": "NO_TRADE",
                        "detail": "; ".join(analysis.warnings[:2]) or "لا توجد أفضلية واضحة.",
                        "score": analysis.score,
                    }
                )
                continue

            provider = self.registry.provider_for(asset)
            draft = SignalDraft(
                asset=asset,
                timeframe=timeframe,
                analysis=analysis,
                source=provider.name,
                validation_quality=report.quality,
                cross=cross,
                candles=candles,
            )
            if best is None or analysis.score > best.analysis.score:
                best = draft
        return best

    async def scan_all(self) -> list[ScanResult]:
        results = await asyncio.gather(
            *(self.scan_market(m) for m in (MARKET_FOREX, MARKET_OTC, MARKET_SMARTY)),
            return_exceptions=False,
        )
        return list(results)
