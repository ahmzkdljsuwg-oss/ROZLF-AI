"""HTTP client for the bot service that owns the real analysis engine.

The web service serves the Mini App shell and proxies authenticated API calls
to the bot service. Telegram initData is validated by the bot service because
only it holds ``TELEGRAM_BOT_TOKEN``; the web service never handles the token.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import aiohttp


class EngineUnavailable(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class EngineResponse:
    status: int
    body: bytes
    content_type: str
    headers: dict[str, str]


class EngineClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 30.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        base = base_url.rstrip("/")
        if base.endswith("/api/mini"):
            base = base[: -len("/api/mini")]
        self.base_url = base
        self.timeout_seconds = timeout_seconds
        self._session = session
        self._owns_session = session is None

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds)
            )
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._session is not None and self._owns_session and not self._session.closed:
            await self._session.close()

    def _headers(self, init_data: str | None) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if init_data:
            headers["X-Telegram-Init-Data"] = init_data
        return headers

    async def request(
        self,
        method: str,
        path: str,
        init_data: str | None = None,
        query: str = "",
        body: bytes | None = None,
    ) -> EngineResponse:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"
        headers = self._headers(init_data)
        if body:
            headers["Content-Type"] = "application/json"
        try:
            async with self.session.request(method, url, headers=headers, data=body) as response:
                payload = await response.read()
                return EngineResponse(
                    status=response.status,
                    body=payload,
                    content_type=response.headers.get("Content-Type", "application/json"),
                    headers={
                        key: response.headers[key]
                        for key in ("Cache-Control", "Retry-After")
                        if key in response.headers
                    },
                )
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise EngineUnavailable(
                "ENGINE_UNREACHABLE",
                "تعذر الاتصال بمحرك ROZLF AI. أعد المحاولة بعد قليل.",
            ) from exc

    async def health(self) -> dict:
        response = await self.request("GET", "/api/mini/health")
        try:
            return json.loads(response.body.decode("utf-8"))
        except Exception as exc:
            raise EngineUnavailable(
                "ENGINE_BAD_RESPONSE", "استجابة محرك ROZLF AI غير صالحة."
            ) from exc
