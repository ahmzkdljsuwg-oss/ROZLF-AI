import os
from unittest.mock import patch

from config import Settings, normalise_database_url


def test_defaults_are_sane(monkeypatch):
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings.from_env()
    assert settings.database_url.startswith("sqlite")
    assert settings.mistral_model == "mistral-small-latest"
    assert not hasattr(settings, "mistral_vision_model")
    assert 50 <= settings.min_confidence <= 95
    assert settings.scanner_interval_seconds >= 30
    assert settings.verification_interval_seconds >= 10


def test_env_overrides(monkeypatch):
    env = {
        "TELEGRAM_BOT_TOKEN": "123:abc",
        "TELEGRAM_CHAT_ID": "42",
        "MISTRAL_API_KEY": "k",
        "MIN_CONFIDENCE": "80",
        "SCANNER_ENABLED": "false",
        "SCAN_MARKETS": "OTC,SMARTY",
        "PORT": "8080",
    }
    with patch.dict(os.environ, env, clear=True):
        settings = Settings.from_env()
    assert settings.telegram_chat_id == 42
    assert settings.min_confidence == 80.0
    assert settings.scanner_enabled is False
    assert settings.scan_markets == "OTC,SMARTY"
    assert settings.port == 8080


def test_bounds_are_clamped():
    env = {"MIN_CONFIDENCE": "12", "SCANNER_INTERVAL_SECONDS": "1", "MAX_SCAN_SIGNALS": "0"}
    with patch.dict(os.environ, env, clear=True):
        settings = Settings.from_env()
    assert settings.min_confidence == 50.0
    assert settings.scanner_interval_seconds == 30
    assert settings.max_scan_signals == 1


def test_allowed_chat_ids():
    with patch.dict(os.environ, {}, clear=True):
        open_settings = Settings.from_env()
    assert open_settings.allowed_chat_ids == set()
    with patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "42"}, clear=True):
        restricted = Settings.from_env()
    assert restricted.allowed_chat_ids == {42}


def test_database_url_normalisation():
    assert normalise_database_url("postgres://u:p@h/db").startswith("postgresql+asyncpg://")
    assert normalise_database_url("postgresql://u:p@h/db").startswith("postgresql+asyncpg://")
    assert normalise_database_url("sqlite:///./x.db").startswith("sqlite+aiosqlite://")
    assert normalise_database_url("sqlite+aiosqlite:///x.db").startswith("sqlite+aiosqlite://")


def test_scan_interval_property():
    with patch.dict(os.environ, {"SCANNER_INTERVAL_SECONDS": "120"}, clear=True):
        settings = Settings.from_env()
    assert settings.scan_interval == 120


def test_web_role_from_railway_service_name():
    with patch.dict(os.environ, {"RAILWAY_SERVICE_NAME": "web"}, clear=True):
        settings = Settings.from_env()
    assert settings.role == "web"
    assert settings.web_only is True


def test_worker_role_is_not_web_only():
    with patch.dict(os.environ, {"RAILWAY_SERVICE_NAME": "worker"}, clear=True):
        settings = Settings.from_env()
    assert settings.role == "worker"
    assert settings.web_only is False


def test_explicit_role_wins():
    with patch.dict(os.environ, {"RAILWAY_SERVICE_NAME": "worker", "ROZLF_ROLE": "web"}, clear=True):
        settings = Settings.from_env()
    assert settings.role == "web"
