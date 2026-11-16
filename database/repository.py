"""Async repository: only verified outcomes feed statistics."""
from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import Settings, normalise_database_url
from database.models import (
    Base,
    Signal,
    Subscription,
    SubscriptionCode,
    SubscriptionNotification,
    UserMode,
    UserSettings,
)

STATUS_ACTIVE = "ACTIVE"
STATUS_WIN = "WIN"
STATUS_LOSS = "LOSS"
STATUS_DRAW = "DRAW"
STATUS_UNVERIFIED = "UNVERIFIED"


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


CODE_AVAILABLE = "AVAILABLE"
CODE_USED = "USED"
CODE_DISABLED = "DISABLED"
SUB_ACTIVE = "ACTIVE"
SUB_EXPIRED = "EXPIRED"
SUB_REVOKED = "REVOKED"
SUB_BANNED = "BANNED"

_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def hash_activation_code(code: str) -> str:
    normalised = (code or "").strip().upper()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


@dataclass
class CodeRecord:
    id: int
    code: str
    duration_days: int
    status: str
    created_by: int
    created_at: datetime
    used_by: int | None = None
    used_at: datetime | None = None


@dataclass
class SubscriptionRecord:
    telegram_id: int
    username: str | None
    first_name: str | None
    plan_days: int
    activated_at: datetime
    expires_at: datetime
    status: str
    last_code: str
    updated_at: datetime

    @property
    def active(self) -> bool:
        return self.status == SUB_ACTIVE and self.expires_at > datetime.now(timezone.utc)

    @property
    def seconds_left(self) -> int:
        return max(0, int((self.expires_at - datetime.now(timezone.utc)).total_seconds()))


@dataclass
class ActivationResult:
    status: str
    message: str
    code: str | None = None
    subscription: SubscriptionRecord | None = None


@dataclass
class NotificationRecord:
    id: int
    event: str
    payload: dict
    created_at: datetime


@dataclass
class SignalRecord:
    id: int
    user_id: int
    asset_key: str
    asset_display: str
    market: str
    timeframe: str
    direction: str
    confidence: float
    entry_price: float
    source: str
    reasons: list[str]
    warnings: list[str]
    expiry_seconds: int
    created_at: datetime
    expires_at: datetime
    status: str
    close_price: float | None = None
    verified_at: datetime | None = None
    verification_source: str | None = None
    result_reason: str | None = None


