"""Signal generation: analysis first, persistence only for tradeable setups."""
from __future__ import annotations

from datetime import datetime

from config import Settings
from database.repository import Repository, SignalRecord
from engines.technical.analyzer import AnalysisResult, analyze_market_data
from providers.base import DataUnavailable, MarketData, utc_now
from providers.catalog import Asset, Market, Timeframe, get_asset, timeframe
from providers.registry import DataSourceRegistry

DURATIONS = (30, 60, 120, 180, 300, 900, 1800, 3600)
DURATION_LABELS = {
    30: "30 SEC",
    60: "1 MIN",
    120: "2 MIN",
    180: "3 MIN",
    300: "5 MIN",
    900: "15 MIN",
    1800: "30 MIN",
    3600: "1 HOUR",
}


def supported_durations(asset: Asset, tf: Timeframe) -> list[int]:
    """Durations that the analysis resolution can realistically verify."""
    if tf.seconds >= 3600:
        supported = [3600]
    elif tf.seconds >= 1800:
        supported = [1800, 3600]
    elif tf.seconds >= 900:
        supported = [900, 1800]
    elif tf.seconds >= 300:
        supported = [300, 900]
    else:
        supported = [60, 120, 180, 300]
        if asset.market in (Market.OTC, Market.SMARTY):
            supported.insert(0, 30)
    return supported


class SignalGenerator:
    def __init__(self, registry: DataSourceRegistry, repo: Repository, settings: Settings) -> None:
        self.registry = registry
        self.repo = repo
        self.settings = settings

    async def fetch_and_analyse(self, asset: Asset, tf: Timeframe | str) -> tuple[MarketData, AnalysisResult]:
        tf = timeframe(tf) if isinstance(tf, str) else tf
        market_data = await self.registry.fetch(asset, tf)
        result = analyze_market_data(market_data)
        return market_data, result

    async def create_signal(
        self,
        user_id: int,
        result: AnalysisResult,
        duration_seconds: int,
        now: datetime | None = None,
    ) -> SignalRecord:
        if result.direction not in ("UP", "DOWN"):
            raise ValueError("Only UP/DOWN analyses can become signals")
        asset = get_asset(result.asset_key)
        allowed = supported_durations(asset, timeframe(result.timeframe))
        if duration_seconds not in allowed:
            raise ValueError(f"Duration {duration_seconds}s is not supported for {result.timeframe}")
        now = now or utc_now()
        return await self.repo.add_signal(
            user_id=user_id,
            asset_key=result.asset_key,
            asset_display=result.asset_display,
            market=result.market,
            timeframe=result.timeframe,
            direction=result.direction,
            confidence=result.confidence,
            entry_price=result.price,
            source=result.source,
            reasons=result.reasons,
            warnings=result.warnings,
            expiry_seconds=duration_seconds,
            created_at=now,
        )

    async def generate(
        self,
        user_id: int,
        asset: Asset,
        tf: Timeframe | str,
        duration_seconds: int | None = None,
        min_confidence: float | None = None,
    ) -> tuple[AnalysisResult, SignalRecord | None]:
        threshold = min_confidence if min_confidence is not None else self.settings.min_confidence
        _, result = await self.fetch_and_analyse(asset, tf)
        if result.direction == "NO TRADE" or result.confidence < threshold:
            return result, None
        asset_obj = get_asset(result.asset_key)
        tf_obj = timeframe(result.timeframe)
        allowed = supported_durations(asset_obj, tf_obj)
        duration = duration_seconds if duration_seconds in allowed else min(
            allowed, key=lambda value: abs(value - tf_obj.seconds)
        )
        record = await self.create_signal(user_id, result, duration)
        return result, record

    async def scan_asset(self, asset: Asset, tf: Timeframe | str, min_confidence: float) -> AnalysisResult | None:
        try:
            _, result = await self.fetch_and_analyse(asset, tf)
        except DataUnavailable:
            return None
        if result.direction == "NO TRADE" or result.confidence < min_confidence:
            return None
        return result
