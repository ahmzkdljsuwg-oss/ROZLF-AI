"""Swissquote public bid/ask feed: quotes only, never candles."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from providers.base import BaseProvider, Candle, DataUnavailable, Quote
from providers.catalog import Asset, Market, Timeframe

URL = "https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/{symbol}"
_CACHE_TTL = 5.0


class SwissquoteProvider(BaseProvider):
    id = "swissquote"
    name = "Swissquote"
    markets = frozenset({Market.FOREX, Market.GOLD})
    can_serve_candles = False

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None
        self._cache: dict[str, tuple[float, Quote]] = {}

    def _supports(self, asset: Asset) -> bool:
        return asset.market in (Market.FOREX, Market.GOLD)

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_candles(self, asset: Asset, tf: Timeframe, limit: int = 300) -> list[Candle]:
        raise DataUnavailable("NO_CANDLES", "Swissquote is a quote source only")

    async def fetch_quote(self, asset: Asset) -> Quote:
        cached = self._cache.get(asset.symbol)
        now = time.monotonic()
        if cached and cached[0] > now:
            return cached[1]

        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=8.0))
        try:
            response = await self._client.get(URL.format(symbol=asset.symbol))
        except httpx.HTTPError as exc:
            raise DataUnavailable("NETWORK", f"Swissquote quote error: {exc}") from exc
        if response.status_code != 200:
            raise DataUnavailable("PROVIDER_ERROR", f"Swissquote returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DataUnavailable("BAD_RESPONSE", "Swissquote returned non-JSON data") from exc
        if not isinstance(payload, list) or not payload:
            raise DataUnavailable("EMPTY", "Swissquote returned no quotes")

        entry = payload[0]
        profiles = entry.get("spreadProfilePrices") or []
        if not profiles:
            raise DataUnavailable("EMPTY", "Swissquote quote has no bid/ask")
        profile = next((p for p in profiles if p.get("spreadProfile") == "elite"), profiles[0])
        try:
            bid = float(profile["bid"])
            ask = float(profile["ask"])
            ts = datetime.fromtimestamp(float(entry["ts"]) / 1000, tz=timezone.utc)
        except (KeyError, TypeError, ValueError) as exc:
            raise DataUnavailable("BAD_RESPONSE", "Swissquote quote is malformed") from exc
        quote = Quote(symbol=asset.symbol, bid=bid, ask=ask, time=ts, source="Swissquote")
        self._cache[asset.symbol] = (now + _CACHE_TTL, quote)
        return quote
