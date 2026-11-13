"""HTTP client for the bot service that owns the real analysis engine.

The web service serves the Mini App shell and proxies authenticated API calls
to the bot service. Telegram initData is validated by the bot service because
only it holds ``TELEGRAM_BOT_TOKEN``; the web service never handles the token.
"""
from __future__ import annotations

import asyncio
import json
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import aiohttp


class EngineUnavailable(Exception):
    def __init__(self, code: str, message: str, *, detail: str = "", elapsed_ms: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail
        self.elapsed_ms = elapsed_ms


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
        timeout_seconds: float = 20.0,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        base = base_url.strip().rstrip("/")
        if base.endswith("/api/mini"):
            base = base[: -len("/api/mini")]
        self.base_url = base
        self.timeout_seconds = timeout_seconds
        self._session = session
        self._owns_session = session is None
        self.last_peer: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    @property
    def safe_url(self) -> str:
        parts = urlsplit(self.base_url)
        host = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        return f"{parts.scheme}://{host}{port}{parts.path}".rstrip("/")

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds, connect=8.0)
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
        started = time.monotonic()
        try:
            async with self.session.request(method, url, headers=headers, data=body) as response:
                payload = await response.read()
                connection = response.connection
                if connection is not None and connection.transport is not None:
                    peer = connection.transport.get_extra_info("peername")
                    if peer:
                        self.last_peer = str(peer[0])
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
        except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
            elapsed = int((time.monotonic() - started) * 1000)
            raise EngineUnavailable(
                "ENGINE_UNREACHABLE",
                "تعذر الاتصال بمحرك ROZLF AI. أعد المحاولة بعد قليل.",
                detail=f"{type(exc).__name__}: {exc}"[:300],
                elapsed_ms=elapsed,
            ) from exc

    async def health(self) -> dict:
        response = await self.request("GET", "/api/mini/health")
        try:
            return json.loads(response.body.decode("utf-8"))
        except Exception as exc:
            raise EngineUnavailable(
                "ENGINE_BAD_RESPONSE", "استجابة محرك ROZLF AI غير صالحة."
            ) from exc

    async def probe(self) -> dict:
        """Bounded connectivity probe: DNS, TCP/TLS, then the real health route."""
        parts = urlsplit(self.base_url)
        host = parts.hostname or ""
        secure = parts.scheme != "http"
        port = parts.port or (443 if secure else 80)
        report: dict = {
            "upstream": self.safe_url,
            "host": host,
            "port": port,
        }
        loop = asyncio.get_running_loop()
        started = time.monotonic()
        try:
            infos = await asyncio.wait_for(
                loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=6.0
            )
            report["dns"] = sorted({item[4][0] for item in infos})
            report["dns_ms"] = int((time.monotonic() - started) * 1000)
        except Exception as exc:
            report["dns_error"] = f"{type(exc).__name__}: {exc}"[:200]
            return report

        started = time.monotonic()
        writer = None
        try:
            context = ssl.create_default_context() if secure else None
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, ssl=context, server_hostname=host if secure else None),
                timeout=8.0,
            )
            peer = writer.get_extra_info("peername")
            report["peer"] = str(peer[0]) if peer else None
            report["connect_ms"] = int((time.monotonic() - started) * 1000)
            writer.close()
            await writer.wait_closed()
        except Exception as exc:
            report["connect_error"] = f"{type(exc).__name__}: {exc}"[:200]
            report["connect_ms"] = int((time.monotonic() - started) * 1000)
            if writer is not None:
                writer.close()
            return report

        started = time.monotonic()
        try:
            response = await self.request("GET", "/api/mini/health")
            report["http_status"] = response.status
            report["http_ms"] = int((time.monotonic() - started) * 1000)
            try:
                report["body"] = json.loads(response.body.decode("utf-8"))
            except Exception:
                report["body_bytes"] = len(response.body)
        except EngineUnavailable as exc:
            report["http_error"] = exc.detail
            report["http_ms"] = exc.elapsed_ms
        return report
