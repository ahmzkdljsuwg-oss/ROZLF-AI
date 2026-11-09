"""Read-only HTTP bridge for ExpertOption OTC/Smarty candles.

The operator must supply a bridge that reads their own ExpertOption session and
returns candles tagged with the exact market. ROZLF never logs in, never places
orders and never accepts data for a different market or platform.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from providers.base import BaseProvider, Candle, DataUnavailable, Quote, ensure_utc
from providers.catalog import Asset, Market, Timeframe


class ExpertOptionBridgeProvider(BaseProvider):
    id = "eo_bridge"
    name = "ExpertOption Bridge"
    markets = frozenset({Market.OTC, Market.SMARTY})
    can_serve_candles = True

    def __init__(self, base_url: str | None, api_key: str | None, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = (base_url or "").rstrip("/") or None
        self.api_key = api_key or None
        self._client = client
        self._owns_client = client is None

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key or "", "Accept": "application/json"}

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.configured:
            raise DataUnavailable("EO_BRIDGE_NOT_CONFIGURED", "No verified ExpertOption bridge is configured")
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0))
        try:
            response = await self._client.get(
                f"{self.base_url}{path}", params=params, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise DataUnavailable("NETWORK", f"ExpertOption bridge unreachable: {exc}") from exc
        if response.status_code == 401:
            raise DataUnavailable("EO_BRIDGE_UNAUTHORIZED", "ExpertOption bridge rejected the API key (EO_BRIDGE_KEY)")
        try:
            payload = response.json()
        except ValueError as exc:
            if response.status_code != 200:
                raise DataUnavailable(
                    "EO_BRIDGE_ERROR", f"ExpertOption bridge returned HTTP {response.status_code}"
                ) from exc
            raise DataUnavailable("BAD_RESPONSE", "ExpertOption bridge returned non-JSON data") from exc
        if not isinstance(payload, dict):
            raise DataUnavailable("BAD_RESPONSE", "ExpertOption bridge returned an unexpected payload")
        if response.status_code != 200:
            code = str(payload.get("error") or "EO_BRIDGE_ERROR")
            message = str(payload.get("message") or f"HTTP {response.status_code}")
            raise DataUnavailable(code, f"ExpertOption bridge: {message}", f"HTTP {response.status_code}")
        return payload

    async def fetch_assets(self, market: Market) -> list[dict[str, Any]]:
        payload = await self._get("/assets", {"market": market.value})
        rows = payload.get("assets")
        if not isinstance(rows, list) or not rows:
            raise DataUnavailable(
                "EMPTY",
                f"ExpertOption account exposes no {market.label} assets",
                f"bridge /assets?market={market.value} returned 0 instruments",
            )
        return [row for row in rows if isinstance(row, dict)]

    async def smarty(self) -> dict[str, Any]:
        """Live SMARTY instrument + candles; raises SMARTY_UNAVAILABLE when absent."""
        return await self._get("/smarty", {"timeframe": "1min", "limit": 2})

    async def health(self) -> dict[str, Any]:
        payload = await self._get("/health", {})
        return payload

    def status(self):
        status = super().status()
        detail = ""
        if not self.configured:
            detail = "EO_BRIDGE_URL / EO_BRIDGE_KEY not set"
        return status.__class__(
            id=status.id,
            name=status.name,
            configured=status.configured,
            can_serve_candles=status.can_serve_candles,
            markets=status.markets,
            detail=detail,
        )

    @staticmethod
    def _check_market(payload: dict[str, Any], asset: Asset) -> None:
        returned_market = str(payload.get("market") or "").lower()
        returned_symbol = str(payload.get("symbol") or "").upper().replace("/", "")
        if returned_market != asset.market.value:
            raise DataUnavailable(
                "SOURCE_MISMATCH",
                f"Bridge data is for market '{returned_market or 'unknown'}', not {asset.market.value}",
            )
        if returned_symbol and returned_symbol != asset.symbol.replace("/", ""):
            raise DataUnavailable(
                "SOURCE_MISMATCH",
                f"Bridge data is for {returned_symbol}, not {asset.symbol}",
            )

    async def fetch_candles(self, asset: Asset, tf: Timeframe, limit: int = 300) -> list[Candle]:
        payload = await self._get(
            "/candles",
            {
                "market": asset.market.value,
                "symbol": asset.bridge_symbol or asset.symbol,
                "timeframe": tf.code,
                "limit": max(60, limit),
            },
        )
        self._check_market(payload, asset)
        rows = payload.get("candles") or []
        candles: list[Candle] = []
        for row in rows:
            try:
                raw_time = row["time"]
                parsed = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
                candles.append(
                    Candle(
                        time=ensure_utc(parsed),
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
            raise DataUnavailable("EMPTY", f"Bridge returned no candles for {asset.display} {tf.code}")
        return candles

    async def fetch_quote(self, asset: Asset) -> Quote:
        payload = await self._get(
            "/quote",
            {"market": asset.market.value, "symbol": asset.bridge_symbol or asset.symbol},
        )
        self._check_market(payload, asset)
        try:
            bid = float(payload["bid"])
            ask = float(payload["ask"])
            ts = datetime.fromisoformat(str(payload["time"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError) as exc:
            raise DataUnavailable("BAD_RESPONSE", "Bridge quote is malformed") from exc
        return Quote(symbol=asset.symbol, bid=bid, ask=ask, time=ensure_utc(ts), source="ExpertOption Bridge")
