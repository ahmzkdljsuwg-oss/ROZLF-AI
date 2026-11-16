"""Startup and packaging checks for the separate NEXUS-ADMIN service."""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from admin_bot import main as admin_main
from config import settings

ROOT = Path(__file__).resolve().parent.parent


def _python(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.endswith("_BOT_TOKEN")}
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_admin_package_imports_with_relative_imports():
    result = _python("-c", "import admin_bot.main; print(admin_bot.main.__name__)")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "admin_bot.main"


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
    )
    monkeypatch.setattr(admin_main, "settings", same)

    asyncio.run(admin_main.run())
    assert "identical to TELEGRAM_BOT_TOKEN" in caplog.text


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
        database_url="sqlite+aiosqlite:///./test-admin-startup.db",
    )
    monkeypatch.setattr(admin_main, "settings", configured)
    monkeypatch.setattr(admin_main, "Bot", FakeBot)
    monkeypatch.setattr(admin_main, "Repository", FakeRepo)
    monkeypatch.setattr(admin_main.Dispatcher, "start_polling", fake_start_polling)

    await admin_main.run()
    assert polling and polling[0] is not None
