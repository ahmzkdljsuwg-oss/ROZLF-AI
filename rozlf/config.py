from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    mistral_api_key: str = ""
    mistral_model: str = "mistral-small-latest"
    mistral_vision_model: str = "mistral-small-latest"
    mistral_api_base: str = "https://api.mistral.ai/v1"
    ai_timeout_seconds: float = 45.0
    ai_retries: int = 1

    twelve_data_api_key: str = ""
    twelve_data_base: str = "https://api.twelvedata.com"

    eo_bridge_url: str = ""
    eo_bridge_key: str = ""

    database_url: str = "sqlite+aiosqlite:///./data/rozlf.db"

    log_level: str = "INFO"

    port: int = 8080
    scanner_interval_seconds: int = 90
    min_signal_score: int = 62
    max_signals_per_scan: int = 3
    signal_cooldown_minutes: int = 45
    default_expiry_seconds: int = 300

    delivery_mode: Literal["polling"] = "polling"

    @field_validator("telegram_chat_id")
    @classmethod
    def _strip(cls, value: str) -> str:
        return (value or "").strip()

    @property
    def allowed_chat_ids(self) -> tuple[int, ...]:
        ids: list[int] = []
        for chunk in self.telegram_chat_id.replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                ids.append(int(chunk))
            except ValueError:
                continue
        return tuple(ids)

    @property
    def has_twelve_data(self) -> bool:
        return bool(self.twelve_data_api_key.strip())

    @property
    def has_mistral(self) -> bool:
        return bool(self.mistral_api_key.strip())

    @property
    def has_eo_bridge(self) -> bool:
        return bool(self.eo_bridge_url.strip() and self.eo_bridge_key.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
