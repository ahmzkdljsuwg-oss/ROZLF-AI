"""Thin, read-only wrapper around the MetaTrader5 Python API."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

try:
    import MetaTrader5 as mt5
except ImportError:  # the production bridge is Windows-only
    mt5 = None  # type: ignore[assignment]

from .settings import BridgeSettings

CURRENCIES = {
    "AUD", "CAD", "CHF", "CNH", "CZK", "DKK", "EUR", "GBP", "HKD", "HUF",
    "JPY", "MXN", "NOK", "NZD", "PLN", "RUB", "SEK", "SGD", "TRY", "USD", "ZAR",
}
TIMEFRAMES = {
    "1min": mt5.TIMEFRAME_M1 if mt5 else None,
    "5min": mt5.TIMEFRAME_M5 if mt5 else None,
    "15min": mt5.TIMEFRAME_M15 if mt5 else None,
    "30min": mt5.TIMEFRAME_M30 if mt5 else None,
    "1h": mt5.TIMEFRAME_H1 if mt5 else None,
}


class MT5Error(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_symbol(name: str) -> str | None:
    raw = (name or "").strip()
    base = re.split(r"[._-]", raw, maxsplit=1)[0].upper()
    if len(base) == 6:
        candidate = base
    else:
        match = re.fullmatch(r"([A-Za-z]{6})([a-z]{1,2})", raw)
        candidate = match.group(1).upper() if match else ""
    if len(candidate) == 6 and candidate[:3] in CURRENCIES and candidate[3:] in CURRENCIES:
        return candidate
    return None


def _iso(epoch: int | float | None) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat().replace("+00:00", "Z")


class MT5Client:
    def __init__(self, settings: BridgeSettings) -> None:
        self.settings = settings
        self.last_error: str | None = None

    def _ensure(self) -> None:
        if mt5 is None:
            raise MT5Error("MT5_PACKAGE_MISSING", "MetaTrader5 package is not installed (Windows only)")
        if mt5.terminal_info() is not None and mt5.account_info() is not None:
            return
        kwargs: dict[str, Any] = {}
        if self.settings.terminal_path:
            kwargs["path"] = self.settings.terminal_path
        if self.settings.login:
            kwargs["login"] = self.settings.login
        if self.settings.password:
            kwargs["password"] = self.settings.password
        if self.settings.server:
            kwargs["server"] = self.settings.server
        kwargs["timeout"] = 30000
        if not mt5.initialize(**kwargs):
            self.last_error = str(mt5.last_error())
            raise MT5Error("MT5_OFFLINE", f"MT5 initialize failed: {self.last_error}")
        if not mt5.terminal_info().connected:
            self.last_error = "terminal not connected to broker"
            raise MT5Error("MT5_OFFLINE", "MT5 terminal is open but not connected to the broker")

    def status(self) -> dict[str, Any]:
        try:
            self._ensure()
        except MT5Error as exc:
            return {"terminal_connected": False, "error": exc.code, "message": exc.message}
        terminal = mt5.terminal_info()
        account = mt5.account_info()
        return {
            "terminal_connected": bool(terminal and terminal.connected),
            "company": getattr(terminal, "company", None),
            "server": getattr(account, "server", None),
            "account": getattr(account, "login", None),
            "trade_allowed": bool(getattr(account, "trade_allowed", False)),
            "build": getattr(terminal, "build", None),
        }

    def resolve(self, requested: str) -> str:
        self._ensure()
        wanted = (requested or "").upper().replace("/", "").strip()
        exact = mt5.symbol_info(wanted)
        if exact is not None:
            return exact.name
        candidates = []
        for info in mt5.symbols_get() or []:
            if canonical_symbol(info.name) == wanted:
                candidates.append(info)
        if not candidates:
            raise MT5Error("MT5_SYMBOL_NOT_FOUND", f"{wanted} is not offered by this MT5 broker")
        visible = [info for info in candidates if info.visible]
        return (visible or candidates)[0].name

    def symbols(self) -> list[dict[str, Any]]:
        self._ensure()
        rows = []
        for info in mt5.symbols_get() or []:
            canonical = canonical_symbol(info.name)
            if canonical is None:
                continue
            rows.append({
                "canonical": canonical,
                "broker": info.name,
                "description": info.description,
                "digits": int(info.digits),
                "point": float(info.point),
                "visible": bool(info.visible),
                "forex": True,
            })
        return rows

    def _broker(self, requested: str) -> str:
        broker = self.resolve(requested)
        info = mt5.symbol_info(broker)
        if info is None:
            raise MT5Error("MT5_SYMBOL_NOT_FOUND", f"{requested} disappeared from Market Watch")
        if not info.visible and not mt5.symbol_select(broker, True):
            raise MT5Error("MT5_SYMBOL_NOT_SELECTED", f"Cannot select {broker} in Market Watch")
        return broker

    def candles(self, requested: str, timeframe: str, limit: int) -> tuple[str, list[dict[str, Any]]]:
        self._ensure()
        tf = TIMEFRAMES.get(timeframe)
        if tf is None:
            raise MT5Error("MT5_BAD_TIMEFRAME", f"Unsupported timeframe {timeframe}")
        broker = self._broker(requested)
        rates = mt5.copy_rates_from_pos(broker, tf, 0, int(limit))
        if rates is None or len(rates) == 0:
            raise MT5Error("MT5_NO_DATA", f"No candles returned for {broker}")
        rows = []
        for rate in rates:
            rows.append({
                "time": _iso(int(rate["time"])),
                "open": float(rate["open"]),
                "high": float(rate["high"]),
                "low": float(rate["low"]),
                "close": float(rate["close"]),
                "tick_volume": int(rate["tick_volume"]),
                "spread": int(rate["spread"]),
                "real_volume": int(rate["real_volume"]),
            })
        return broker, rows

    def quote(self, requested: str) -> tuple[str, dict[str, Any]]:
        self._ensure()
        broker = self._broker(requested)
        tick = mt5.symbol_info_tick(broker)
        if tick is None or tick.bid <= 0 or tick.ask <= 0:
            raise MT5Error("MT5_NO_TICK", f"No live tick for {broker}")
        return broker, {
            "bid": float(tick.bid), "ask": float(tick.ask),
            "time": _iso(int(tick.time)), "broker": broker,
        }
