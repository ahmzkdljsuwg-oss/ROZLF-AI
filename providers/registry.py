"""Provider registry: one market cannot silently borrow another market's data."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Iterable

from engines.validation import validate_candles
from providers.base import BaseProvider, DataUnavailable, MarketData, Quote, utc_now
from providers.catalog import TIMEFRAME_MIN_BARS, Asset, Market, Timeframe, timeframe

logger = logging.getLogger(__name__)

QUOTE_PREFERENCE: dict[Market, tuple[str, ...]] = {
    Market.FOREX: ("swissquote", "twelvedata"),
    Market.MT5: ("mt5",),
    Market.GOLD: ("swissquote", "twelvedata"),
    Market.OTC: ("eo_bridge",),
    Market.SMARTY: ("eo_bridge",),
    Market.AI: ("eo_bridge",),
    Market.FOOTBALL: ("eo_bridge",),
    Market.LUXURY: ("eo_bridge",),
    Market.CRICKET: ("eo_bridge",),
}


class DataSourceRegistry:
    def __init__(self, providers: Iterable[BaseProvider], clock=utc_now, cache_ttl: float = 6.0) -> None:
        self._providers = list(providers)
        self._clock = clock
        self._cache_ttl = max(0.0, cache_ttl)
        self._cache: dict[tuple[str, str, int], tuple[float, MarketData]] = {}
        self._inflight: dict[tuple[str, str, int], asyncio.Task] = {}

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
        key = (asset.key, tf.code, int(limit))
        if self._cache_ttl <= 0:
            return await self._fetch_uncached(asset, tf, limit)

        cached = self._cache.get(key)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]
        pending = self._inflight.get(key)
        if pending is not None:
            return await pending

        task = asyncio.ensure_future(self._fetch_uncached(asset, tf, limit))
        self._inflight[key] = task
        try:
            data = await task
        finally:
            self._inflight.pop(key, None)
        self._cache[key] = (time.monotonic() + self._cache_ttl, data)
        return data

    async def _fetch_uncached(self, asset: Asset, tf: Timeframe, limit: int) -> MarketData:
        min_bars = TIMEFRAME_MIN_BARS[tf.code]
        attempts: list[str] = []

        for provider in self.providers_for(asset):
            if not provider.configured:
                attempts.append(f"{provider.name}: not configured")
                continue
            started = time.monotonic()
            try:
                candles = await provider.fetch_candles(asset, tf, limit=limit)
            except DataUnavailable as exc:
                logger.info("%s %s %s failed in %.0f ms: %s", provider.id, asset.key,
                            tf.code, (time.monotonic() - started) * 1000, exc.message)
                attempts.append(f"{provider.name}: {exc.message}")
                continue
            except Exception:  # defensive: a provider bug must not crash the bot
                logger.exception("provider %s crashed while fetching %s", provider.id, asset.key)
                attempts.append(f"{provider.name}: unexpected error")
                continue
            logger.info("%s %s %s fetched %d bars in %.0f ms", provider.id, asset.key, tf.code,
                        len(candles), (time.monotonic() - started) * 1000)

            report = validate_candles(candles, tf, now=self._clock(), min_bars=min_bars)
            if not report.ok:
                attempts.append(f"{provider.name}: {report.summary}")
                continue
            if report.stale:
                attempts.append(f"{provider.name}: stale data ({report.age_seconds}s old)")
                continue

            quote = await self._quote_with_fallback(asset, None, timeout=4.0)
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

    async def _quote_with_fallback(self, asset: Asset, skip_id: str | None, timeout: float | None = None) -> Quote | None:
        async def lookup() -> Quote | None:
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

        if timeout is None:
            return await lookup()
        try:
            return await asyncio.wait_for(lookup(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("quote lookup for %s exceeded %.1fs", asset.key, timeout)
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

    async def probe(self, asset: Asset, tf: Timeframe | str = "5min", limit: int = 200) -> dict[str, object]:
        """Fetch real candles once and report the true outcome for status panels."""
        try:
            data = await self.fetch(asset, tf, limit=limit)
        except DataUnavailable as exc:
            return {
                "ok": False,
                "asset": asset.display,
                "source": None,
                "code": exc.code,
                "error": exc.message,
                "detail": exc.detail,
            }
        return {
            "ok": True,
            "asset": asset.display,
            "source": data.source,
            "bars": data.validation.bar_count,
            "last_time": data.last_time,
            "error": None,
            "detail": None,
        }

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


def build_registry(config, bridge=None) -> DataSourceRegistry:
    """Wire every provider that has credentials configured."""
    from providers.eobridge import ExpertOptionBridgeProvider
    from providers.mt5 import MT5BridgeProvider
    from providers.swissquote import SwissquoteProvider
    from providers.yahoo import YahooForexProvider
    from providers.twelvedata import TwelveDataProvider

    bridge = bridge or ExpertOptionBridgeProvider(
        getattr(config, "bridge_url", None) or config.eo_bridge_url,
        config.eo_bridge_key,
    )
    return DataSourceRegistry(
        [
            MT5BridgeProvider(config.mt5_bridge_url, config.mt5_bridge_key),
            TwelveDataProvider(config.twelve_data_api_key),
            YahooForexProvider(),
            SwissquoteProvider(),
            bridge,
        ]
    )