class Repository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._engine = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def init(self) -> None:
        self._engine = create_async_engine(normalise_database_url(self.settings.database_url), future=True)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        async with self._engine.begin() as connection:
            postgres = connection.dialect.name == "postgresql"
            if postgres:
                # Serialize startup schema work if both services initialize together.
                await connection.execute(text("SELECT pg_advisory_xact_lock(782136460)"))
            await connection.run_sync(Base.metadata.create_all)
            if postgres:
                await self._migrate_telegram_user_ids(connection)
            signal_columns = await connection.run_sync(
                lambda sync: {column["name"] for column in inspect(sync).get_columns("signals")}
            )
            if "result_reason" not in signal_columns:
                await connection.execute(text("ALTER TABLE signals ADD COLUMN result_reason TEXT"))
            await self._migrate_code_hashes(connection)

    @staticmethod
    async def _migrate_telegram_user_ids(connection) -> None:
        """Keep Telegram account IDs above 2³¹-1 usable on existing PostgreSQL databases."""
        for table in ("signals", "user_modes", "user_settings"):
            columns = await connection.run_sync(
                lambda sync: inspect(sync).get_columns(table)
            )
            kind = next((str(col["type"]) for col in columns if col["name"] == "user_id"), None)
            if kind == "INTEGER":
                await connection.execute(text(f"ALTER TABLE {table} ALTER COLUMN user_id TYPE BIGINT"))

    async def _migrate_code_hashes(self, connection) -> None:
        """Hash legacy plaintext codes in place, then erase the plaintext."""
        columns = await connection.run_sync(
            lambda sync: {column["name"] for column in inspect(sync).get_columns("subscription_codes")}
        )
        if "code_hash" not in columns:
            await connection.execute(text("ALTER TABLE subscription_codes ADD COLUMN code_hash VARCHAR(64)"))
        rows = (
            await connection.execute(text("SELECT id, code, code_hash FROM subscription_codes"))
        ).mappings().all()
        for row in rows:
            stored = row["code"] or ""
            digest = row["code_hash"] or hash_activation_code(stored)
            await connection.execute(
                text(
                    "UPDATE subscription_codes SET code_hash = :digest, code = :masked WHERE id = :id"
                ),
                {"digest": digest, "masked": digest[:32], "id": row["id"]},
            )
            if stored and stored != digest[:32]:
                await connection.execute(
                    text("UPDATE subscriptions SET last_code = :masked WHERE last_code = :stored"),
                    {"masked": digest[:16], "stored": stored},
                )
        await connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_subscription_codes_code_hash "
                "ON subscription_codes (code_hash)"
            )
        )

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None

    def _session(self) -> AsyncSession:
        if self._session_factory is None:
            raise RuntimeError("Repository.init() was not called")
        return self._session_factory()

    async def add_signal(
        self,
        user_id: int,
        asset_key: str,
        asset_display: str,
        market: str,
        timeframe: str,
        direction: str,
        confidence: float,
        entry_price: float,
        source: str,
        reasons: list[str],
        warnings: list[str],
        expiry_seconds: int,
        created_at: datetime,
    ) -> SignalRecord:
        expires_at = created_at + timedelta(seconds=expiry_seconds)
        async with self._session() as session:
            row = Signal(
                user_id=user_id,
                asset_key=asset_key,
                asset_display=asset_display,
                market=market,
                timeframe=timeframe,
                direction=direction,
                confidence=confidence,
                entry_price=entry_price,
                source=source,
                reasons=json.dumps(reasons, ensure_ascii=False),
                warnings=json.dumps(warnings, ensure_ascii=False),
                expiry_seconds=expiry_seconds,
                created_at=created_at,
                expires_at=expires_at,
                status=STATUS_ACTIVE,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._to_record(row)

    async def active_signals(self, user_id: int | None = None, limit: int = 25) -> list[SignalRecord]:
        statement = select(Signal).where(Signal.status == STATUS_ACTIVE).order_by(Signal.created_at.desc()).limit(limit)
        if user_id is not None:
            statement = statement.where(Signal.user_id == user_id)
        async with self._session() as session:
            rows = (await session.scalars(statement)).all()
            return [self._to_record(row) for row in rows]

    async def due_signals(self, now: datetime) -> list[SignalRecord]:
        statement = select(Signal).where(Signal.status == STATUS_ACTIVE, Signal.expires_at <= now)
        async with self._session() as session:
            rows = (await session.scalars(statement)).all()
            return [self._to_record(row) for row in rows]

    async def finish_signal(
        self,
        signal_id: int,
        result: str,
        close_price: float | None,
        verified_at: datetime | None,
        source: str | None,
        reason: str | None = None,
    ) -> None:
        async with self._session() as session:
            row = await session.get(Signal, signal_id)
            if row is None or row.status != STATUS_ACTIVE:
                return
            row.status = result
            row.close_price = close_price
            row.verified_at = verified_at
            row.verification_source = source
            row.result_reason = reason
            await session.commit()

    async def recent_signals(self, limit: int = 10, user_id: int | None = None) -> list[SignalRecord]:
        statement = select(Signal).order_by(Signal.created_at.desc()).limit(limit)
        if user_id is not None:
            statement = statement.where(Signal.user_id == user_id)
        async with self._session() as session:
            return [self._to_record(row) for row in (await session.scalars(statement)).all()]

    async def recent_signal_exists(self, asset_key: str, since: datetime) -> bool:
        statement = (
            select(Signal.id)
            .where(Signal.asset_key == asset_key, Signal.created_at >= since)
            .limit(1)
        )
        async with self._session() as session:
            return (await session.execute(statement)).first() is not None

    async def statistics(self, user_id: int | None = None) -> dict:
        async with self._session() as session:
            statuses: dict[str, int] = {}
            statement = select(Signal.status, func.count(Signal.id)).group_by(Signal.status)
            if user_id is not None:
                statement = statement.where(Signal.user_id == user_id)
            for status, count in (await session.execute(statement)).all():
                statuses[status] = int(count)

            avg_statement = select(func.avg(Signal.confidence)).where(
                Signal.status.in_((STATUS_WIN, STATUS_LOSS, STATUS_DRAW))
            )
            if user_id is not None:
                avg_statement = avg_statement.where(Signal.user_id == user_id)
            avg_confidence = (await session.execute(avg_statement)).scalar()

            best_statement = (
                select(Signal.asset_display, func.count(Signal.id))
                .where(Signal.status == STATUS_WIN)
                .group_by(Signal.asset_display)
                .order_by(func.count(Signal.id).desc())
                .limit(1)
            )
            if user_id is not None:
                best_statement = best_statement.where(Signal.user_id == user_id)
            best = (await session.execute(best_statement)).first()

            closed_statement = select(
                Signal.market, Signal.status, Signal.entry_price, Signal.close_price
            ).where(Signal.status.in_((STATUS_WIN, STATUS_LOSS, STATUS_DRAW)))
            if user_id is not None:
                closed_statement = closed_statement.where(Signal.user_id == user_id)
            closed_rows = (await session.execute(closed_statement)).all()

        per_market: dict[str, dict] = {}
        gross_gain = 0.0
        gross_loss = 0.0
        for market, status, entry, close in closed_rows:
            row = per_market.setdefault(
                market, {"wins": 0, "losses": 0, "draws": 0, "win_rate": None}
            )
            if status == STATUS_WIN:
                row["wins"] += 1
            elif status == STATUS_LOSS:
                row["losses"] += 1
            else:
                row["draws"] += 1
            if entry and close and entry > 0:
                move = abs((float(close) - float(entry)) / float(entry))
                if status == STATUS_WIN:
                    gross_gain += move
                elif status == STATUS_LOSS:
                    gross_loss += move
        for row in per_market.values():
            decided = row["wins"] + row["losses"]
            row["win_rate"] = round(row["wins"] / decided * 100, 1) if decided else None

        wins = statuses.get(STATUS_WIN, 0)
        losses = statuses.get(STATUS_LOSS, 0)
        draws = statuses.get(STATUS_DRAW, 0)
        verified = wins + losses + draws
        decided = wins + losses
        return {
            "total": sum(statuses.values()),
            "active": statuses.get(STATUS_ACTIVE, 0),
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "unverified": statuses.get(STATUS_UNVERIFIED, 0),
            "verified": verified,
            "accuracy": round((wins / decided) * 100, 1) if decided else None,
            "avg_confidence": round(float(avg_confidence), 1) if avg_confidence is not None else None,
            "best_asset": best[0] if best else None,
            "best_asset_wins": int(best[1]) if best else 0,
            "per_market": per_market,
            "profit_factor": round(gross_gain / gross_loss, 2) if gross_loss > 0 else None,
        }

    async def get_user_settings(self, user_id: int, defaults: dict | None = None) -> dict:
        defaults = defaults or {"markets": ["FOREX"], "min_confidence": 60.0, "scanner_enabled": True}
        async with self._session() as session:
            row = await session.get(UserSettings, user_id)
            if row is None:
                return dict(defaults)
            try:
                markets = json.loads(row.markets)
            except (TypeError, ValueError):
                markets = defaults["markets"]
            return {
                "markets": markets,
                "min_confidence": row.min_confidence,
                "scanner_enabled": bool(row.scanner_enabled),
            }

    async def save_user_settings(self, user_id: int, settings: dict) -> None:
        async with self._session() as session:
            row = await session.get(UserSettings, user_id)
            if row is None:
                row = UserSettings(user_id=user_id, updated_at=datetime.now(timezone.utc))
                session.add(row)
            row.markets = json.dumps(settings.get("markets", ["FOREX"]))
            row.min_confidence = float(settings.get("min_confidence", 60.0))
            row.scanner_enabled = 1 if settings.get("scanner_enabled", True) else 0
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()

    async def get_analysis_mode(self, user_id: int) -> str:
        async with self._session() as session:
            row = await session.get(UserMode, user_id)
            return row.mode if row and row.mode in {"strong", "lo"} else "strong"

    async def set_analysis_mode(self, user_id: int, mode: str) -> str:
        if mode not in {"strong", "lo"}:
            raise ValueError("mode must be 'strong' or 'lo'")
        async with self._session() as session:
            row = await session.get(UserMode, user_id)
            if row is None:
                row = UserMode(user_id=user_id, mode=mode, updated_at=datetime.now(timezone.utc))
                session.add(row)
            row.mode = mode
            row.updated_at = datetime.now(timezone.utc)
            await session.commit()
        return mode

    async def create_activation_code(self, duration_days: int, created_by: int) -> CodeRecord:
        if duration_days <= 0:
            raise ValueError("duration_days must be positive")
        now = datetime.now(timezone.utc)
        for _ in range(12):
            groups = [
                "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
                for _ in range(4)
            ]
            code = "NX-" + "-".join(groups)
            digest = hash_activation_code(code)
            async with self._session() as session:
                row = SubscriptionCode(
                    code=digest[:32],
                    code_hash=digest,
                    duration_days=duration_days,
                    status=CODE_AVAILABLE,
                    created_by=created_by,
                    created_at=now,
                )
                session.add(row)
                try:
                    await session.commit()
                except IntegrityError:
                    await session.rollback()
                    continue
                await session.refresh(row)
                return self._code_record(row, revealed_code=code)
        raise RuntimeError("could not generate a unique activation code")

    async def list_codes(self, status: str | None = None, limit: int = 50) -> list[CodeRecord]:
        statement = select(SubscriptionCode).order_by(SubscriptionCode.created_at.desc()).limit(limit)
        if status is not None:
            statement = statement.where(SubscriptionCode.status == status)
        async with self._session() as session:
            rows = (await session.scalars(statement)).all()
            return [self._code_record(row) for row in rows]

    async def find_code_by_hash(self, digest: str) -> CodeRecord | None:
        async with self._session() as session:
            row = await session.scalar(
                select(SubscriptionCode).where(SubscriptionCode.code_hash == digest)
            )
            return self._code_record(row) if row is not None else None

    async def disable_code(self, code_id: int) -> bool:
        async with self._session() as session:
            row = await session.get(SubscriptionCode, code_id)
            if row is None or row.status != CODE_AVAILABLE:
                return False
            row.status = CODE_DISABLED
            await session.commit()
        return True

    async def activate_code(
        self,
        code: str,
        telegram_id: int,
        username: str | None = None,
        first_name: str | None = None,
        now: datetime | None = None,
    ) -> ActivationResult:
        normalised = (code or "").strip().upper()
        digest = hash_activation_code(normalised)
        now = now or datetime.now(timezone.utc)
        async with self._session() as session:
            async with session.begin():
                existing_subscription = await session.get(Subscription, telegram_id)
                if existing_subscription is not None and existing_subscription.status == SUB_BANNED:
                    return ActivationResult("BANNED", "هذا الحساب محظور ولا يمكنه تفعيل أي كود.")
                claimed = await session.execute(
                    update(SubscriptionCode)
                    .where(
                        SubscriptionCode.code_hash == digest,
                        SubscriptionCode.status == CODE_AVAILABLE,
                        SubscriptionCode.used_by.is_(None),
                    )
                    .values(status=CODE_USED, used_by=telegram_id, used_at=now)
                )
                if claimed.rowcount != 1:
                    existing = await session.scalar(
                        select(SubscriptionCode).where(SubscriptionCode.code_hash == digest)
                    )
                    if existing is None:
                        return ActivationResult("INVALID", "الكود غير موجود.")
                    if existing.status == CODE_DISABLED:
                        return ActivationResult("DISABLED", "هذا الكود معطل.")
                    return ActivationResult("USED", "هذا الكود مستخدم مسبقاً ولا يمكن تفعيله مرة أخرى.")
                row = await session.scalar(
                    select(SubscriptionCode).where(SubscriptionCode.code_hash == digest)
                )
                duration = row.duration_days
                expires_at = now + timedelta(days=duration)
                subscription = await session.get(Subscription, telegram_id)
                if subscription is None:
                    subscription = Subscription(
                        telegram_id=telegram_id,
                        username=username,
                        first_name=first_name,
                        plan_days=duration,
                        activated_at=now,
                        expires_at=expires_at,
                        status=SUB_ACTIVE,
                        last_code=digest[:16],
                        updated_at=now,
                    )
                    session.add(subscription)
                else:
                    subscription.username = username or subscription.username
                    subscription.first_name = first_name or subscription.first_name
                    subscription.plan_days = duration
                    subscription.activated_at = now
                    subscription.expires_at = expires_at
                    subscription.status = SUB_ACTIVE
                    subscription.last_code = digest[:16]
                    subscription.updated_at = now
                payload = {
                    "code": f"NX-****-****-{normalised[-4:]}",
                    "telegram_id": telegram_id,
                    "username": username,
                    "duration_days": duration,
                    "activated_at": now.isoformat(),
                    "expires_at": expires_at.isoformat(),
                    "status": SUB_ACTIVE,
                }
                session.add(
                    SubscriptionNotification(
                        event="ACTIVATED",
                        payload=json.dumps(payload, ensure_ascii=False),
                        created_at=now,
                    )
                )
                await session.flush()
                record = self._subscription_record(subscription)
                return ActivationResult("ACTIVATED", "تم تفعيل الاشتراك.", normalised, record)

    async def subscription_for(self, telegram_id: int, now: datetime | None = None) -> SubscriptionRecord | None:
        now = now or datetime.now(timezone.utc)
        async with self._session() as session:
            row = await session.get(Subscription, telegram_id)
            if row is None:
                return None
            record = self._subscription_record(row)
            if record.status == SUB_ACTIVE and record.expires_at <= now:
                row.status = SUB_EXPIRED
                row.updated_at = now
                await session.commit()
                record = self._subscription_record(row)
            return record

    async def is_subscribed(self, telegram_id: int, now: datetime | None = None) -> bool:
        record = await self.subscription_for(telegram_id, now)
        return bool(record and record.active)

    async def list_subscriptions(self, limit: int = 100) -> list[SubscriptionRecord]:
        statement = select(Subscription).order_by(Subscription.expires_at.desc()).limit(limit)
        async with self._session() as session:
            rows = (await session.scalars(statement)).all()
            return [self._subscription_record(row) for row in rows]

    async def revoke_subscription(self, telegram_id: int, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        async with self._session() as session:
            row = await session.get(Subscription, telegram_id)
            if row is None:
                return False
            row.status = SUB_REVOKED
            row.expires_at = min(_aware(row.expires_at), now)
            row.updated_at = now
            await session.commit()
        return True

    async def extend_subscription(
        self, telegram_id: int, days: int, now: datetime | None = None
    ) -> SubscriptionRecord | None:
        if days <= 0:
            raise ValueError("days must be positive")
        now = now or datetime.now(timezone.utc)
        async with self._session() as session:
            row = await session.get(Subscription, telegram_id)
            if row is None or row.status == SUB_BANNED:
                return None
            current_expiry = _aware(row.expires_at) or now
            row.expires_at = max(current_expiry, now) + timedelta(days=days)
            row.plan_days = int(row.plan_days or 0) + days
            row.status = SUB_ACTIVE
            row.updated_at = now
            await session.commit()
            return self._subscription_record(row)

    async def ban_subscription(self, telegram_id: int, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        async with self._session() as session:
            row = await session.get(Subscription, telegram_id)
            if row is None:
                return False
            row.status = SUB_BANNED
            row.expires_at = min(_aware(row.expires_at) or now, now)
            row.updated_at = now
            await session.commit()
        return True

    async def pending_notifications(self, limit: int = 25) -> list[NotificationRecord]:
        statement = (
            select(SubscriptionNotification)
            .where(SubscriptionNotification.sent_at.is_(None))
            .order_by(SubscriptionNotification.created_at)
            .limit(limit)
        )
        async with self._session() as session:
            rows = (await session.scalars(statement)).all()
            return [
                NotificationRecord(
                    id=row.id,
                    event=row.event,
                    payload=json.loads(row.payload or "{}"),
                    created_at=_aware(row.created_at),
                )
                for row in rows
            ]

    async def mark_notification_sent(self, notification_id: int, error: str | None = None) -> None:
        async with self._session() as session:
            row = await session.get(SubscriptionNotification, notification_id)
            if row is None:
                return
            row.sent_at = datetime.now(timezone.utc)
            row.error = error
            await session.commit()

    @staticmethod
    def _code_record(row: SubscriptionCode, revealed_code: str | None = None) -> CodeRecord:
        masked = "NX-****-****-" + (row.code_hash or row.code or "")[-4:]
        return CodeRecord(
            id=row.id,
            code=revealed_code or masked,
            duration_days=row.duration_days,
            status=row.status,
            created_by=row.created_by,
            created_at=_aware(row.created_at),
            used_by=row.used_by,
            used_at=_aware(row.used_at),
        )

    @staticmethod
    def _subscription_record(row: Subscription) -> SubscriptionRecord:
        return SubscriptionRecord(
            telegram_id=row.telegram_id,
            username=row.username,
            first_name=row.first_name,
            plan_days=row.plan_days,
            activated_at=_aware(row.activated_at),
            expires_at=_aware(row.expires_at),
            status=row.status,
            last_code=row.last_code,
            updated_at=_aware(row.updated_at),
        )

    @staticmethod
    def _to_record(row: Signal) -> SignalRecord:
        try:
            reasons = json.loads(row.reasons or "[]")
        except (TypeError, ValueError):
            reasons = []
        try:
            warnings = json.loads(row.warnings or "[]")
        except (TypeError, ValueError):
            warnings = []
        return SignalRecord(
            id=row.id,
            user_id=row.user_id,
            asset_key=row.asset_key,
            asset_display=row.asset_display,
            market=row.market,
            timeframe=row.timeframe,
            direction=row.direction,
            confidence=row.confidence,
            entry_price=row.entry_price,
            source=row.source,
            reasons=reasons,
            warnings=warnings,
            expiry_seconds=row.expiry_seconds,
            created_at=_aware(row.created_at),
            expires_at=_aware(row.expires_at),
            status=row.status,
            close_price=row.close_price,
            verified_at=_aware(row.verified_at),
            verification_source=row.verification_source,
            result_reason=row.result_reason,
        )
