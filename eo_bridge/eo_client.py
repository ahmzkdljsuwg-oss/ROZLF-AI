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
import zlib
from dataclasses import dataclass
from typing import Any

import aiohttp

from .catalog import Instrument
from .settings import BridgeSettings

logger = logging.getLogger("eo_bridge.client")

# ExpertOption rejects subscriptions once too many assets/timeframes are held
# on one session. Keep a small LRU window and unsubscribe before growing it.
MAX_SUBSCRIPTIONS = 8
CANDLE_CACHE_SECONDS = 1.5

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
        self._subscription_order: list[tuple[int, int]] = []
        self._candle_cache: dict[tuple[int, int], tuple[float, list[Candle]]] = {}
        self._fetch_locks: dict[tuple[int, int], asyncio.Lock] = {}
        self._fetch_semaphore = asyncio.Semaphore(3)
        self._market_stats: dict[str, dict[str, Any]] = {}
        self._assets: list[Instrument] = []
        self._assets_loaded_at = 0.0
        self._assets_debug: dict[str, Any] = {}
        self._seen_actions: dict[str, int] = {}
        self._raw_by_id: dict[int, dict[str, Any]] = {}
        self._timeframes_payload: Any = None
        self._candle_debug: list[Any] = []
        self._msg_shapes: list[Any] = []
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
            "assets_debug": dict(self._assets_debug),
            "seen_actions": dict(self._seen_actions),
            "msg_shapes": list(self._msg_shapes),
            "timeframes_payload": self._timeframes_payload,
            "candle_debug": list(self._candle_debug),
            "last_message_age_seconds": (
                round(time.time() - self._last_message_at, 1) if self._last_message_at else None
            ),
            "last_error": self._last_error,
            "subscriptions": [list(key) for key in self._subscription_order],
            "market_status": {
                market: dict(values) for market, values in self._market_stats.items()
            },
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
        auth_failures = 0
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
            if self._last_error and self._last_error.startswith(("TOKEN_INVALID", "AUTH_FAILED")):
                auth_failures += 1
            else:
                auth_failures = 0
            if auth_failures >= 3:
                delay = 600.0
                logger.error(
                    "ExpertOption session is still being refused (%s); waiting %.0fs "
                    "before the next attempt. Refresh EO_TOKEN.",
                    self._last_error,
                    delay,
                )
            else:
                delay = min(30.0, backoff) + random.uniform(0, 1.0)
                logger.info("Reconnecting to ExpertOption in %.1fs", delay)
                backoff = min(30.0, backoff * 2)
            await asyncio.sleep(delay)

    async def _connect_once(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        logger.info("Connecting to %s", self.settings.ws_url)
        self._ws = await self._session.ws_connect(
            self.settings.ws_url,
            headers=HEADERS,
            heartbeat=25,
            compress=0,
            max_msg_size=0,
        )
        self._last_error = None
        self._receive_task = asyncio.create_task(self._receive_loop(), name="eo-recv")
        self._ping_task = asyncio.create_task(self._ping_loop(), name="eo-ping")
        await self._handshake()

    async def _wait_closed(self) -> None:
        task = self._receive_task
        if task is None or task is asyncio.current_task():
            return
        # A locally closed socket cancels the receive task; that must end this
        # connection attempt, not kill the supervisor that would reconnect.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

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
        self._subscriptions.clear()
        self._subscription_order.clear()
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
            if message.type is aiohttp.WSMsgType.TEXT:
                raw = message.data
            elif message.type is aiohttp.WSMsgType.BINARY:
                raw = self._decode_binary(message.data)
                if raw is None:
                    continue
            else:
                continue
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if isinstance(data, list):
                if len(self._msg_shapes) < 3:
                    self._msg_shapes.append(self._shape(data))
                for item in data:
                    if isinstance(item, dict):
                        self._dispatch(item)
            elif isinstance(data, dict):
                if len(self._msg_shapes) < 3:
                    self._msg_shapes.append(self._shape(data))
                self._dispatch(data)
        if self._ws is not None and self._ws.exception() is not None:
            raise BridgeError("SOCKET", str(self._ws.exception()))

    @staticmethod
    def _decode_binary(payload: bytes) -> str | None:
        # Some ExpertOption gateways answer in binary frames (plain UTF-8 JSON
        # or zlib-compressed JSON) instead of text frames.
        with contextlib.suppress(UnicodeDecodeError):
            return payload.decode("utf-8")
        with contextlib.suppress(Exception):
            return zlib.decompress(payload).decode("utf-8")
        return None

    @staticmethod
    def _shape(value: Any, depth: int = 0) -> Any:
        if isinstance(value, dict):
            return {
                key: ("<redacted>" if any(secret in key.lower() for secret in ("token", "pass", "email"))
                      else ExpertOptionClient._shape(item, depth + 1) if depth < 2 else "...")
                for key, item in list(value.items())[:14]
            }
        if isinstance(value, list):
            return [ExpertOptionClient._shape(value[0], depth + 1)] if value else []
        if isinstance(value, str) and len(value) > 40:
            return f"str[{len(value)}]"
        return value if isinstance(value, (int, float, bool)) or value is None else type(value).__name__

    @staticmethod
    def _classify_error(detail: Any) -> str:
        """Map ExpertOption error text to a code the bot can show honestly."""
        text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
        lowered = text.lower()
        if "token" in lowered and any(
            word in lowered for word in ("invalid", "expired", "wrong", "unknown", "unauthoriz")
        ):
            return "TOKEN_INVALID"
        if any(word in lowered for word in ("unauthoriz", "not authorized", "auth")):
            return "AUTH_FAILED"
        return "EO_ERROR"

    def _dispatch(self, data: dict[str, Any]) -> None:
        action = data.get("action")
        if isinstance(action, str):
            self._seen_actions[action] = self._seen_actions.get(action, 0) + 1
        ns = str(data.get("ns")) if data.get("ns") else None
        if action == "error":
            detail = data.get("message")
            code = self._classify_error(detail)
            if ns and ns in self._pending and not self._pending[ns].done():
                self._pending[ns].set_exception(BridgeError(code, str(detail)))
            if code in {"TOKEN_INVALID", "AUTH_FAILED"}:
                self._last_error = f"{code}: {detail}"
            elif not ns or ns not in self._pending:
                self._last_error = f"EO: {detail}"
            return
        if action == "token":
            new_token = (data.get("message") or {}).get("token")
            if isinstance(new_token, str) and new_token:
                self._token = new_token
            return
        if action == "getCandlesTimeframes":
            self._timeframes_payload = data.get("message")
        if action == "multipleAction":
            for sub in (data.get("message") or {}).get("actions") or []:
                self._dispatch(dict(sub))
            return
        if action in {"candles", "assetHistoryCandles"}:
            message = data.get("message") or {}
            if str(message.get("assetId") or message.get("assetid") or message.get("asset")) == "240" \
                    and len(self._candle_debug) < 3:
                self._candle_debug.append({"action": action, "keys": sorted(message),
                                           "sample": json.dumps(message)[:500]})
            self._ingest_candles(message)
        if action == "assets":
            raw_assets = (data.get("message") or {}).get("assets") or []
            if raw_assets:
                from .catalog import build_instruments

                self._merge_assets(build_instruments(raw_assets), raw_assets)
                self._assets_loaded_at = time.time()
                self._assets_debug = {"raw_count": len(raw_assets), "parsed": len(self._assets),
                                      "sample": [{"id": a.get("id"), "symbol": a.get("symbol"),
                                                  "name": a.get("name")} for a in raw_assets[:3]]}
                self._connected.set()
        if ns and ns in self._pending and not self._pending[ns].done():
            self._pending[ns].set_result(data)

    def _ingest_candles(self, message: dict[str, Any]) -> None:
        try:
            asset_id = int(
                message.get("assetId")
                or message.get("assetid")
                or message.get("asset")
                or 0
            )
        except (TypeError, ValueError):
            return
        if not asset_id:
            return
        try:
            message_tf = int(message.get("tf") or message.get("timeframe") or 0)
        except (TypeError, ValueError):
            message_tf = 0
        blocks = message.get("candles")
        if isinstance(blocks, dict):
            blocks = [blocks]
        if not blocks:
            periods = message.get("periods")
            blocks = [{"tf": message_tf, "periods": periods}] if periods else []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            try:
                tf = int(block.get("tf") or message_tf or 0)
            except (TypeError, ValueError):
                tf = message_tf
            if not tf:
                continue
            bucket = self._candles.setdefault((asset_id, tf), {})
            periods = block.get("periods")
            if periods:
                for period in periods:
                    try:
                        start = self._normalise_ts(period[0])
                        rows = period[1] or []
                    except (IndexError, TypeError, ValueError):
                        continue
                    if start is None:
                        continue
                    self._store_rows(bucket, [(start + index * tf, row) for index, row in enumerate(rows)])
                continue
            if "t" in block and isinstance(block.get("v"), list):
                self._store_rows(bucket, [(int(block["t"]), block["v"])])

    @staticmethod
    def _normalise_ts(value: Any) -> int | None:
        """ExpertOption has shipped period starts in both seconds and ms."""
        try:
            timestamp = int(float(value))
        except (TypeError, ValueError):
            return None
        if timestamp <= 0:
            return None
        if timestamp > 10_000_000_000:
            timestamp //= 1000
        return timestamp

    @staticmethod
    def _row_to_candle(timestamp: int, row: Any) -> Candle | None:
        if not isinstance(row, (list, tuple)) or len(row) < 4:
            return None
        try:
            values = [float(value) for value in row[:4]]
        except (TypeError, ValueError):
            return None
        if any(value <= 0 or value != value for value in values):
            return None
        # Different ExpertOption builds order the four values differently, so
        # accept the first ordering that is a valid OHLC bar.
        candidates = (
            values,
            [values[0], values[3], values[2], values[1]],  # open, close, low, high
            [values[0], values[3], values[1], values[2]],  # open, close, high, low
        )
        for open_, high, low, close in candidates:
            if high >= max(open_, close) and low <= min(open_, close) and high > low:
                volume = 0.0
                if len(row) > 4:
                    try:
                        volume = float(row[4] or 0)
                    except (TypeError, ValueError):
                        volume = 0.0
                return Candle(
                    time=timestamp,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                )
        logger.debug("dropping inconsistent ExpertOption candle row %r", row)
        return None

    @classmethod
    def _store_rows(cls, bucket: dict[int, Candle], pairs: list[tuple[Any, Any]]) -> None:
        for raw_ts, row in pairs:
            timestamp = cls._normalise_ts(raw_ts)
            if timestamp is None:
                continue
            candle = cls._row_to_candle(timestamp, row)
            if candle is not None:
                bucket[timestamp] = candle

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
        await self._wait_for_assets(15.0)
        if not self._assets:
            # Some gateways ignore the batch and answer a plain assets request.
            with contextlib.suppress(BridgeError):
                await self.refresh_assets()
        if not self._assets:
            await self._wait_for_assets(8.0)
        if not self._assets:
            raise self._auth_error()
        self._connected.set()
        self._last_error = None
        logger.info("ExpertOption authenticated: %d instruments", len(self._assets))

    def raw_asset(self, asset_id: int) -> dict[str, Any]:
        raw = self._raw_by_id.get(asset_id) or {}
        keep = (
            "id", "symbol", "name", "is_active", "is_visible", "is_otc", "type", "asset_type",
            "mode", "modeId", "group_id", "asset_group_id", "expiration_step", "expiration_count",
            "expiration_max_seconds", "purchase_time", "start_time", "shutdown_time",
            "custom_time_enabled", "precision", "profit",
        )
        return {key: raw[key] for key in keep if key in raw}

    def _merge_assets(self, instruments: list[Instrument], raw_assets: list[dict[str, Any]] | None = None) -> None:
        for raw in raw_assets or []:
            try:
                self._raw_by_id[int(raw.get("id"))] = raw
            except (TypeError, ValueError):
                continue
        # The gateway may push partial asset lists (e.g. one active symbol).
        # Never let a smaller update wipe the full catalog discovered earlier.
        merged = {item.id: item for item in self._assets}
        for item in instruments:
            merged[item.id] = item
        self._assets = [merged[key] for key in sorted(merged)]

    async def _wait_for_assets(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._assets:
            if self._last_error and self._last_error.startswith(("TOKEN_INVALID", "AUTH_FAILED")):
                return
            await asyncio.sleep(0.1)

    def _auth_error(self) -> BridgeError:
        error = self._last_error or ""
        if error.startswith("TOKEN_INVALID"):
            return BridgeError(
                "TOKEN_INVALID",
                "ExpertOption rejected the session token (expired or signed out): " + error.split(":", 1)[-1].strip(),
            )
        if error.startswith("AUTH_FAILED"):
            return BridgeError("AUTH_FAILED", error.split(":", 1)[-1].strip() or "ExpertOption refused the session")
        if not self._last_message_at:
            return BridgeError(
                "NO_RESPONSE",
                "ExpertOption closed the socket before answering the handshake; "
                "check EO_REGION and EO_TOKEN",
            )
        return BridgeError(
            "AUTH_FAILED",
            error or "ExpertOption returned no assets; token is invalid or expired",
        )

    async def refresh_assets(self) -> list[Instrument]:
        response = await self.request("assets", None, timeout=15.0)
        raw_assets = (response.get("message") or {}).get("assets") or []
        if raw_assets:
            from .catalog import build_instruments

            self._merge_assets(build_instruments(raw_assets), raw_assets)
            self._assets_loaded_at = time.time()
            self._assets_debug = {"raw_count": len(raw_assets), "parsed": len(self._assets),
                                  "sample": [{"id": a.get("id"), "symbol": a.get("symbol"),
                                              "name": a.get("name")} for a in raw_assets[:3]]}
        return self.assets

    async def ensure_assets(self, max_age_seconds: float = 300.0) -> list[Instrument]:
        if self._runner is None or self._runner.done():
            await self.start()
        if not self.settings.eo_token:
            raise BridgeError("EO_TOKEN_MISSING", "Bridge has no ExpertOption session token")
        if not self.connected:
            deadline = time.monotonic() + 15.0
            while not self.connected and time.monotonic() < deadline:
                if self._last_error and self._last_error.startswith(("TOKEN_INVALID", "AUTH_FAILED")):
                    raise self._auth_error()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._connected.wait(), timeout=0.2)
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
    def _record_market(self, instrument: Instrument, **values: Any) -> None:
        entry = self._market_stats.setdefault(instrument.market, {})
        entry.update(values)
        entry["updated_at"] = round(time.time(), 1)
        entry["symbol"] = instrument.symbol

    async def _unsubscribe(self, key: tuple[int, int]) -> None:
        if key in self._subscriptions:
            self._subscriptions.discard(key)
            if key in self._subscription_order:
                self._subscription_order.remove(key)
        with contextlib.suppress(BridgeError, Exception):
            await self.request(
                "unsubscribeCandles",
                {"assets": [{"id": key[0], "timeframes": [key[1]]}]},
                timeout=4.0,
            )

    async def _subscribe(self, key: tuple[int, int]) -> None:
        if key in self._subscriptions:
            return
        while len(self._subscription_order) >= MAX_SUBSCRIPTIONS:
            await self._unsubscribe(self._subscription_order[0])
        try:
            await self.request(
                "subscribeCandles",
                {"assets": [{"id": key[0], "timeframes": [key[1]]}]},
                timeout=8.0,
            )
        except BridgeError as exc:
            if "TOO_MANY_ASSETS" not in exc.code.upper() and "TOO_MANY" not in str(exc.message).upper():
                raise
            for old in list(self._subscription_order):
                if old != key:
                    await self._unsubscribe(old)
            await self.request(
                "subscribeCandles",
                {"assets": [{"id": key[0], "timeframes": [key[1]]}]},
                timeout=8.0,
            )
        self._subscriptions.add(key)
        self._subscription_order.append(key)

    async def get_candles(self, instrument: Instrument, tf_seconds: int, limit: int = 300) -> list[Candle]:
        if not self.connected:
            raise BridgeError("DISCONNECTED", "ExpertOption socket is not connected")
        key = (instrument.id, tf_seconds)
        cached = self._candle_cache.get(key)
        if cached is not None and time.monotonic() - cached[0] < CANDLE_CACHE_SECONDS:
            return cached[1][-limit:]
        lock = self._fetch_locks.setdefault(key, asyncio.Lock())
        async with self._fetch_semaphore, lock:
            cached = self._candle_cache.get(key)
            if cached is not None and time.monotonic() - cached[0] < CANDLE_CACHE_SECONDS:
                return cached[1][-limit:]
            bucket = self._candles.setdefault(key, {})
            last_error: BridgeError | None = None
            async with self._request_lock:
                await self._subscribe(key)
                needed = max(limit, 60)
                span = max(self.settings.candle_history_seconds, tf_seconds * needed)
                end = int(time.time())
                latest = max(bucket) if bucket else 0
                # A bucket that stopped advancing must be backfilled from
                # history instead of being served as if it were live.
                attempts = 3 if len(bucket) < needed or end - latest > max(tf_seconds * 3, 30) else 0
                for attempt in range(attempts):
                    start = end - span
                    try:
                        await self.request(
                            "assetHistoryCandles",
                            {
                                "assetid": instrument.id,
                                "periods": [[start, end]],
                                "timeframes": [tf_seconds],
                            },
                            timeout=8.0,
                        )
                    except BridgeError as exc:
                        last_error = exc
                        logger.warning(
                            "history fetch failed for %s tf=%s attempt=%s: %s",
                            instrument.symbol, tf_seconds, attempt + 1, exc.code,
                        )
                    await asyncio.sleep(0.4 * (2 ** attempt))
                    if bucket:
                        end = min(bucket) - 1
                    span = max(span, tf_seconds * needed)
            now = time.time()
            horizon = now + max(tf_seconds, 60)
            ordered = [bucket[ts] for ts in sorted(bucket)]
            if any(candle.time > horizon for candle in ordered):
                logger.warning(
                    "dropping ExpertOption candles dated in the future for %s tf=%s",
                    instrument.symbol,
                    tf_seconds,
                )
            candles = [candle for candle in ordered if candle.time <= horizon][-limit:]
            if not candles:
                self._record_market(instrument, ok=False, error=(last_error.code if last_error else "NO_CANDLES"),
                                    timeframe=tf_seconds)
                if last_error is not None:
                    raise last_error
                raise BridgeError(
                    "NO_CANDLES",
                    f"ExpertOption returned no candles for {instrument.symbol} tf={tf_seconds}",
                )
            newest = time.time() - candles[-1].time
            self._record_market(instrument, ok=True, error=None, timeframe=tf_seconds,
                                candles=len(candles), stale_seconds=round(max(0.0, newest), 1))
            self._candle_cache[key] = (time.monotonic(), list(candles))
            return candles

    async def get_quote(self, instrument: Instrument) -> tuple[Candle, int]:
        candles = await self.get_candles(instrument, 5, limit=2)
        return candles[-1], 5
