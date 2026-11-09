"""Twelve Data provider — real OHLC candles for Forex and gold."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import httpx

from .base import (
    MARKET_FOREX,
    Asset,
    Candle,
    DataUnavailable,
    ProviderError,
    ProviderStatus,
    Quote,
    SourceNotConfigured,
    MarketProvider,
    now_ts,
)

INTERVALS: dict[int, str] = {60: "1min", 300: "5min", 900: "15min", 1800: "30min", 3600: "1h"}
CACHE_TTL = 20


def td_symbol(symbol: str) -> str:
    if symbol == "XAUUSD":
        return "XAU/USD"
    if len(symbol) == 6:
        return f"{symbol[:3]}/{symbol[3:]}"
    return symbol


class TwelveDataProvider(MarketProvider):
    name = "twelvedata"
    title = "Twelve Data"
    markets = (MARKET_FOREX,)

    def __init__(self, api_key: str, base_url: str = "https://api.twelvedata.com", client: httpx.AsyncClient | None = None):
        self._api_key = (api_key or "").strip()
        self._base = base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=20.0)
        self._owns_client = client is None
        self._cache: dict[tuple[str, int], tuple[float, list[Candle]]] = {}
        self._last_update: int | None = None
        self._last_error = ""

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def supports(self, asset: Asset) -> bool:
        return asset.market == MARKET_FOREX and asset.market in self.markets

    def supported_timeframes(self, asset: Asset) -> tuple[int, ...]:
        return tuple(tf for tf in asset.timeframes if tf in INTERVALS)

    async def candles(self, asset: Asset, timeframe: int, limit: int = 200) -> list[Candle]:
        interval = INTERVALS.get(timeframe)
        if not interval:
            raise DataUnavailable(
                f"{asset.symbol}: الفريم {timeframe}s غير مدعوم من Twelve Data.",
                code="TIMEFRAME_UNSUPPORTED",
            )
        if not self.configured:
            raise SourceNotConfigured("TWELVE_DATA_API_KEY غير مضبوط.")

        key = (asset.symbol, timeframe)
        cached = self._cache.get(key)
        if cached and time.time() - cached[0] < CACHE_TTL:
            return list(cached[1])

        rows = await self._fetch(td_symbol(asset.symbol), interval, limit)
        candles = [
            Candle(
                time=int(r["_ts"]),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r.get("volume") or 0),
            )
            for r in rows
        ]
        candles.sort(key=lambda c: c.time)
        self._cache[key] = (time.time(), candles)
        self._last_update = now_ts()
        return candles

    async def _fetch(self, symbol: str, interval: str, limit: int) -> list[dict]:
        params = {
            "symbol": symbol,
            "interval": interval,
            "outputsize": max(80, min(limit, 500)),
            "timezone": "UTC",
            "apikey": self._api_key,
        }
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                resp = await self._client.get(f"{self._base}/time_series", params=params)
                if resp.status_code == 429:
                    raise ProviderError("Twelve Data: تجاوز حد الطلبات.", code="RATE_LIMIT", retryable=True)
                if resp.status_code >= 500:
                    raise ProviderError("Twelve Data: خطأ خادم مؤقت.", code="UPSTREAM", retryable=True)
                payload = resp.json()
                if isinstance(payload, dict) and payload.get("status") == "error":
                    message = str(payload.get("message") or "")
                    code = str(payload.get("code") or "")
                    if code == "401" or "apikey" in message.lower() or "api key" in message.lower():
                        raise ProviderError("Twelve Data: المفتاح غير صالح أو غير مفعّل.", code="AUTH")
                    if code == "429" or "limit" in message.lower():
                        raise ProviderError("Twelve Data: تجاوز حد الطلبات.", code="RATE_LIMIT", retryable=True)
                    raise ProviderError(f"Twelve Data: {message or 'استجابة غير متوقعة'}", code="UPSTREAM")
                values = payload.get("values") if isinstance(payload, dict) else None
                if not values:
                    raise DataUnavailable(f"لا توجد شموع لـ {symbol} على فريم {interval}.", code="NO_DATA")
                out = []
                for row in values:
                    dt = row.get("datetime", "")
                    out.append({**row, "_ts": _parse_utc(dt)})
                return out
            except (ProviderError, DataUnavailable) as exc:
                last_error = exc
                if getattr(exc, "retryable", False) and attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                raise
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                self._last_error = str(exc)
                raise ProviderError("تعذر الوصول إلى Twelve Data.", code="NETWORK", retryable=True) from exc
        raise ProviderError(f"Twelve Data غير متاح: {last_error}", code="NETWORK")

    async def quote(self, asset: Asset) -> Quote:
        rows = await self.candles(asset, 60, limit=5)
        last = rows[-1]
        return Quote(symbol=asset.symbol, price=last.close, time=last.time, source=self.name)

    async def status(self) -> ProviderStatus:
        return ProviderStatus(
            name=self.name,
            title=self.title,
            configured=self.configured,
            connected=bool(self._last_update),
            markets=self.markets,
            assets=8,
            last_update=self._last_update,
            detail="مصدر الشموع الحقيقي للفوركس والذهب." if self.configured else "غير مضبوط: أضف TWELVE_DATA_API_KEY.",
            quality="good" if self._last_update else "unknown",
            extra={"last_error": self._last_error},
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _parse_utc(value: str) -> int:
    text = (value or "").strip()
    if not text:
        raise ValueError("missing datetime")
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())
