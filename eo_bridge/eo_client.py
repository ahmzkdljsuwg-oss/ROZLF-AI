"""Read-only ExpertOption websocket client used by the bridge.

Protocol notes (unofficial, verified against the public ExpertOption web client
message flow): every request carries the session token; candles arrive either as
`assetHistoryCandles` (history windows) or `candles` (live updates).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any

import aiohttp

from .catalog import Instrument
from .settings import BridgeSettings

logger = logging.getLogger("eo_bridge.client")

HEADERS = {
    "Origin": "https://app.expertoption.com",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


class BridgeError(Exception):
    """Raised when ExpertOption data cannot be provided honestly."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class Candle:
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.time)),
            "timestamp": self.time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


class ExpertOptionClient:
    def __init__(self, settings: BridgeSettings) -> None:
        self.settings = settings
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._runner: asyncio.Task[None] | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._ping_task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()
        self._stopping = False
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._candles: dict[tuple[int, int], dict[int, Candle]] = {}
        self._subscriptions: set[tuple[int, int]] = set()
        self._assets: list[Instrument] = []
        self._assets_loaded_at = 0.0
        self._last_message_at = 0.0
        self._last_error: str | None = None
        self._token: str | None = settings.eo_token
        self._request_lock = asyncio.Lock()

    # ---------------------------------------------------------------- lifecycle
    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    @property
    def assets(self) -> list[Instrument]:
        return list(self._assets)

    def status(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "token_set": bool(self._token),
            "region": self.settings.eo_region,
            "demo": self.settings.eo_demo,
            "assets": len(self._assets),
            "last_message_age_seconds": (
                round(time.time() - self._last_message_at, 1) if self._last_message_at else None
            ),
            "last_error": self._last_error,
        }

    async def start(self) -> None:
        if not self.settings.eo_token:
            self._last_error = "EO_TOKEN_MISSING"
            logger.warning("EO_TOKEN is not set; bridge will answer DATA_UNAVAILABLE")
            return
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._supervise(), name="eo-client")

    async def stop(self) -> None:
        self._stopping = True
        for task in (self._ping_task, self._receive_task, self._runner):
            if task is not None:
                task.cancel()
        for task in (self._ping_task, self._receive_task, self._runner):
            if task is not None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        await self._close_socket()
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _supervise(self) -> None:
        backoff = 1.0
        while not self._stopping:
            try:
                await self._connect_once()
                backoff = 1.0
                await self._wait_closed()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - surfaced through /health
                self._last_error = f"{type(exc).__name__}: {exc}"
                logger.warning("ExpertOption connection failed: %s", self._last_error)
            finally:
                self._connected.clear()
                for future in self._pending.values():
                    if not future.done():
                        future.set_exception(BridgeError("DISCONNECTED", "ExpertOption socket closed"))
                self._pending.clear()
                await self._close_socket()
            if self._stopping:
                break
            delay = min(30.0, backoff) + random.uniform(0, 1.0)
            logger.info("Reconnecting to ExpertOption in %.1fs", delay)
            await asyncio.sleep(delay)
            backoff = min(30.0, backoff * 2)

    async def _connect_once(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        logger.info("Connecting to %s", self.settings.ws_url)
        self._ws = await self._session.ws_connect(
            self.settings.ws_url,
            headers=HEADERS,
            heartbeat=25,
            compress=15,
            max_msg_size=0,
        )
        self._last_error = None
        self._receive_task = asyncio.create_task(self._receive_loop(), name="eo-recv")
        self._ping_task = asyncio.create_task(self._ping_loop(), name="eo-ping")
        await self._handshake()

    async def _wait_closed(self) -> None:
        if self._receive_task is not None:
            await self._receive_task

    async def _close_socket(self) -> None:
        for task in (self._ping_task, self._receive_task):
            if task is not None and task is not asyncio.current_task():
                task.cancel()
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        self._ws = None
        self._ping_task = None
        self._receive_task = None
        self._connected.clear()

    # ------------------------------------------------------------------ sending
    async def _send(self, payload: dict[str, Any]) -> None:
        if self._ws is None or self._ws.closed:
            raise BridgeError("DISCONNECTED", "ExpertOption socket is not connected")
        payload.setdefault("token", self._token)
        payload.setdefault("v", 23)
        await self._ws.send_str(json.dumps(payload))

    async def request(self, action: str, message: Any, timeout: float = 12.0) -> dict[str, Any]:
        if self._ws is None or self._ws.closed:
            raise BridgeError("DISCONNECTED", "ExpertOption socket is not connected")
        ns = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[ns] = future
        try:
            await self._send({"action": action, "message": message, "ns": ns})
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise BridgeError("TIMEOUT", f"ExpertOption did not answer {action}") from exc
        finally:
            self._pending.pop(ns, None)

    async def _ping_loop(self) -> None:
        while self._ws is not None and not self._ws.closed:
            with contextlib.suppress(Exception):
                await self._send({"action": "ping", "message": {}})
            await asyncio.sleep(25)

    # ----------------------------------------------------------------- receiving
    async def _receive_loop(self) -> None:
        assert self._ws is not None
        async for message in self._ws:
            self._last_message_at = time.time()
            if message.type is not aiohttp.WSMsgType.TEXT:
                continue
            try:
                data = json.loads(message.data)
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict):
                self._dispatch(data)
        if self._ws is not None and self._ws.exception() is not None:
            raise BridgeError("SOCKET", str(self._ws.exception()))

    def _dispatch(self, data: dict[str, Any]) -> None:
        action = data.get("action")
        ns = str(data.get("ns")) if data.get("ns") else None
        if action == "error":
            detail = data.get("message")
            if ns and ns in self._pending and not self._pending[ns].done():
                self._pending[ns].set_exception(BridgeError("EO_ERROR", str(detail)))
            else:
                self._last_error = f"EO: {detail}"
            return
        if action == "token":
            new_token = (data.get("message") or {}).get("token")
            if isinstance(new_token, str) and new_token:
                self._token = new_token
            return
        if action == "multipleAction":
            for sub in (data.get("message") or {}).get("actions") or []:
                self._dispatch(dict(sub))
            return
        if action in {"candles", "assetHistoryCandles"}:
            self._ingest_candles(data.get("message") or {})
        if action == "assets":
            raw_assets = (data.get("message") or {}).get("assets") or []
            if raw_assets:
                from .catalog import build_instruments

                self._assets = build_instruments(raw_assets)
                self._assets_loaded_at = time.time()
                self._connected.set()
        if ns and ns in self._pending and not self._pending[ns].done():
            self._pending[ns].set_result(data)

    def _ingest_candles(self, message: dict[str, Any]) -> None:
        try:
            asset_id = int(message.get("assetId") or message.get("assetid") or 0)
            tf = int(message.get("tf") or 0)
        except (TypeError, ValueError):
            return
        if not asset_id or not tf:
            return
        bucket = self._candles.setdefault((asset_id, tf), {})
        for block in message.get("candles") or []:
            periods = block.get("periods") if isinstance(block, dict) else None
            if periods:
                for period in periods:
                    try:
                        start = int(period[0])
                        rows = period[1] or []
                    except (IndexError, TypeError, ValueError):
                        continue
                    self._store_rows(bucket, [(start + index * tf, row) for index, row in enumerate(rows)])
                continue
            # Live candle shapes: {"t": ts, "v": [o,h,l,c]} or [ts, [o,h,l,c]]
            if isinstance(block, dict) and "t" in block and isinstance(block.get("v"), list):
                self._store_rows(bucket, [(int(block["t"]), block["v"])])
            elif isinstance(block, list) and len(block) >= 2 and isinstance(block[1], list):
                self._store_rows(bucket, [(int(block[0]), block[1])])

    @staticmethod
    def _store_rows(bucket: dict[int, Candle], pairs: list[tuple[int, list]]) -> None:
        for timestamp, row in pairs:
            if not isinstance(row, list) or len(row) < 4:
                continue
            try:
                bucket[timestamp] = Candle(
                    time=timestamp,
                    open=float(row[0]),
                    high=float(row[1]),
                    low=float(row[2]),
                    close=float(row[3]),
                    volume=float(row[4]) if len(row) > 4 and row[4] is not None else 0.0,
                )
            except (TypeError, ValueError):
                continue

    # ------------------------------------------------------------------ handshake
    async def _handshake(self) -> None:
        actions = [
            {"action": "profile", "ns": str(uuid.uuid4())},
            {"action": "assets", "ns": str(uuid.uuid4())},
            {"action": "getCandlesTimeframes", "ns": str(uuid.uuid4())},
            {"action": "setTimeZone", "message": {"timeZone": 0}, "ns": str(uuid.uuid4())},
        ]
        ns = str(uuid.uuid4())
        await self._send(
            {
                "action": "multipleAction",
                "ns": ns,
                "message": {"token": self._token, "actions": actions},
            }
        )
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not self._assets:
            if self._last_error and "error" in self._last_error.lower():
                raise BridgeError("AUTH_FAILED", self._last_error)
            await asyncio.sleep(0.1)
        if not self._assets:
            raise BridgeError("AUTH_FAILED", "ExpertOption returned no assets; token is invalid or expired")
        self._connected.set()
        self._last_error = None
        logger.info("ExpertOption authenticated: %d instruments", len(self._assets))

    async def refresh_assets(self) -> list[Instrument]:
        response = await self.request("assets", None, timeout=15.0)
        raw_assets = (response.get("message") or {}).get("assets") or []
        if raw_assets:
            from .catalog import build_instruments

            self._assets = build_instruments(raw_assets)
            self._assets_loaded_at = time.time()
        return self.assets

    async def ensure_assets(self, max_age_seconds: float = 300.0) -> list[Instrument]:
        if self._runner is None or self._runner.done():
            await self.start()
        if not self.settings.eo_token:
            raise BridgeError("EO_TOKEN_MISSING", "Bridge has no ExpertOption session token")
        if not self.connected:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._connected.wait(), timeout=15.0)
        if not self.connected:
            raise BridgeError(
                "DISCONNECTED",
                self._last_error or "ExpertOption socket is not connected",
            )
        if not self._assets or time.time() - self._assets_loaded_at > max_age_seconds:
            await self.refresh_assets()
        if not self._assets:
            raise BridgeError("AUTH_FAILED", "ExpertOption returned no assets")
        return self.assets

    # -------------------------------------------------------------------- candles
    async def get_candles(self, instrument: Instrument, tf_seconds: int, limit: int = 300) -> list[Candle]:
        if not self.connected:
            raise BridgeError("DISCONNECTED", "ExpertOption socket is not connected")
        key = (instrument.id, tf_seconds)
        bucket = self._candles.setdefault(key, {})
        async with self._request_lock:
            if key not in self._subscriptions:
                await self.request(
                    "subscribeCandles",
                    {"assets": [{"id": instrument.id, "timeframes": [tf_seconds]}]},
                    timeout=8.0,
                )
                self._subscriptions.add(key)
            needed = max(limit, 60)
            span = max(self.settings.candle_history_seconds, tf_seconds * needed)
            end = int(time.time())
            for _ in range(3):
                if len(bucket) >= needed:
                    break
                start = end - span
                with contextlib.suppress(BridgeError):
                    await self.request(
                        "assetHistoryCandles",
                        {
                            "assetid": instrument.id,
                            "periods": [[start, end]],
                            "timeframes": [tf_seconds],
                        },
                        timeout=8.0,
                    )
                await asyncio.sleep(0.4)
                if bucket:
                    end = min(bucket) - 1
                span = max(span, tf_seconds * needed)
        candles = [bucket[ts] for ts in sorted(bucket)][-limit:]
        if not candles:
            raise BridgeError("NO_CANDLES", f"ExpertOption returned no candles for {instrument.symbol} tf={tf_seconds}")
        return candles

    async def get_quote(self, instrument: Instrument) -> tuple[Candle, int]:
        candles = await self.get_candles(instrument, 5, limit=2)
        return candles[-1], 5
