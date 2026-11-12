"""Keyless FOREX candles from Yahoo Finance's public chart endpoint.

Real, delayed interbank FX quotes — no API key required. It is a fallback only:
FOREX pairs only, never OTC, never SMARTY, never a substitute instrument.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from providers.base import BaseProvider, Candle, DataUnavailable, ensure_utc
from providers.catalog import Asset, Market, Timeframe

INTERVAL = {"1min": "1m", "5min": "5m", "15min": "15m", "30min": "30m", "1h": "60m"}
# Yahoo caps how far back each interval may reach.
RANGE = {"1min": "5d", "5min": "1mo", "15min": "1mo", "30min": "1mo", "1h": "3mo"}
BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"


class YahooForexProvider(BaseProvider):
    id = "yahoo"
    name = "Yahoo Finance FX"
    markets = frozenset({Market.FOREX})
    can_serve_candles = True

    def __init__(self, client: httpx.AsyncClient | None = None, timeout: float = 15.0) -> None:
        self._client = client
        self._owns = client is None
        self._timeout = timeout

    async def close(self) -> None:
        if self._owns and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _get(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
                headers={"User-Agent": "Mozilla/5.0 (compatible; ROZLF-AI/1.0)"},
            )
        return self._client

    @staticmethod
    def yahoo_symbol(asset: Asset) -> str:
        return asset.symbol.replace("/", "") + "=X"

    async def fetch_candles(self, asset: Asset, tf: Timeframe, limit: int = 300) -> list[Candle]:
        if asset.market is not Market.FOREX:
            raise DataUnavailable("UNSUPPORTED_MARKET", f"{self.name} serves FOREX only, not {asset.market.value}")
        interval = INTERVAL.get(tf.code)
        if interval is None:
            raise DataUnavailable("UNSUPPORTED_TIMEFRAME", f"{self.name} has no {tf.code} candles")
        client = await self._get()
        symbol = self.yahoo_symbol(asset)
        try:
            response = await client.get(
                BASE + symbol, params={"interval": interval, "range": RANGE[tf.code]}
            )
        except httpx.HTTPError as exc:
            raise DataUnavailable("NETWORK", f"{self.name} unreachable: {exc}") from exc
        if response.status_code != 200:
            raise DataUnavailable("HTTP_ERROR", f"{self.name} returned HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DataUnavailable("BAD_RESPONSE", f"{self.name} returned non-JSON data") from exc
        chart = payload.get("chart") or {}
        if chart.get("error"):
            raise DataUnavailable("BAD_REQUEST", f"{self.name}: {chart['error'].get('description')}")
        results = chart.get("result") or []
        if not results:
            raise DataUnavailable("EMPTY", f"{self.name} returned no series for {symbol}")
        result = results[0]
        stamps = result.get("timestamp") or []
        quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        opens = quotes.get("open") or []
        highs = quotes.get("high") or []
        lows = quotes.get("low") or []
        closes = quotes.get("close") or []
        volumes = quotes.get("volume") or []

        candles: list[Candle] = []
        for index, stamp in enumerate(stamps):
            try:
                o, h, low_, c = opens[index], highs[index], lows[index], closes[index]
                if None in (o, h, low_, c):
                    continue
                candles.append(
                    Candle(
                        time=ensure_utc(datetime.fromtimestamp(float(stamp), tz=timezone.utc)),
                        open=float(o),
                        high=float(h),
                        low=float(low_),
                        close=float(c),
                        volume=float(volumes[index] or 0.0) if index < len(volumes) else 0.0,
                    )
                )
            except (IndexError, TypeError, ValueError):
                continue
        candles.sort(key=lambda candle: candle.time)
        if not candles:
            raise DataUnavailable("EMPTY", f"{self.name} returned no usable candles for {symbol}")
        return candles[-limit:]

    def status(self):
        status = super().status()
        return status.__class__(
            id=status.id,
            name=status.name,
            configured=status.configured,
            can_serve_candles=status.can_serve_candles,
            markets=status.markets,
            detail="public delayed FX feed (no key)",
        )
