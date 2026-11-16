"""Subscription lifecycle: atomic activation, expiry enforcement, admin operations."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from admin_bot import handlers as admin_handlers
from admin_bot.main import notification_loop
from bot import formatting as fmt
from bot.handlers import menus as handlers
from bot.middleware.subscription import SubscriptionMiddleware
from database.repository import Repository


class Message:
    def __init__(self, text="", user_id=42, username="client"):
        self.text = text
        self.from_user = SimpleNamespace(id=user_id, username=username, first_name="Client")
        self.chat = SimpleNamespace(id=user_id)
        self.sent = []

    async def answer(self, text, reply_markup=None, **kwargs):
        self.sent.append((text, reply_markup))

    async def edit_text(self, text, reply_markup=None, **kwargs):
        self.sent.append((text, reply_markup))


class Callback:
    def __init__(self, data, user_id=42):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = Message(user_id=user_id)
        self.answers = []

    async def answer(self, text="", show_alert=False, **kwargs):
        self.answers.append(text)


class RepoContext:
    def __init__(self, repo):
        self.repo = repo


@pytest.mark.asyncio
async def test_code_creation_is_unique_and_supports_every_duration(repo):
    codes = set()
    for days in (1, 7, 30, 90, 365):
        record = await repo.create_activation_code(days, created_by=9001)
        assert record.code.startswith("NX-")
        assert len(record.code) == 22
        assert record.duration_days == days
        assert record.status == "AVAILABLE"
        codes.add(record.code)
    assert len(codes) == 5


@pytest.mark.asyncio
async def test_code_activates_once_and_queues_owner_notification(repo):
    code = await repo.create_activation_code(30, created_by=9001)
    first = await repo.activate_code(code.code, 5001, username="first")
    assert first.status == "ACTIVATED"
    assert first.subscription is not None
    assert abs((first.subscription.expires_at - first.subscription.activated_at) - timedelta(days=30)) < timedelta(seconds=1)

    second = await repo.activate_code(code.code, 5002, username="second")
    assert second.status == "USED"
    assert await repo.is_subscribed(5001) is True
    assert await repo.is_subscribed(5002) is False

    pending = await repo.pending_notifications()
    assert len(pending) == 1
    payload = pending[0].payload
    assert payload["code"].startswith("NX-****-****-") and payload["code"].endswith(code.code[-4:])
    assert payload["telegram_id"] == 5001
    assert payload["username"] == "first"
    assert payload["duration_days"] == 30
    assert payload["status"] == "ACTIVE"
    assert payload["activated_at"] and payload["expires_at"]


@pytest.mark.asyncio
async def test_concurrent_activation_can_only_succeed_once(repo):
    code = await repo.create_activation_code(7, created_by=9001)
    results = await asyncio.gather(
        repo.activate_code(code.code, 6001),
        repo.activate_code(code.code, 6002),
    )
    statuses = sorted(result.status for result in results)
    assert statuses == ["ACTIVATED", "USED"]


@pytest.mark.asyncio
async def test_subscription_expires_automatically_and_persists_across_restart(settings, tmp_path):
    first = Repository(settings)
    await first.init()
    code = await first.create_activation_code(1, created_by=9001)
    activated_at = datetime.now(timezone.utc) - timedelta(days=2)
    result = await first.activate_code(code.code, 7001, username="expired", now=activated_at)
    assert result.status == "ACTIVATED"
    record = await first.subscription_for(7001)
    assert record is not None and record.active is False
    assert record.status == "EXPIRED"
    assert await first.is_subscribed(7001) is False
    await first.close()

    second = Repository(settings)
    await second.init()
    record = await second.subscription_for(7001)
    assert record is not None and record.status == "EXPIRED"
    assert await second.is_subscribed(7001) is False
    await second.close()


@pytest.mark.asyncio
async def test_revoked_subscription_loses_access(repo):
    code = await repo.create_activation_code(90, created_by=9001)
    await repo.activate_code(code.code, 8001)
    assert await repo.is_subscribed(8001) is True
    assert await repo.revoke_subscription(8001) is True
    record = await repo.subscription_for(8001)
    assert record is not None and record.active is False
    assert record.status == "REVOKED"


@pytest.mark.asyncio
async def test_client_activate_and_status_handlers(repo, monkeypatch):
    from bot import context

    code = await repo.create_activation_code(7, created_by=9001)
    monkeypatch.setattr(context, "_context", SimpleNamespace(repo=repo), raising=False)

    missing = Message("/activate", user_id=8101)
    await handlers.cmd_activate(missing)
    assert "NX-" in missing.sent[-1][0]

    activated = Message(f"/activate {code.code.lower()}", user_id=8101, username="buyer")
    await handlers.cmd_activate(activated)
    assert "تم تفعيل اشتراك NEXUS AI" in activated.sent[-1][0]
    assert "7 أيام" in activated.sent[-1][0]
    assert await repo.is_subscribed(8101) is True

    repeat = Message(f"/activate {code.code}", user_id=8101)
    await handlers.cmd_activate(repeat)
    assert "تعذر التفعيل" in repeat.sent[-1][0]
    assert "USED" in repeat.sent[-1][0]

    status = Message("/status", user_id=8101)
    await handlers.cmd_subscription_status(status)
    assert "ACTIVE" in status.sent[-1][0]

    nobody = Message("/status", user_id=8102)
    await handlers.cmd_subscription_status(nobody)
    assert "NO SUBSCRIPTION" in nobody.sent[-1][0]


@pytest.mark.asyncio
async def test_subscription_middleware_blocks_analysis_but_allows_public_commands(settings, repo):
    gate = SubscriptionMiddleware(replace(settings, subscriptions_enabled=True, owner_telegram_ids="8368948762"), repo)
    calls = []

    async def handler(event, data):
        calls.append(event)
        return "ok"

    assert await gate(handler, Message("/start", user_id=8201), {}) == "ok"
    assert await gate(handler, Message("/activate NX-X", user_id=8201), {}) == "ok"
    assert await gate(handler, Callback("nx:home", user_id=8201), {}) == "ok"
    assert calls and len(calls) == 3

    blocked = Callback("nx:market:OTC", user_id=8201)
    assert await gate(handler, blocked, {}) is None
    assert "الاشتراك غير نشط" in blocked.answers[0]
    assert any("الاشتراك غير نشط" in text for text, _ in blocked.message.sent)
    assert await gate(handler, Message("hello", user_id=8201), {}) is None
    assert len(calls) == 3

    code = await repo.create_activation_code(30, created_by=9001)
    await repo.activate_code(code.code, 8201)
    assert await gate(handler, Callback("nx:market:OTC", user_id=8201), {}) == "ok"
    assert await gate(handler, Message("/lo", user_id=8201), {}) == "ok"


@pytest.mark.asyncio
async def test_owners_bypass_the_subscription_gate(settings, repo):
    gate = SubscriptionMiddleware(replace(settings, subscriptions_enabled=True, owner_telegram_ids="8368948762"), repo)

    async def handler(event, data):
        return "ok"

    assert await gate(handler, Callback("nx:market:OTC", user_id=8368948762), {}) == "ok"


@pytest.mark.asyncio
async def test_admin_creates_lists_and_revokes_codes(repo):
    callback = Callback("adm:days:30", user_id=9001)
    await admin_handlers.cb_days(callback, repo)
    text, _ = callback.message.sent[-1]
    assert "تم إنشاء كود تفعيل جديد" in text
    import re
    created_code = re.search(r"(NX-[A-Z0-9]{4}(?:-[A-Z0-9]{4}){3})", text).group(1)

    available = Callback("adm:codes:avail", user_id=9001)
    await admin_handlers.cb_codes(available, repo)
    assert any("NX-****-****-" in text for text, _ in available.message.sent)

    await repo.activate_code(created_code, 8301, username="user8301")
    used = Callback("adm:codes:used", user_id=9001)
    await admin_handlers.cb_codes(used, repo)
    assert any("NX-****-****-" in text for text, _ in used.message.sent)

    customers = Callback("adm:cust", user_id=9001)
    await admin_handlers.cb_customers(customers, repo)
    assert any("8301" in text for text, _ in customers.message.sent)

    revoke = Callback("adm:revoke:8301", user_id=9001)
    await admin_handlers.cb_revoke(revoke, repo)
    confirm = Callback("adm:revoke:yes:8301", user_id=9001)
    await admin_handlers.cb_revoke(confirm, repo)
    assert await repo.is_subscribed(8301) is False
    assert (await repo.subscription_for(8301)).status == "REVOKED"


@pytest.mark.asyncio
async def test_admin_notification_loop_delivers_and_clears_queue(repo):
    class Bot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, **kwargs):
            self.sent.append((chat_id, text))

    code = await repo.create_activation_code(1, created_by=9001)
    await repo.activate_code(code.code, 8401, username="notify", first_name="N")
    bot = Bot()
    task = asyncio.create_task(notification_loop(bot, repo, frozenset({9001})))
    for _ in range(30):
        await asyncio.sleep(0.05)
        if bot.sent:
            break
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert bot.sent and bot.sent[0][0] == 9001
    assert "NX-****-****-" in bot.sent[0][1]
    assert "8401" in bot.sent[0][1]
    assert "يوم واحد" in bot.sent[0][1]
    assert await repo.pending_notifications() == []


def test_subscription_texts_never_fake_a_calibrated_confidence():
    from database.repository import SubscriptionRecord

    now = datetime.now(timezone.utc)
    record = SubscriptionRecord(
        telegram_id=1,
        username="u",
        first_name=None,
        plan_days=30,
        activated_at=now,
        expires_at=now + timedelta(days=30),
        status="ACTIVE",
        last_code="NX-TEST",
        updated_at=now,
    )
    text = fmt.subscription_status_text(record)
    assert "ACTIVE" in text
    assert "%" not in text


@pytest.mark.asyncio
async def test_admin_bot_rejects_customers_and_allows_owner():
    from admin_bot.middleware import OwnerOnlyMiddleware

    gate = OwnerOnlyMiddleware(frozenset({9001}))

    async def handler(event, data):
        return "owner"

    assert await gate(handler, Message("/start", user_id=9001), {}) == "owner"

    customer_message = Message("/start", user_id=9301)
    assert await gate(handler, customer_message, {}) is None
    assert "مخصص لمالك النظام فقط" in customer_message.sent[-1][0]

    customer_callback = Callback("adm:new", user_id=9301)
    assert await gate(handler, customer_callback, {}) is None
    assert "غير مصرح" in customer_callback.answers[-1]
    assert customer_callback.message.sent == []
