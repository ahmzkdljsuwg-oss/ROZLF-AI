"""Twelve Data OHLC provider (real forex + gold candles)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx

from providers.base import BaseProvider, Candle, DataUnavailable, Quote, utc_now
from providers.catalog import Asset, Market, Timeframe

BASE_URL = "https://api.twelvedata.com"
_CANDLE_CACHE_TTL = 20.0
_QUOTE_CACHE_TTL = 10.0


class TwelveDataProvider(BaseProvider):
    id = "twelvedata"
    name = "Twelve Data"
    markets = frozenset({Market.FOREX, Market.GOLD})
    can_serve_candles = True

    def __init__(self, api_key: str | None, client: httpx.AsyncClient | None = None) -> None:
        self.api_key = (api_key or "").strip()
        self._client = client
        self._owns_client = client is None
        self._cache: dict[tuple[str, str, int], tuple[float, list[Candle]]] = {}
        self._limited_until = 0.0
        self._quote_cache: dict[str, tuple[float, Quote]] = {}

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _supports(self, asset: Asset) -> bool:
        return asset.twelve_data_symbol is not None

    def status(self):
        status = super().status()
        detail = "live API key" if self.api_key else "TWELVE_DATA_API_KEY is not configured"
        return status.__class__(
            id=status.id,
            name=status.name,
            configured=status.configured,
            can_serve_candles=status.can_serve_candles,
            markets=status.markets,
            detail=detail,
        )

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0))
        return self._client

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _require_key(self) -> None:
        if not self.api_key:
            raise DataUnavailable(
                "NOT_CONFIGURED",
                "TWELVE_DATA_API_KEY is not configured; no verified FOREX/GOLD source is available",
            )

    def _check_cooldown(self):
        if time.monotonic() < self._limited_until:
            raise DataUnavailable("RATE_LIMITED", "Twelve Data is in quota cooldown")

    def _check_status(self, response):
        if response.status_code == 429:
            try:
                delay = float(response.headers.get("Retry-After", "60"))
            except (ValueError, TypeError):
                delay = 60
            self._limited_until = time.monotonic() + max(30, min(900, delay))
            raise DataUnavailable("RATE_LIMITED", "Twelve Data rate limit reached (HTTP 429)")

    def _check_payload(self, payload: Any, symbol: str) -> None:
        if not isinstance(payload, dict):
            raise DataUnavailable("BAD_RESPONSE", f"Twelve Data returned an unexpected payload for {symbol}")
        if payload.get("status") != "error" and "code" not in payload:
            return
        code = int(payload.get("code") or 0)
        message = str(payload.get("message") or "unknown error")
        if code == 429:
            self._limited_until = time.monotonic() + 60
            raise DataUnavailable("RATE_LIMITED", "Twelve Data rate limit reached", message)
        if code in (401, 403):
            raise DataUnavailable(
                "INVALID_KEY",
                "Twelve Data API key rejected",
                message,
            )
        if "not available" in message.lower() or "not found" in message.lower():
            raise DataUnavailable(
                "SYMBOL_NOT_IN_PLAN",
                f"Twelve Data does not serve {symbol} on this plan",
                message,
            )
        raise DataUnavailable("PROVIDER_ERROR", f"Twelve Data error for {symbol}: {message}", message)

    async def fetch_candles(self, asset: Asset, tf: Timeframe, limit: int = 300) -> list[Candle]:
        self._require_key()
        symbol = asset.twelve_data_symbol or ""
        key = (symbol, tf.code, int(limit))
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached and cached[0] > now:
            return list(cached[1])

        self._check_cooldown()
        client = await self._http()
        try:
            response = await client.get(
                f"{BASE_URL}/time_series",
                params={
                    "symbol": symbol,
                    "interval": tf.code,
                    "outputsize": max(60, min(limit, 5000)),
                    "timezone": "UTC",
                    "apikey": self.api_key,
                },
            )
        except httpx.HTTPError as exc:
            raise DataUnavailable("NETWORK", f"Twelve Data network error: {type(exc).__name__}") from exc

        self._check_status(response)
        if response.status_code >= 500:
            raise DataUnavailable("PROVIDER_DOWN", f"Twelve Data returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DataUnavailable("BAD_RESPONSE", "Twelve Data returned non-JSON data") from exc
        self._check_payload(payload, symbol)

        values = payload.get("values") or []
        candles: list[Candle] = []
        for row in values:
            try:
                candles.append(
                    Candle(
                        time=datetime.strptime(row["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row.get("volume") or 0.0),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        candles.sort(key=lambda candle: candle.time)
        if not candles:
            raise DataUnavailable("EMPTY", f"Twelve Data returned no candles for {symbol} {tf.code}")
        self._cache[key] = (now + _CANDLE_CACHE_TTL, candles)
        return list(candles)

    async def fetch_quote(self, asset: Asset) -> Quote:
        self._require_key()
        symbol = asset.twelve_data_symbol or ""
        cached = self._quote_cache.get(symbol)
        now = time.monotonic()
        if cached and cached[0] > now:
            return cached[1]

        self._check_cooldown()
        client = await self._http()
        try:
            response = await client.get(
                f"{BASE_URL}/price",
                params={"symbol": symbol, "apikey": self.api_key},
            )
            self._check_status(response)
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DataUnavailable("NETWORK", f"Twelve Data quote error: {type(exc).__name__}") from exc
        self._check_payload(payload, symbol)
        try:
            price = float(payload["price"])
        except (KeyError, TypeError, ValueError) as exc:
            raise DataUnavailable("EMPTY", f"Twelve Data returned no price for {symbol}") from exc
        quote = Quote(symbol=asset.symbol, bid=price, ask=price, time=utc_now(), source="Twelve Data")
        self._quote_cache[symbol] = (now + _QUOTE_CACHE_TTL, quote)
        return quote
