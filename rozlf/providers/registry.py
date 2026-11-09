"""Data Source Registry — the only place that decides which feed serves an asset."""

from __future__ import annotations

import logging

from ..config import Settings
from ..engines.validation import ValidationReport, validate_candles
from .base import (
    MARKET_FOREX,
    MARKET_OTC,
    MARKET_SMARTY,
    Asset,
    Candle,
    DataUnavailable,
    MarketProvider,
    ProviderError,
    Quote,
)
from .catalog import all_assets, assets_for, find, timeframe_label
from .eobridge import ExpertOptionBridgeProvider
from .swissquote import SwissquoteProvider
from .twelvedata import TwelveDataProvider

log = logging.getLogger(__name__)


class DataSourceRegistry:
    def __init__(self, providers: list[MarketProvider]):
        self._providers = providers

    @classmethod
    def from_settings(cls, settings: Settings) -> "DataSourceRegistry":
        providers: list[MarketProvider] = [
            TwelveDataProvider(settings.twelve_data_api_key, settings.twelve_data_base),
            SwissquoteProvider(),
            ExpertOptionBridgeProvider(settings.eo_bridge_url, settings.eo_bridge_key),
        ]
        return cls(providers)

    @property
    def providers(self) -> list[MarketProvider]:
        return list(self._providers)

    def provider_for(self, asset: Asset) -> MarketProvider:
        for provider in self._providers:
            if provider.can_serve_candles and provider.supports(asset):
                return provider
        raise DataUnavailable(f"{asset.symbol}: لا يوجد مصدر بيانات مسجل لهذا الأصل.", code="NO_PROVIDER")

    def quote_provider(self, asset: Asset) -> MarketProvider | None:
        for provider in self._providers:
            if isinstance(provider, SwissquoteProvider) and provider.supports(asset):
                return provider
        return None

    def asset(self, symbol: str) -> Asset:
        asset = find(symbol)
        if not asset:
            raise DataUnavailable(f"الأصل {symbol} غير موجود في الكتالوج.", code="UNKNOWN_ASSET")
        return asset

    def supported_timeframes(self, asset: Asset) -> tuple[int, ...]:
        try:
            provider = self.provider_for(asset)
        except DataUnavailable:
            return ()
        return provider.supported_timeframes(asset)

    async def candles(self, asset: Asset, timeframe: int, limit: int = 200) -> tuple[list[Candle], ValidationReport]:
        provider = self.provider_for(asset)
        candles = await provider.candles(asset, timeframe, limit)
        report = validate_candles(candles, timeframe)
        if not report.ok:
            raise DataUnavailable(
                f"{asset.symbol} {timeframe_label(timeframe)}: {report.detail}",
                code=report.code,
            )
        return candles, report

    async def cross_check(self, asset: Asset, last_candle: Candle) -> dict[str, object]:
        """Compare the newest candle close with a live quote from another feed."""
        provider = self.quote_provider(asset)
        if provider is None:
            return {"checked": False, "reason": "لا يوجد مصدر أسعار مستقل لهذا الأصل."}
        try:
            quote: Quote = await provider.quote(asset)
        except ProviderError as exc:
            return {"checked": False, "reason": f"تعذر التحقق: {exc.code}"}
        if last_candle.close <= 0:
            return {"checked": False, "reason": "سعر الشمعة غير صالح."}
        drift = abs(quote.price - last_candle.close) / last_candle.close
        return {
            "checked": True,
            "live_price": quote.price,
            "candle_close": last_candle.close,
            "drift_pct": round(drift * 100, 4),
            "spread": quote.spread,
            "source": quote.source,
            "consistent": drift < 0.004,
        }

    async def market_overview(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        statuses = await self.statuses()
        by_name = {s["name"]: s for s in statuses}
        td = by_name.get("twelvedata", {})
        bridge = by_name.get("expertoption", {})
        rows.append(
            {
                "market": MARKET_FOREX,
                "assets": len(assets_for(MARKET_FOREX)),
                "available": bool(td.get("configured")),
                "provider": "twelvedata",
                "detail": td.get("detail", ""),
            }
        )
        for market in (MARKET_OTC, MARKET_SMARTY):
            rows.append(
                {
                    "market": market,
                    "assets": len(assets_for(market)),
                    "available": bool(bridge.get("configured")) and bool(bridge.get("connected")),
                    "provider": "expertoption",
                    "detail": bridge.get("detail", ""),
                }
            )
        return rows

    async def statuses(self) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for provider in self._providers:
            try:
                status = await provider.status()
                out.append(status.as_dict())
            except Exception as exc:  # a broken feed must not break the dashboard
                log.warning("provider status failed: %s", exc)
                out.append(
                    {
                        "name": provider.name,
                        "title": provider.title,
                        "configured": False,
                        "connected": False,
                        "detail": f"خطأ في الحالة: {exc.__class__.__name__}",
                        "quality": "unknown",
                    }
                )
        return out

    def catalog_rows(self) -> list[dict[str, object]]:
        return [
            {
                "symbol": a.symbol,
                "name": a.name,
                "market": a.market,
                "provider": a.provider,
                "timeframes": [timeframe_label(tf) for tf in a.timeframes],
            }
            for a in all_assets()
        ]

    async def close(self) -> None:
        for provider in self._providers:
            try:
                await provider.close()
            except Exception:
                pass
