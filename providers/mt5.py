"""Read-only client for the ROZLF MT5 bridge.

Railway cannot host a MetaTrader 5 terminal, so this provider only talks to an
authenticated bridge running next to a logged-in MT5 terminal (Windows VPS or
the operator's own PC). Every payload is checked for market, symbol and source
before it can reach the analysis engine.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from providers.base import BaseProvider, Candle, DataUnavailable, Quote, ensure_utc
from providers.catalog import Asset, Market, Timeframe, mt5_asset


class MT5BridgeProvider(BaseProvider):
    id = "mt5"
    name = "MetaTrader 5 Bridge"
    markets = frozenset({Market.MT5})
    can_serve_candles = True

    def __init__(self, base_url: str | None, api_key: str | None, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = (base_url or "").rstrip("/") or None
        self.api_key = api_key or None
        self._client = client
        self._owns_client = client is None

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def status(self):
        status = super().status()
        detail = "" if self.configured else "MT5_BRIDGE_URL / MT5_BRIDGE_KEY not set"
        return status.__class__(
            id=status.id, name=status.name, configured=status.configured,
            can_serve_candles=status.can_serve_candles, markets=status.markets, detail=detail,
        )

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key or "", "Accept": "application/json"}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.configured:
            raise DataUnavailable("MT5_NOT_CONFIGURED", "MT5 bridge is not configured")
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
        try:
            response = await self._client.get(
                f"{self.base_url}{path}", params=params or {}, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise DataUnavailable("MT5_OFFLINE", "MT5 bridge is unreachable", str(exc)) from exc
        if response.status_code == 401:
            raise DataUnavailable("MT5_UNAUTHORIZED", "MT5 bridge rejected MT5_BRIDGE_KEY")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DataUnavailable("MT5_BAD_RESPONSE", f"MT5 bridge returned HTTP {response.status_code}") from exc
        if not isinstance(payload, dict):
            raise DataUnavailable("MT5_BAD_RESPONSE", "MT5 bridge returned an unexpected payload")
        if response.status_code != 200:
            code = str(payload.get("error") or "MT5_OFFLINE")
            message = str(payload.get("message") or f"HTTP {response.status_code}")
            raise DataUnavailable(code, f"MT5 bridge: {message}", f"HTTP {response.status_code}")
        return payload

    async def health(self) -> dict[str, Any]:
        return await self._get("/health")

    async def list_fx_symbols(self) -> list[dict[str, Any]]:
        """Broker FX symbols actually visible in Market Watch.

        No pair is invented: an empty list raises MT5_OFFLINE.
        """
        payload = await self._get("/symbols")
        rows = payload.get("symbols")
        if not payload.get("terminal_connected"):
            raise DataUnavailable("MT5_OFFLINE", "MT5 terminal is not connected")
        if not isinstance(rows, list):
            raise DataUnavailable("MT5_BAD_RESPONSE", "MT5 bridge returned no symbol list")
        result = [row for row in rows if isinstance(row, dict) and row.get("forex") is True]
        if not result:
            raise DataUnavailable("MT5_NO_SYMBOLS", "MT5 account exposes no FX pairs")
        return result

    async def fetch_candles(self, asset: Asset, tf: Timeframe, limit: int = 300) -> list[Candle]:
        payload = await self._get(
            "/candles",
            {"symbol": asset.bridge_symbol or asset.symbol.replace("/", ""),
             "timeframe": tf.code, "limit": max(220, limit)},
        )
        self._check_payload(payload, asset)
        rows = payload.get("candles") or []
        candles: list[Candle] = []
        for row in rows:
            try:
                parsed = datetime.fromisoformat(str(row["time"]).replace("Z", "+00:00"))
                candles.append(Candle(
                    time=ensure_utc(parsed),
                    open=float(row["open"]), high=float(row["high"]),
                    low=float(row["low"]), close=float(row["close"]),
                    volume=float(row.get("tick_volume") or row.get("volume") or 0.0),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        candles.sort(key=lambda candle: candle.time)
        if not candles:
            raise DataUnavailable("MT5_NO_DATA", f"MT5 returned no candles for {asset.symbol} {tf.label}")
        age = (datetime.now(timezone.utc) - candles[-1].time).total_seconds()
        if age > tf.seconds * 2 + 120:
            raise DataUnavailable(
                "MT5_STALE_DATA",
                f"MT5 candles for {asset.symbol} {tf.label} are {int(age)}s old",
            )
        return candles

    async def fetch_quote(self, asset: Asset) -> Quote:
        payload = await self._get("/quote", {"symbol": asset.bridge_symbol or asset.symbol.replace("/", "")})
        self._check_payload(payload, asset)
        try:
            bid = float(payload["bid"])
            ask = float(payload["ask"])
            parsed = datetime.fromisoformat(str(payload["time"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError) as exc:
            raise DataUnavailable("MT5_BAD_RESPONSE", "MT5 quote is malformed") from exc
        if bid <= 0 or ask <= 0 or ask < bid:
            raise DataUnavailable("MT5_BAD_QUOTE", f"MT5 returned an invalid quote for {asset.symbol}")
        age = (datetime.now(timezone.utc) - ensure_utc(parsed)).total_seconds()
        if age > 180:
            raise DataUnavailable("MT5_STALE_TICK", f"MT5 quote for {asset.symbol} is {int(age)}s old")
        return Quote(symbol=asset.symbol, bid=bid, ask=ask, time=ensure_utc(parsed), source="MetaTrader 5")

    @staticmethod
    def _check_payload(payload: dict[str, Any], asset: Asset) -> None:
        if str(payload.get("market") or "").lower() != Market.MT5.value:
            raise DataUnavailable("MT5_SOURCE_MISMATCH", "Bridge payload is not MT5 market data")
        if payload.get("source") != "MetaTrader 5" or payload.get("terminal_connected") is not True:
            raise DataUnavailable("MT5_OFFLINE", "MT5 terminal is not connected")
        canonical = str(payload.get("canonical") or "").upper().replace("/", "")
        expected = asset.symbol.replace("/", "").upper()
        if canonical != expected:
            raise DataUnavailable("MT5_SYMBOL_MISMATCH", f"Bridge returned {canonical or 'unknown'}, not {expected}")


def discovered_assets(rows: list[dict[str, Any]]) -> list[Asset]:
    """Build assets only for pairs the broker actually returned.

    A broker can list the same canonical pair twice (AUDCAD and AUDCAD.a), so
    the visible Market Watch entry wins and each pair appears exactly once.
    """
    chosen: dict[str, tuple[bool, Asset]] = {}
    for row in rows:
        canonical = str(row.get("canonical") or "").upper().replace("/", "")
        if len(canonical) != 6 or not canonical.isalpha():
            continue
        asset = mt5_asset(canonical, str(row.get("broker") or canonical),
                          str(row.get("description") or "") or None)
        visible = bool(row.get("visible"))
        current = chosen.get(canonical)
        if current is None or (visible and not current[0]):
            chosen[canonical] = (visible, asset)
    return [chosen[key][1] for key in sorted(chosen)]
