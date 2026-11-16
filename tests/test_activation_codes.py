"""End-to-end activation-code scenarios: issue, reject, activate, reuse, expiry, ban."""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from admin_bot import handlers as admin_handlers
from admin_bot.middleware import OwnerOnlyMiddleware
from bot.middleware.subscription import SubscriptionMiddleware
from config import PRIMARY_OWNER_ID
from database.repository import Repository, hash_activation_code


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


class FakeState:
    def __init__(self):
        self.current = None

    async def set_state(self, value):
        self.current = value

    async def clear(self):
        self.current = None


def issued_code(callback: Callback) -> str:
    text, _ = callback.message.sent[-1]
    match = re.search(r"(NX-[A-Z0-9]{4}(?:-[A-Z0-9]{4}){3})", text)
    assert match, text
    return match.group(1)


@pytest.mark.asyncio
async def test_owner_issues_a_unique_hashed_code(repo):
    first = Callback("adm:days:30", user_id=PRIMARY_OWNER_ID)
    second = Callback("adm:days:30", user_id=PRIMARY_OWNER_ID)
    await admin_handlers.cb_days(first, repo)
    await admin_handlers.cb_days(second, repo)
    code_one, code_two = issued_code(first), issued_code(second)

    assert code_one != code_two
    assert re.fullmatch(r"NX-[A-Z0-9]{4}(?:-[A-Z0-9]{4}){3}", code_one)

    stored = await repo.list_codes()
    assert stored
    assert all(code.code.startswith("NX-****-****-") for code in stored)
    assert code_one not in {code.code for code in stored}
    assert await repo.find_code_by_hash(hash_activation_code(code_one)) is not None


@pytest.mark.asyncio
async def test_non_owner_cannot_issue_or_use_the_admin_panel(repo, settings):
    gate = OwnerOnlyMiddleware(frozenset({PRIMARY_OWNER_ID}))

    async def handler(event, data):
        return "handled"

    assert await gate(handler, Callback("adm:days:30", user_id=9001), {"repo": repo}) is None
    assert await gate(handler, Callback("adm:days:30", user_id=PRIMARY_OWNER_ID), {"repo": repo}) == "handled"


@pytest.mark.asyncio
async def test_customer_activates_code_once(repo):
    admin = Callback("adm:days:7", user_id=PRIMARY_OWNER_ID)
    await admin_handlers.cb_days(admin, repo)
    code = issued_code(admin)

    result = await repo.activate_code(code, 7001, username="buyer")
    assert result.status == "ACTIVATED"
    assert result.subscription.telegram_id == 7001
    assert await repo.is_subscribed(7001) is True


@pytest.mark.asyncio
async def test_reuse_and_second_account_are_rejected(repo):
    admin = Callback("adm:days:30", user_id=PRIMARY_OWNER_ID)
    await admin_handlers.cb_days(admin, repo)
    code = issued_code(admin)

    assert (await repo.activate_code(code, 7101, username="first")).status == "ACTIVATED"
    again = await repo.activate_code(code, 7101, username="first")
    assert again.status == "USED"
    other = await repo.activate_code(code, 7102, username="second")
    assert other.status == "USED"
    assert await repo.is_subscribed(7102) is False


@pytest.mark.asyncio
async def test_expired_subscription_stops_protected_features(repo, settings):
    admin = Callback("adm:days:1", user_id=PRIMARY_OWNER_ID)
    await admin_handlers.cb_days(admin, repo)
    code = issued_code(admin)
    activation_time = datetime.now(timezone.utc) - timedelta(days=2)
    result = await repo.activate_code(code, 7201, username="expired", now=activation_time)
    assert result.status == "ACTIVATED"
    assert await repo.is_subscribed(7201) is False

    gate = SubscriptionMiddleware(replace(settings, subscriptions_enabled=True), repo)

    async def handler(event, data):
        return "handled"

    assert await gate(handler, Callback("nx:analysis", user_id=7201), {}) is None
    assert await gate(handler, Callback("nx:analysis", user_id=PRIMARY_OWNER_ID), {}) == "handled"


@pytest.mark.asyncio
async def test_ban_revokes_access_and_blocks_future_activation(repo):
    admin = Callback("adm:days:30", user_id=PRIMARY_OWNER_ID)
    await admin_handlers.cb_days(admin, repo)
    code = issued_code(admin)
    await repo.activate_code(code, 7301, username="banned")

    assert await repo.ban_subscription(7301) is True
    assert await repo.is_subscribed(7301) is False
    fresh = await repo.create_activation_code(30, created_by=PRIMARY_OWNER_ID)
    blocked = await repo.activate_code(fresh.code, 7301, username="banned")
    assert blocked.status == "BANNED"


