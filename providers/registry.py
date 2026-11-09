"""Provider registry: one market cannot silently borrow another market's data."""
from __future__ import annotations

import logging
from typing import Iterable

from engines.validation import validate_candles
from providers.base import BaseProvider, DataUnavailable, MarketData, Quote, utc_now
from providers.catalog import TIMEFRAME_MIN_BARS, Asset, Market, Timeframe, timeframe

logger = logging.getLogger(__name__)

QUOTE_PREFERENCE: dict[Market, tuple[str, ...]] = {
    Market.FOREX: ("swissquote", "twelvedata"),
    Market.GOLD: ("swissquote", "twelvedata"),
    Market.OTC: ("eo_bridge",),
    Market.SMARTY: ("eo_bridge",),
}


class DataSourceRegistry:
    def __init__(self, providers: Iterable[BaseProvider], clock=utc_now) -> None:
        self._providers = list(providers)
        self._clock = clock

    @property
    def providers(self) -> list[BaseProvider]:
        return list(self._providers)

    def add(self, provider: BaseProvider) -> None:
        self._providers.append(provider)

    def providers_for(self, asset: Asset, candles_only: bool = True) -> list[BaseProvider]:
        return [
            provider
            for provider in self._providers
            if provider.supports(asset) and (provider.can_serve_candles or not candles_only)
        ]

    def _ordered_for_quote(self, asset: Asset) -> list[BaseProvider]:
        available = {provider.id: provider for provider in self.providers_for(asset, candles_only=False)}
        ordered: list[BaseProvider] = []
        for provider_id in QUOTE_PREFERENCE.get(asset.market, ()):
            if provider_id in available:
                ordered.append(available.pop(provider_id))
        ordered.extend(available.values())
        return ordered

    async def fetch(self, asset: Asset, tf: Timeframe | str = "5min", limit: int = 300) -> MarketData:
        tf = timeframe(tf) if isinstance(tf, str) else tf
        min_bars = TIMEFRAME_MIN_BARS[tf.code]
        attempts: list[str] = []

        for provider in self.providers_for(asset):
            if not provider.configured:
                attempts.append(f"{provider.name}: not configured")
                continue
            try:
                candles = await provider.fetch_candles(asset, tf, limit=limit)
            except DataUnavailable as exc:
                attempts.append(f"{provider.name}: {exc.message}")
                continue
            except Exception:  # defensive: a provider bug must not crash the bot
                logger.exception("provider %s crashed while fetching %s", provider.id, asset.key)
                attempts.append(f"{provider.name}: unexpected error")
                continue

            report = validate_candles(candles, tf, now=self._clock(), min_bars=min_bars)
            if not report.ok:
                attempts.append(f"{provider.name}: {report.summary}")
                continue
            if report.stale:
                attempts.append(f"{provider.name}: stale data ({report.age_seconds}s old)")
                continue

            quote = await self._quote_with_fallback(asset, None)
            return MarketData(
                asset=asset,
                timeframe=tf,
                candles=sorted(candles, key=lambda candle: candle.time),
                source=provider.name,
                quote=quote,
                validation=report,
            )

        detail = "; ".join(attempts) or "no provider registered for this market"
        raise DataUnavailable(
            "DATA_UNAVAILABLE",
            f"DATA UNAVAILABLE — no verified source for {asset.display} {tf.label}",
            detail,
        )

    async def _quote_with_fallback(self, asset: Asset, skip_id: str | None) -> Quote | None:
        for provider in self._ordered_for_quote(asset):
            if provider.id == skip_id:
                continue
            if not provider.configured:
                continue
            try:
                return await provider.fetch_quote(asset)
            except DataUnavailable:
                continue
            except Exception:
                logger.exception("provider %s crashed while quoting %s", provider.id, asset.key)
        return None

    async def fetch_quote(self, asset: Asset) -> Quote:
        quote = await self._quote_with_fallback(asset, None)
        if quote is None:
            raise DataUnavailable("QUOTE_UNAVAILABLE", f"No verified quote source for {asset.display}")
        return quote

    async def quote_for_verification(self, asset: Asset, max_age_seconds: float) -> Quote:
        quote = await self.fetch_quote(asset)
        age = quote.age_seconds(self._clock())
        if age > max_age_seconds:
            raise DataUnavailable("STALE_QUOTE", f"{asset.display} quote is {int(age)}s old")
        return quote

    def statuses(self) -> list[dict[str, object]]:
        return [provider.status().as_dict() for provider in self._providers]

    def source_summary(self, asset: Asset) -> str:
        names = [p.name for p in self.providers_for(asset) if p.configured]
        return ", ".join(names) if names else "NONE"

    async def close(self) -> None:
        for provider in self._providers:
            try:
                await provider.close()
            except Exception:
                logger.exception("failed closing provider %s", provider.id)


def build_registry(config) -> DataSourceRegistry:
    """Wire every provider that has credentials configured."""
    from providers.eobridge import ExpertOptionBridgeProvider
    from providers.swissquote import SwissquoteProvider
    from providers.twelvedata import TwelveDataProvider

    registry = DataSourceRegistry(
        [
            TwelveDataProvider(config.twelve_data_api_key),
            SwissquoteProvider(),
            ExpertOptionBridgeProvider(config.eo_bridge_url, config.eo_bridge_key),
        ]
    )
    return registry
