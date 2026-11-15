"""Gemini review client. It judges supplied evidence and never invents market data."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

SYSTEM_PROMPT = (
    "You are ROZLF AI, an independent reviewer of a computed trading analysis. "
    "Use ONLY the JSON evidence supplied. Never invent prices, candles, indicators or news. "
    "Decide strictly UP, DOWN or NO TRADE. Return JSON only: "
    '{"decision":"UP|DOWN|NO TRADE","confidence":0-100,"reason":"max 60 words"}. '
    "NO TRADE is correct when evidence is insufficient or contradictory."
)


class GeminiUnavailable(Exception):
    pass


class GeminiClient:
    def __init__(
        self,
        api_key: str | None,
        model: str = "gemini-2.5-flash",
        client: httpx.AsyncClient | None = None,
        timeout: float = 45.0,
    ) -> None:
        self.api_key = api_key or None
        self.model = model
        self._client = client
        self._owns_client = client is None
        self._timeout = timeout
        self.last_error: str | None = None
        self._online: bool | None = None
        self._checked_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def health(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "online": self._online,
            "model": self.model,
            "last_error": self.last_error,
        }

    async def check(self, max_age: float = 300.0) -> bool:
        if not self.configured:
            self._online = False
            return False
        loop = asyncio.get_running_loop()
        if self._online is not None and loop.time() - self._checked_at < max_age:
            return self._online
        try:
            await self._post("Reply with OK", timeout=5.0, attempts=1)
            self._online = True
            self.last_error = None
        except GeminiUnavailable as exc:
            self._online = False
            self.last_error = str(exc)
        self._checked_at = loop.time()
        return self._online

    async def _post(
        self,
        prompt: str,
        *,
        system_prompt: str = SYSTEM_PROMPT,
        json_mode: bool = True,
        timeout: float | None = None,
        attempts: int = 3,
    ) -> str:
        if not self.configured:
            raise GeminiUnavailable("GEMINI_API_KEY is not configured")
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout, connect=10.0))
        payload: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": 500},
        }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        url = f"{API_ROOT}/{self.model}:generateContent"
        last_error = "unknown Gemini failure"
        for attempt in range(max(1, attempts)):
            try:
                response = await self._client.post(
                    url,
                    params={"key": self.api_key},
                    json=payload,
                    timeout=timeout if timeout is not None else self._timeout,
                )
            except httpx.HTTPError as exc:
                # Never include the request URL: it carries the API key.
                last_error = f"network error ({type(exc).__name__})"
                if attempt + 1 < attempts:
                    await asyncio.sleep(1.0 * (attempt + 1))
                continue
            if response.status_code in (429, 500, 502, 503, 504):
                last_error = f"temporary Gemini failure ({response.status_code})"
                if attempt + 1 < attempts:
                    await asyncio.sleep(1.5 * (attempt + 1))
                continue
            if response.status_code != 200:
                self.last_error = f"Gemini HTTP {response.status_code}"
                raise GeminiUnavailable(self.last_error)
            try:
                data = response.json()
                parts = data["candidates"][0]["content"]["parts"]
                text = " ".join(part.get("text", "") for part in parts if isinstance(part, dict))
            except (KeyError, IndexError, TypeError, ValueError):
                self.last_error = "malformed Gemini response"
                raise GeminiUnavailable(self.last_error)
            text = text.strip()
            if not text:
                self.last_error = "empty Gemini completion"
                raise GeminiUnavailable(self.last_error)
            self.last_error = None
            return text
        self.last_error = last_error
        raise GeminiUnavailable(last_error)

    async def analyse_setup(self, payload: dict) -> str:
        return await self._post(
            "Review this computed market analysis and return the required JSON:\n"
            + str(payload)
        )
