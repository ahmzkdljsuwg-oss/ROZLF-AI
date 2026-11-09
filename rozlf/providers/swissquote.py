"""Swissquote public quote feed — live bid/ask used for spread and freshness checks.

It is quote-only: it never provides candles, so it can never be used to invent
a chart. The analysis engine only uses it to verify that the newest candle from
the candle provider is consistent with a live price.
"""

from __future__ import annotations

import httpx

from .base import (
    MARKET_FOREX,
    Asset,
    Candle,
    DataUnavailable,
    MarketProvider,
    ProviderError,
    ProviderStatus,
    Quote,
    now_ts,
)

BASE = "https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument"
PREFERRED_PROFILE = "elite"


def sq_symbol(symbol: str) -> str:
    if len(symbol) == 6:
        return f"{symbol[:3]}/{symbol[3:]}"
    return symbol


class SwissquoteProvider(MarketProvider):
    name = "swissquote"
    title = "Swissquote (أسعار حية للمقارنة)"
    markets = (MARKET_FOREX,)
    can_serve_candles = False

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client or httpx.AsyncClient(timeout=12.0)
        self._owns_client = client is None
        self._last_update: int | None = None
        self._last_error = ""

    def configured(self) -> bool:
        return True

    def supports(self, asset: Asset) -> bool:
        return asset.market == MARKET_FOREX

    def supported_timeframes(self, asset: Asset) -> tuple[int, ...]:
        return ()

    async def candles(self, asset: Asset, timeframe: int, limit: int = 200) -> list[Candle]:
        raise DataUnavailable(
            f"{asset.symbol}: Swissquote مصدر أسعار فقط ولا يوفر شموعاً.",
            code="QUOTE_ONLY",
        )

    async def quote(self, asset: Asset) -> Quote:
        url = f"{BASE}/{sq_symbol(asset.symbol)}"
        try:
            resp = await self._client.get(url)
        except httpx.HTTPError as exc:
            self._last_error = str(exc)
            raise ProviderError("تعذر الوصول إلى Swissquote.", code="NETWORK", retryable=True) from exc
        if resp.status_code != 200:
            raise ProviderError(f"Swissquote HTTP {resp.status_code}", code="UPSTREAM", retryable=resp.status_code >= 500)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ProviderError("Swissquote: استجابة غير قابلة للقراءة.", code="UPSTREAM") from exc
        if not isinstance(payload, list) or not payload:
            raise DataUnavailable(f"Swissquote: لا يوجد سعر لـ {asset.symbol}.", code="NO_DATA")

        chosen = None
        for block in payload:
            for price in block.get("spreadProfilePrices", []):
                if price.get("spreadProfile") == PREFERRED_PROFILE:
                    chosen = (block, price)
                    break
            if chosen:
                break
        if chosen is None:
            block = payload[0]
            prices = block.get("spreadProfilePrices") or []
            if not prices:
                raise DataUnavailable(f"Swissquote: لا يوجد سعر لـ {asset.symbol}.", code="NO_DATA")
            chosen = (block, prices[0])

        block, price = chosen
        ts_ms = int(block.get("ts") or 0)
        self._last_update = now_ts()
        return Quote(
            symbol=asset.symbol,
            price=round((float(price["bid"]) + float(price["ask"])) / 2, 8),
            bid=float(price["bid"]),
            ask=float(price["ask"]),
            time=int(ts_ms / 1000) if ts_ms else now_ts(),
            source=self.name,
        )

    async def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            title=self.title,
            configured=True,
            connected=bool(self._last_update),
            markets=self.markets,
            last_update=self._last_update,
            detail="أسعار bid/ask حية للتحقق من حداثة الشموع والسبريد.",
            quality="good" if self._last_update else "unknown",
            extra={"last_error": self._last_error, "quote_only": True},
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
