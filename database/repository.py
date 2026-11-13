"""Async repository: only verified outcomes feed statistics."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import Settings, normalise_database_url
from database.models import Base, Signal, UserSettings

STATUS_ACTIVE = "ACTIVE"
STATUS_WIN = "WIN"
STATUS_LOSS = "LOSS"
STATUS_DRAW = "DRAW"
STATUS_UNVERIFIED = "UNVERIFIED"


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


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
    entry_at: datetime | None = None


class Repository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._engine = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def init(self) -> None:
        self._engine = create_async_engine(normalise_database_url(self.settings.database_url), future=True)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)
        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            columns = await connection.run_sync(
                lambda sync: {column["name"] for column in inspect(sync).get_columns("signals")}
            )
            if "result_reason" not in columns:
                await connection.execute(text("ALTER TABLE signals ADD COLUMN result_reason TEXT"))
            if "entry_at" not in columns:
                ddl = (
                    "ALTER TABLE signals ADD COLUMN entry_at TIMESTAMP"
                    if connection.dialect.name == "sqlite"
                    else "ALTER TABLE signals ADD COLUMN entry_at TIMESTAMP WITH TIME ZONE"
                )
                await connection.execute(text(ddl))

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
        entry_at: datetime | None = None,
    ) -> SignalRecord:
        entry_at = entry_at or created_at
        expires_at = entry_at + timedelta(seconds=expiry_seconds)
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
                entry_at=entry_at,
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
            entry_at=_aware(getattr(row, "entry_at", None)) or _aware(row.created_at),
            close_price=row.close_price,
            verified_at=_aware(row.verified_at),
            verification_source=row.verification_source,
            result_reason=row.result_reason,
        )
