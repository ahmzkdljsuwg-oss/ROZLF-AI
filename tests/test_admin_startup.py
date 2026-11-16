"""Startup and packaging checks for the separate NEXUS-ADMIN service."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from aiogram import Router
from aiogram.exceptions import TelegramConflictError

from admin_bot import main as admin_main
from admin_bot.middleware import OwnerOnlyMiddleware
from config import settings

ROOT = Path(__file__).resolve().parent.parent


def _python(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH" and not k.endswith("_BOT_TOKEN")}
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_admin_package_and_every_module_import_without_pythonpath():
    result = _python(
        "-c",
        "import admin_bot, admin_bot.main, admin_bot.handlers, admin_bot.keyboards, admin_bot.middleware; "
        "print('ALL_ADMIN_IMPORTS_OK')",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ALL_ADMIN_IMPORTS_OK"


def test_start_admin_launcher_runs_from_an_unrelated_directory(tmp_path):
    result = _python(str(ROOT / "start_admin.py"), cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "ModuleNotFoundError" not in result.stderr
    assert "ADMIN_BOT_TOKEN is missing" in result.stderr


def test_direct_script_execution_reports_the_package_entrypoint():
    result = _python(str(ROOT / "admin_bot" / "main.py"))
    assert result.returncode != 0
    assert "python -m admin_bot.main" in result.stderr


def test_admin_refuses_to_poll_with_the_customer_token(monkeypatch, caplog):
    same = replace(
        settings,
        admin_bot_token="123:same",
        telegram_bot_token="123:same",
        owner_telegram_ids="9001",
        database_url="postgresql://user:pass@example.test:5432/db",
    )
    monkeypatch.setattr(admin_main, "settings", same)

    asyncio.run(admin_main.run())
    assert "identical to TELEGRAM_BOT_TOKEN" in caplog.text


def test_admin_refuses_an_invalid_admin_token(monkeypatch, caplog):
    bad = replace(
        settings,
        admin_bot_token="not-a-token",
        telegram_bot_token="456:customer",
        owner_telegram_ids="9001",
        database_url="postgresql://user:pass@example.test:5432/db",
    )
    monkeypatch.setattr(admin_main, "settings", bad)

    asyncio.run(admin_main.run())
    assert "does not look like a BotFather token" in caplog.text


def test_admin_refuses_an_ephemeral_sqlite_database(monkeypatch, caplog):
    ephemeral = replace(
        settings,
        admin_bot_token="123:admin",
        telegram_bot_token="456:customer",
        owner_telegram_ids="9001",
        database_url="sqlite+aiosqlite:///./should-not-be-used.db",
    )
    monkeypatch.setattr(admin_main, "settings", ephemeral)

    asyncio.run(admin_main.run())
    assert "must be PostgreSQL" in caplog.text


def test_owner_identity_is_fixed_regardless_of_environment(monkeypatch):
    from config import PRIMARY_OWNER_ID

    spoofed = replace(
        settings,
        admin_bot_token="123:admin",
        telegram_bot_token="456:customer",
        owner_telegram_ids="9001,7777",
        database_url="postgresql://user:pass@example.test:5432/db",
    )
    monkeypatch.setattr(admin_main, "settings", spoofed)

    assert spoofed.owner_ids == frozenset({PRIMARY_OWNER_ID})
    assert PRIMARY_OWNER_ID == 8368948762



@pytest.mark.asyncio
async def test_admin_reaches_polling_without_conflict(monkeypatch):
    polling = []

    class FakeSession:
        async def close(self):
            pass

    class FakeBot:
        def __init__(self, **kwargs):
            self.session = FakeSession()

        async def delete_webhook(self, **kwargs):
            return True

        async def set_my_commands(self, *args, **kwargs):
            return True

    class FakeRepo:
        def __init__(self, cfg):
            self.cfg = cfg

        async def init(self):
            pass

        async def close(self):
            pass

        async def pending_notifications(self):
            return []

    async def fake_start_polling(self, bot, **kwargs):
        polling.append(kwargs.get("allowed_updates"))

    configured = replace(
        settings,
        admin_bot_token="123:admin",
        telegram_bot_token="456:customer",
        owner_telegram_ids="9001",
        database_url="postgresql://user:pass@example.test:5432/db",
    )
    monkeypatch.setattr(admin_main, "settings", configured)
    monkeypatch.setattr(admin_main, "Bot", FakeBot)
    monkeypatch.setattr(admin_main, "Repository", FakeRepo)
    monkeypatch.setattr(admin_main.Dispatcher, "start_polling", fake_start_polling)
    monkeypatch.setattr(admin_main.handlers, "router", Router())

    await admin_main.run()
    assert polling and polling[0] is not None


@pytest.mark.asyncio
async def test_owner_middleware_allows_only_configured_owners():
    calls = []

    async def handler(event, data):
        calls.append(event.from_user.id)
        return "ok"

    gate = OwnerOnlyMiddleware(frozenset({9001}))

    class Event:
        def __init__(self, user_id):
            self.from_user = SimpleNamespace(id=user_id, username=f"u{user_id}", first_name="U")
            self.answers = []

        async def answer(self, text="", show_alert=False, **kwargs):
            self.answers.append(text)

    owner = Event(9001)
    intruder = Event(7777)
    assert await gate(handler, owner, {}) == "ok"
    assert await gate(handler, intruder, {}) is None
    assert calls == [9001]
    assert "مالك النظام" in intruder.answers[-1]


@pytest.mark.asyncio
async def test_admin_stops_after_three_telegram_conflicts(monkeypatch, caplog):
    attempts = []

    class FakeSession:
        async def close(self):
            pass

    class FakeBot:
        def __init__(self, **kwargs):
            self.session = FakeSession()

        async def delete_webhook(self, **kwargs):
            return True

        async def set_my_commands(self, *args, **kwargs):
            return True

    class FakeRepo:
        def __init__(self, cfg):
            self.cfg = cfg

        async def init(self):
            pass

        async def close(self):
            pass

        async def pending_notifications(self):
            return []

    async def conflict(self, bot, **kwargs):
        attempts.append(1)
        raise TelegramConflictError(method=None, message="conflict")

    async def fake_sleep(seconds):
        return None

    configured = replace(
        settings,
        admin_bot_token="123:admin",
        telegram_bot_token="456:customer",
        owner_telegram_ids="9001",
        database_url="postgresql://user:pass@example.test:5432/db",
    )
    monkeypatch.setattr(admin_main, "settings", configured)
    monkeypatch.setattr(admin_main, "Bot", FakeBot)
    monkeypatch.setattr(admin_main, "Repository", FakeRepo)
    monkeypatch.setattr(admin_main.Dispatcher, "start_polling", conflict)
    monkeypatch.setattr(admin_main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(admin_main.handlers, "router", Router())

    with pytest.raises(TelegramConflictError):
        await admin_main.run()
    assert len(attempts) == 3
    assert "refusing to run a duplicate" in caplog.text
