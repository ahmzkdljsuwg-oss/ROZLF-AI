"""Mistral text client. It explains supplied data; it never invents prices."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_URL = "https://api.mistral.ai/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are ROZLF AI, a disciplined market analyst inside a Telegram bot. "
    "Use ONLY the indicators, prices and structure supplied in the user message. "
    "Never invent prices, candles or news. If the data is insufficient, say so. "
    "Explain the direction (UP/DOWN/NO TRADE) with concrete indicator/SMC evidence. "
    "Be concise (max 120 words), professional, and add a one-line risk note. "
    "You do not execute trades and never promise profits."
)


class MistralUnavailable(Exception):
    pass


class MistralClient:
    def __init__(
        self,
        api_key: str | None,
        model: str = "mistral-small-latest",
        client: httpx.AsyncClient | None = None,
        timeout: float = 45.0,
    ) -> None:
        self.api_key = api_key or None
        self.model = model
        self._client = client
        self._owns_client = client is None
        self._timeout = timeout
        self.last_error: str | None = None

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
            "model": self.model,
            "last_error": self.last_error,
        }

    async def _post(self, payload: dict) -> str:
        if not self.configured:
            raise MistralUnavailable("MISTRAL_API_KEY is not configured")
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout, connect=10.0))
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last_error: str | None = None
        for attempt in range(3):
            try:
                response = await self._client.post(API_URL, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                last_error = f"network error: {exc}"
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            if response.status_code == 429:
                last_error = "rate limited (429)"
                await asyncio.sleep(2.0 * (attempt + 1))
                continue
            if response.status_code >= 500:
                last_error = f"server error ({response.status_code})"
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            if response.status_code != 200:
                self.last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                raise MistralUnavailable(self.last_error)
            try:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                self.last_error = f"malformed response: {exc}"
                raise MistralUnavailable(self.last_error) from exc
            if isinstance(content, list):
                content = " ".join(
                    part.get("text", "") for part in content if isinstance(part, dict)
                )
            text = str(content).strip()
            if not text:
                self.last_error = "empty completion"
                raise MistralUnavailable(self.last_error)
            self.last_error = None
            return text
        self.last_error = last_error or "unknown Mistral failure"
        raise MistralUnavailable(self.last_error)

    async def chat(self, user_prompt: str, system_prompt: str = SYSTEM_PROMPT, model: str | None = None) -> str:
        return await self._post(
            {
                "model": model or self.model,
                "temperature": 0.2,
                "max_tokens": 400,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
        )

    async def analyse_setup(self, payload: dict) -> str:
        prompt = (
            "Analyse this trading setup and explain the direction. "
            "Data (JSON):\n" + str(payload)
        )
        return await self.chat(prompt)

