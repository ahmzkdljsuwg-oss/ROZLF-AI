"""ExpertOption bridge provider for OTC and Smarty instruments.

The bot deliberately never stores an ExpertOption session token. It talks to a
separate read-only bridge the operator already runs (the bridge owns the
session and exposes candle/asset reads). Without that bridge the OTC and
Smarty engines report DATA UNAVAILABLE instead of substituting Forex candles.
"""

from __future__ import annotations

import httpx

from .base import (
    MARKET_OTC,
    MARKET_SMARTY,
    Asset,
    Candle,
    DataUnavailable,
    MarketProvider,
    ProviderError,
    ProviderStatus,
    Quote,
    SourceNotConfigured,
    now_ts,
)


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


class ExpertOptionBridgeProvider(MarketProvider):
    name = "expertoption"
    title = "ExpertOption Bridge (قراءة فقط)"
    markets = (MARKET_OTC, MARKET_SMARTY)

    def __init__(self, base_url: str, key: str, client: httpx.AsyncClient | None = None, timeout: float = 20.0):
        self._base = (base_url or "").rstrip("/")
        self._key = (key or "").strip()
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None
        self._last_update: int | None = None
        self._last_error = ""
        self._connected = False

    @property
    def configured(self) -> bool:
        return bool(self._base and self._key)

    def supports(self, asset: Asset) -> bool:
        return asset.market in self.markets

    def supported_timeframes(self, asset: Asset) -> tuple[int, ...]:
        return asset.timeframes

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}

    async def _get(self, path: str, params: dict | None = None) -> object:
        if not self.configured:
            raise SourceNotConfigured(
                "جسر ExpertOption غير مضبوط: أضف EO_BRIDGE_URL وEO_BRIDGE_KEY. "
                "لن تُستخدم بيانات فوركس بديلاً عن OTC أو Smarty."
            )
        try:
            resp = await self._client.get(f"{self._base}{path}", params=params, headers=self._headers())
        except httpx.HTTPError as exc:
            self._connected = False
            self._last_error = str(exc)
            raise ProviderError("تعذر الوصول إلى جسر ExpertOption.", code="NETWORK", retryable=True) from exc
        if resp.status_code in (401, 403):
            self._connected = False
            raise ProviderError("جسر ExpertOption: مفتاح غير صالح.", code="AUTH")
        if resp.status_code >= 400:
            self._last_error = f"HTTP {resp.status_code}"
            raise ProviderError(f"جسر ExpertOption HTTP {resp.status_code}", code="UPSTREAM", retryable=resp.status_code >= 500)
        try:
            return resp.json()
        except ValueError as exc:
            raise ProviderError("جسر ExpertOption: استجابة غير قابلة للقراءة.", code="UPSTREAM") from exc

    async def candles(self, asset: Asset, timeframe: int, limit: int = 200) -> list[Candle]:
        if timeframe not in asset.timeframes:
            raise DataUnavailable(
                f"{asset.symbol}: الفريم {timeframe}s غير مدعوم لهذا الأصل.",
                code="TIMEFRAME_UNSUPPORTED",
            )
        params = {"instrument_id": asset.source_id or asset.symbol, "period": timeframe, "limit": limit}
        payload = await self._get("/sources/expertoption-session/candles", params)
        rows = _extract_rows(payload)
        if not rows:
            raise DataUnavailable(f"{asset.symbol}: لا توجد شموع من جلسة ExpertOption.", code="NO_DATA")
        candles: list[Candle] = []
        for row in rows:
            ts = int(_as_float(row.get("time") or row.get("timestamp") or row.get("t")))
            candles.append(
                Candle(
                    time=ts,
                    open=_as_float(row.get("open") or row.get("o")),
                    high=_as_float(row.get("high") or row.get("h")),
                    low=_as_float(row.get("low") or row.get("l")),
                    close=_as_float(row.get("close") or row.get("c")),
                    volume=_as_float(row.get("volume") or row.get("v")),
                )
            )
        candles.sort(key=lambda c: c.time)
        self._connected = True
        self._last_update = now_ts()
        return candles

    async def quote(self, asset: Asset) -> Quote:
        payload = await self._get("/sources/expertoption-session/quote", {"instrument_id": asset.source_id or asset.symbol})
        data = payload if isinstance(payload, dict) else {}
        price = _as_float(data.get("price") or data.get("close"))
        if price <= 0:
            raise DataUnavailable(f"{asset.symbol}: لا يوجد سعر حالي.", code="NO_DATA")
        return Quote(
            symbol=asset.symbol,
            price=price,
            time=int(_as_float(data.get("time")) or now_ts()),
            source=self.name,
        )

    async def status(self) -> ProviderStatus:
        detail = "متصل بجسر ExpertOption (قراءة فقط)."
        connected = self._connected
        if not self.configured:
            detail = "غير مضبوط: أضف EO_BRIDGE_URL وEO_BRIDGE_KEY."
        else:
            try:
                await self._get("/health")
                connected = True
                self._connected = True
            except ProviderError as exc:
                connected = False
                detail = f"الجسر غير متاح: {exc.code}"
        return ProviderStatus(
            name=self.name,
            title=self.title,
            configured=self.configured,
            connected=connected,
            markets=self.markets,
            assets=13,
            last_update=self._last_update,
            detail=detail,
            quality="good" if self._last_update else ("unknown" if connected else "unavailable"),
            extra={"last_error": self._last_error, "read_only": True},
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _extract_rows(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("candles", "data", "rows", "items", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []
