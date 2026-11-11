"""Configuration for the standalone ExpertOption bridge.

The bridge needs a real ExpertOption session token (EO_TOKEN). It never logs in
with an email/password, never places trades and never synthesises prices.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_REGION_URL = "wss://fr24g1eu.expertoption.com/"

REGIONS = {
    "EUROPE": "wss://fr24g1eu.expertoption.com/",
    "INDIA": "wss://fr24g1in.expertoption.com/",
    "HONG_KONG": "wss://fr24g1hk.expertoption.com/",
    "SINGAPORE": "wss://fr24g1sg.expertoption.com/",
    "UNITED_STATES": "wss://fr24g1us.expertoption.com/",
}


def _text(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or None


def _number(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class BridgeSettings:
    api_key: str | None
    eo_token: str | None
    eo_region: str
    eo_demo: bool
    host: str
    port: int
    candle_history_seconds: int
    quote_cache_seconds: float
    candle_cache_seconds: float
    log_level: str

    @property
    def ws_url(self) -> str:
        region = (self.eo_region or "EUROPE").strip()
        if region.startswith(("ws://", "wss://")):
            return region
        region = region.upper()
        return REGIONS.get(region, DEFAULT_REGION_URL)

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.eo_token)

    def describe(self) -> dict[str, object]:
        return {
            "api_key_set": bool(self.api_key),
            "eo_token_set": bool(self.eo_token),
            "region": self.eo_region,
            "demo": self.eo_demo,
        }

    @classmethod
    def from_env(cls) -> "BridgeSettings":
        return cls(
            api_key=_text("EO_BRIDGE_KEY"),
            eo_token=_text("EO_TOKEN"),
            eo_region=_text("EO_REGION", "EUROPE") or "EUROPE",
            eo_demo=_flag("EO_DEMO", True),
            host=_text("HOST", "0.0.0.0") or "0.0.0.0",
            port=int(_number("PORT", 8080)),
            candle_history_seconds=int(_number("EO_HISTORY_SECONDS", 7200)),
            quote_cache_seconds=_number("EO_QUOTE_CACHE_SECONDS", 1.0),
            candle_cache_seconds=_number("EO_CANDLE_CACHE_SECONDS", 3.0),
            log_level=(_text("LOG_LEVEL", "INFO") or "INFO").upper(),
        )
