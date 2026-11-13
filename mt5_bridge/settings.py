"""Bridge settings. Secrets come from the environment, never from files in git."""
from __future__ import annotations

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover
    pass


def _text(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


@dataclass(frozen=True)
class BridgeSettings:
    api_key: str
    host: str
    port: int
    terminal_path: str | None
    login: int | None
    password: str | None
    server: str | None
    max_age_seconds: int

    @classmethod
    def from_env(cls) -> "BridgeSettings":
        login_raw = _text("MT5_LOGIN")
        return cls(
            api_key=_text("MT5_BRIDGE_KEY", "") or "",
            host=_text("MT5_BRIDGE_HOST", "0.0.0.0") or "0.0.0.0",
            port=int(_text("MT5_BRIDGE_PORT", "8090") or "8090"),
            terminal_path=_text("MT5_TERMINAL_PATH"),
            login=int(login_raw) if login_raw and login_raw.isdigit() else None,
            password=_text("MT5_PASSWORD"),
            server=_text("MT5_SERVER"),
            max_age_seconds=max(60, int(_text("MT5_MAX_AGE_SECONDS", "180") or "180")),
        )