@pytest.mark.asyncio
async def test_extend_reactivates_expired_subscription(repo):
    admin = Callback("adm:days:1", user_id=PRIMARY_OWNER_ID)
    await admin_handlers.cb_days(admin, repo)
    code = issued_code(admin)
    await repo.activate_code(code, 7401, now=datetime.now(timezone.utc) - timedelta(days=3))
    assert await repo.is_subscribed(7401) is False

    extended = await repo.extend_subscription(7401, 7)
    assert extended is not None and extended.active is True
    assert await repo.is_subscribed(7401) is True


@pytest.mark.asyncio
async def test_admin_panel_lists_extends_and_bans_customers(repo):
    admin = Callback("adm:days:30", user_id=PRIMARY_OWNER_ID)
    await admin_handlers.cb_days(admin, repo)
    code = issued_code(admin)
    await repo.activate_code(code, 7501, username="panel")

    listing = Callback("adm:cust", user_id=PRIMARY_OWNER_ID)
    await admin_handlers.cb_customers(listing, repo)
    assert any("7501" in text for text, _ in listing.message.sent)

    view = Callback("adm:view:7501", user_id=PRIMARY_OWNER_ID)
    await admin_handlers.cb_view_customer(view, repo)
    profile = view.message.sent[-1][0]
    assert "بداية الاشتراك" in profile and "نهاية الاشتراك" in profile

    extend_menu = Callback("adm:ext:7501", user_id=PRIMARY_OWNER_ID)
    await admin_handlers.cb_extend(extend_menu)
    extend = Callback("adm:extdays:7501:7", user_id=PRIMARY_OWNER_ID)
    await admin_handlers.cb_extend_days(extend, repo)
    record = await repo.subscription_for(7501)
    assert record.plan_days >= 37

    confirm = Callback("adm:ban:7501", user_id=PRIMARY_OWNER_ID)
    await admin_handlers.cb_ban(confirm, repo)
    assert "هل تريد حظر" in confirm.message.sent[-1][0]
    banned = Callback("adm:ban:yes:7501", user_id=PRIMARY_OWNER_ID)
    await admin_handlers.cb_ban(banned, repo)
    assert await repo.is_subscribed(7501) is False


@pytest.mark.asyncio
async def test_owner_can_search_a_customer_by_telegram_id(repo):
    admin = Callback("adm:days:7", user_id=PRIMARY_OWNER_ID)
    await admin_handlers.cb_days(admin, repo)
    await repo.activate_code(issued_code(admin), 7701, username="searchable")

    state = FakeState()
    prompt = Callback("adm:search", user_id=PRIMARY_OWNER_ID)
    await admin_handlers.cb_search(prompt, state)
    assert state.current is not None
    assert "Telegram ID" in prompt.message.sent[-1][0]

    reply = Message(user_id=PRIMARY_OWNER_ID, text="7701")
    await admin_handlers.msg_search_customer(reply, repo, state)
    assert state.current is None
    assert "7701" in reply.sent[-1][0]


@pytest.mark.asyncio
async def test_legacy_plaintext_codes_are_migrated_idempotently(repo):
    from datetime import datetime, timezone

    from database.models import SubscriptionCode

    async with repo._session() as session:
        session.add(
            SubscriptionCode(
                code="NX-LEGACY-CODE-0001",
                code_hash=None,
                duration_days=30,
                status="AVAILABLE",
                created_by=PRIMARY_OWNER_ID,
                created_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    async with repo._engine.begin() as connection:
        await repo._migrate_code_hashes(connection)
    async with repo._engine.begin() as connection:
        await repo._migrate_code_hashes(connection)

    migrated = await repo.find_code_by_hash(hash_activation_code("NX-LEGACY-CODE-0001"))
    assert migrated is not None
    assert migrated.code.startswith("NX-****-****-")
    result = await repo.activate_code("NX-LEGACY-CODE-0001", 7601, username="legacy")
    assert result.status == "ACTIVATED"


@pytest.mark.asyncio
async def test_customer_bot_stays_functional_alongside_activation(repo):
    from bot.handlers import menus

    assert menus.router is not None
    assert any(observer.callback.__name__ == "cmd_start" for observer in menus.router.message.handlers)
    assert await repo.is_subscribed(999999) is False
