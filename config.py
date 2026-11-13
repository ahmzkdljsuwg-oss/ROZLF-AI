"""Environment-backed configuration for ROZLF AI."""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

try:  # optional at import time so tests can run without a .env
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a hard dependency in production
    pass


def _text(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip().strip('"').strip("'").strip()
    return value or default


def _number(name: str, default, cast):
    raw = _text(name)
    if raw is None:
        return default
    try:
        return cast(raw)
    except ValueError:
        return default


def _flag(name: str, default: bool) -> bool:
    raw = _text(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


DEFAULT_MINI_APP_URL = "https://web-production-b044b.up.railway.app"
DEFAULT_BOT_API_URL = "https://rozlf-ai-production.up.railway.app"


def _mini_app_url() -> str | None:
    raw = _text("MINI_APP_URL") or _text("PUBLIC_BASE_URL")
    if not raw:
        domain = _text("RAILWAY_PUBLIC_DOMAIN")
        raw = f"https://{domain}" if domain else DEFAULT_MINI_APP_URL
    if not raw:
        return None
    url = raw.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if url.endswith("/mini-app"):
        url = url[: -len("/mini-app")]
    if not url.startswith("https://") and "localhost" not in url and "127.0.0.1" not in url:
        return None
    return url + "/mini-app/"


def _http_url(name: str) -> str | None:
    raw = _text(name)
    if not raw:
        return None
    url = raw.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _engine_api_url(role: str, mini_app_url: str | None) -> str | None:
    """Upstream bot URL for the web-only proxy.

    A self-reference (the web service pointing at its own host) is the known
    cause of recursive 30s timeouts, so it is ignored. The production bot
    domain is used only as the last resort for the web-only role.
    """
    url = _http_url("ENGINE_API_URL")
    own = _http_url("RAILWAY_PUBLIC_DOMAIN") or mini_app_url
    if url and own and urlsplit(url).hostname == urlsplit(own).hostname:
        url = None
    if not url and role.startswith("web"):
        return DEFAULT_BOT_API_URL
    return url


def normalise_database_url(url: str) -> str:
    """SQLAlchemy needs an explicit async driver."""
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("sqlite://") and "+aiosqlite" not in url:
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: int | None
    mistral_api_key: str | None
    mistral_model: str
    twelve_data_api_key: str | None
    database_url: str
    log_level: str
    eo_bridge_url: str | None
    eo_bridge_key: str | None
    port: int | None
    scanner_interval_seconds: int
    verification_interval_seconds: int
    min_confidence: float
    scanner_enabled: bool
    scan_markets: str
    max_scan_signals: int
    role: str
    mini_app_url: str | None = None
    engine_api_url: str | None = None
    mt5_bridge_url: str | None = None
    mt5_bridge_key: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        role = (_text("ROZLF_ROLE") or "bot").lower()
        mini_app_url = _mini_app_url()
        return cls(
            telegram_bot_token=_text("TELEGRAM_BOT_TOKEN", "") or "",
            telegram_chat_id=_number("TELEGRAM_CHAT_ID", None, int),
            mistral_api_key=_text("MISTRAL_API_KEY"),
            mistral_model=_text("MISTRAL_MODEL", "mistral-small-latest") or "mistral-small-latest",
            twelve_data_api_key=_text("TWELVE_DATA_API_KEY"),
            database_url=_text("DATABASE_URL", "sqlite+aiosqlite:///./rozlf.db") or "",
            log_level=(_text("LOG_LEVEL", "INFO") or "INFO").upper(),
            eo_bridge_url=_text("EO_BRIDGE_URL"),
            eo_bridge_key=_text("EO_BRIDGE_KEY"),
            port=_number("PORT", None, int),
            scanner_interval_seconds=max(30, _number("SCANNER_INTERVAL_SECONDS", 90, int)),
            verification_interval_seconds=max(10, _number("VERIFICATION_INTERVAL_SECONDS", 20, int)),
            min_confidence=min(95.0, max(50.0, _number("MIN_CONFIDENCE", 60.0, float))),
            scanner_enabled=_flag("SCANNER_ENABLED", True),
            scan_markets=_text("SCAN_MARKETS", "FOREX,SMARTY,AI,FOOTBALL,LUXURY,CRICKET") or "FOREX,SMARTY,AI,FOOTBALL,LUXURY,CRICKET",
            max_scan_signals=max(1, _number("MAX_SCAN_SIGNALS", 3, int)),
            role=role,
            mini_app_url=mini_app_url,
            engine_api_url=_engine_api_url(role, mini_app_url),
            mt5_bridge_url=_http_url("MT5_BRIDGE_URL"),
            mt5_bridge_key=_text("MT5_BRIDGE_KEY"),
        )

    @property
    def bridge_url(self) -> str | None:
        """Normalised bridge URL: a pasted host without scheme still works."""
        url = (self.eo_bridge_url or "").strip().rstrip("/")
        if not url:
            return None
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        if url.endswith("/docs"):
            url = url[: -len("/docs")]
        return url

    @property
    def scan_interval(self) -> int:
        return self.scanner_interval_seconds

    @property
    def async_database_url(self) -> str:
        return normalise_database_url(self.database_url)

    @property
    def allowed_chat_ids(self) -> frozenset[int]:
        if self.telegram_chat_id is None:
            return frozenset()
        return frozenset({self.telegram_chat_id})

    @property
    def mistral_enabled(self) -> bool:
        return bool(self.mistral_api_key)

    @property
    def web_only(self) -> bool:
        """Health-only mode for a dedicated service; the default bot role polls Telegram."""
        return self.role in {"web-only", "health"}

    def startup_problems(self) -> list[str]:
        problems: list[str] = []
        if not self.telegram_bot_token:
            problems.append("TELEGRAM_BOT_TOKEN is missing")
        if not self.telegram_api_looks_valid:
            problems.append("TELEGRAM_BOT_TOKEN does not look like a BotFather token")
        if self.telegram_chat_id is None:
            problems.append("TELEGRAM_CHAT_ID is missing: /id onboarding is open to any user")
        return problems

    @property
    def telegram_api_looks_valid(self) -> bool:
        token = self.telegram_bot_token
        return ":" in token and token.split(":", 1)[0].isdigit()

    def describe(self) -> dict[str, object]:
        """Safe status block: never includes secret values."""
        return {
            "telegram": bool(self.telegram_bot_token) and self.telegram_api_looks_valid,
            "telegram_chat_id_configured": self.telegram_chat_id is not None,
            "mistral": self.mistral_enabled,
            "mistral_model": self.mistral_model,
            "twelve_data": bool(self.twelve_data_api_key),
            "eo_bridge": bool(self.eo_bridge_url and self.eo_bridge_key),
            "mt5_bridge": bool(self.mt5_bridge_url and self.mt5_bridge_key),
            "database": "postgresql" if "postgresql" in self.async_database_url else "sqlite",
            "scanner_enabled": self.scanner_enabled,
            "min_confidence": self.min_confidence,
            "mini_app": bool(self.mini_app_url),
            "engine_api": bool(self.engine_api_url),
        }


settings = Settings.from_env()
