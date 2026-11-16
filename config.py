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


def _http_url(name: str) -> str | None:
    raw = _text(name)
    if not raw:
        return None
    url = raw.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


PRIMARY_OWNER_ID = 8368948762


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
    gemini_api_key: str | None
    gemini_model: str
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
    mt5_bridge_url: str | None = None
    mt5_bridge_key: str | None = None
    mistral_vision_model: str = "pixtral-12b-2409"
    admin_bot_token: str = ""
    owner_telegram_ids: str = ""
    subscriptions_enabled: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            telegram_bot_token=_text("TELEGRAM_BOT_TOKEN", "") or "",
            telegram_chat_id=_number("TELEGRAM_CHAT_ID", None, int),
            gemini_api_key=_text("GEMINI_API_KEY"),
            gemini_model=_text("GEMINI_MODEL", "gemini-2.5-flash") or "gemini-2.5-flash",
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
            scan_markets=_text("SCAN_MARKETS", "FOREX,GOLD,OTC,SMARTY,AI,FOOTBALL,LUXURY,CRICKET") or "FOREX,GOLD,OTC,SMARTY,AI,FOOTBALL,LUXURY,CRICKET",
            max_scan_signals=max(1, _number("MAX_SCAN_SIGNALS", 3, int)),
            mt5_bridge_url=_http_url("MT5_BRIDGE_URL"),
            mt5_bridge_key=_text("MT5_BRIDGE_KEY"),
            mistral_vision_model=_text("MISTRAL_VISION_MODEL", "pixtral-12b-2409") or "pixtral-12b-2409",
            admin_bot_token=_text("ADMIN_BOT_TOKEN", "") or "",
            owner_telegram_ids=_text("OWNER_TELEGRAM_IDS", str(PRIMARY_OWNER_ID)) or str(PRIMARY_OWNER_ID),
            subscriptions_enabled=_flag(
                "SUBSCRIPTIONS_ENABLED",
                bool(_text("ADMIN_BOT_TOKEN", "")),
            ),
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
    def database_is_persistent(self) -> bool:
        return normalise_database_url(self.database_url).startswith(
            ("postgresql+asyncpg://", "postgresql://", "postgres://")
        )

    @property
    def admin_bot_token_looks_valid(self) -> bool:
        token = self.admin_bot_token
        return ":" in token and token.split(":", 1)[0].isdigit()

    @property
    def bot_tokens_are_distinct(self) -> bool:
        return bool(self.admin_bot_token) and self.admin_bot_token != self.telegram_bot_token

    @property
    def allowed_chat_ids(self) -> frozenset[int]:
        if self.telegram_chat_id is None:
            return frozenset()
        return frozenset({self.telegram_chat_id})

    @property
    def owner_ids(self) -> frozenset[int]:
        # The platform owner is fixed; environment values can never grant
        # activation-code privileges to another Telegram account.
        return frozenset({PRIMARY_OWNER_ID})

    @property
    def admin_enabled(self) -> bool:
        return bool(self.admin_bot_token) and bool(self.owner_ids)

    @property
    def mistral_enabled(self) -> bool:
        return bool(self.mistral_api_key)

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def ai_enabled(self) -> bool:
        return self.gemini_enabled or self.mistral_enabled

    def startup_problems(self) -> list[str]:
        problems: list[str] = []
        if not self.telegram_bot_token:
            problems.append("TELEGRAM_BOT_TOKEN is missing")
        if not self.telegram_api_looks_valid:
            problems.append("TELEGRAM_BOT_TOKEN does not look like a BotFather token")
        if self.telegram_chat_id is None:
            problems.append("TELEGRAM_CHAT_ID is missing: /id onboarding is open to any user")
        if self.subscriptions_enabled and not self.database_is_persistent:
            problems.append("DATABASE_URL is not PostgreSQL: subscriptions will not survive a redeploy")
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
            "gemini": self.gemini_enabled,
            "gemini_model": self.gemini_model,
            "mistral": self.mistral_enabled,
            "mistral_model": self.mistral_model,
            "mistral_vision_model": self.mistral_vision_model,
            "twelve_data": bool(self.twelve_data_api_key),
            "eo_bridge": bool(self.eo_bridge_url and self.eo_bridge_key),
            "mt5_bridge": bool(self.mt5_bridge_url and self.mt5_bridge_key),
            "database": "postgresql" if "postgresql" in self.async_database_url else "sqlite",
            "scanner_enabled": self.scanner_enabled,
            "min_confidence": self.min_confidence,
            "subscriptions_enabled": self.subscriptions_enabled,
            "admin_bot": self.admin_enabled,
            "owner_ids": len(self.owner_ids),
        }


settings = Settings.from_env()
