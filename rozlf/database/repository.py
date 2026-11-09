"""Persistence layer for signals and statistics."""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .models import Base, SignalRow


class SignalRepository:
    def __init__(self, engine: AsyncEngine):
        self._engine = engine
        self._session: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

    @classmethod
    async def create(cls, database_url: str) -> "SignalRepository":
        if database_url.startswith("sqlite"):
            path = database_url.split("///")[-1]
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
        engine = create_async_engine(database_url, pool_pre_ping=True)
        repo = cls(engine)
        await repo.init()
        return repo

    async def init(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def add(self, **fields) -> SignalRow:
        row = SignalRow(**fields)
        async with self._session() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def get(self, signal_id: int) -> SignalRow | None:
        async with self._session() as session:
            return await session.get(SignalRow, signal_id)

    async def list(self, *, status: str | None = None, limit: int = 10, symbol: str | None = None) -> list[SignalRow]:
        stmt = select(SignalRow).order_by(SignalRow.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(SignalRow.status == status)
        if symbol:
            stmt = stmt.where(SignalRow.symbol == symbol.upper())
        async with self._session() as session:
            return list((await session.scalars(stmt)).all())

    async def due_for_resolution(self, now: int | None = None, max_attempts: int = 20) -> list[SignalRow]:
        now = now or int(time.time())
        stmt = (
            select(SignalRow)
            .where(SignalRow.status == "OPEN", SignalRow.expires_at <= now, SignalRow.resolve_attempts < max_attempts)
            .order_by(SignalRow.expires_at.asc())
            .limit(20)
        )
        async with self._session() as session:
            return list((await session.scalars(stmt)).all())

    async def recent_duplicate(self, symbol: str, direction: str, timeframe: int, within_seconds: int) -> bool:
        since = int(time.time()) - within_seconds
        stmt = (
            select(func.count())
            .select_from(SignalRow)
            .where(
                SignalRow.symbol == symbol,
                SignalRow.direction == direction,
                SignalRow.timeframe == timeframe,
                SignalRow.created_at >= since,
            )
        )
        async with self._session() as session:
            return bool((await session.scalar(stmt)) or 0)

    async def count_since(self, since_ts: int) -> int:
        stmt = select(func.count()).select_from(SignalRow).where(SignalRow.created_at >= since_ts)
        async with self._session() as session:
            return int((await session.scalar(stmt)) or 0)

    async def count_today(self) -> int:
        midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        return await self.count_since(int(midnight.timestamp()))

    async def mark_attempt(self, signal_id: int) -> None:
        async with self._session() as session:
            row = await session.get(SignalRow, signal_id)
            if row:
                row.resolve_attempts = (row.resolve_attempts or 0) + 1
                await session.commit()

    async def set_ai_note(self, signal_id: int, note: str) -> None:
        async with self._session() as session:
            row = await session.get(SignalRow, signal_id)
            if row:
                row.ai_note = note[:2000]
                await session.commit()

    async def resolve(self, signal_id: int, *, result: str, exit_price: float | None, status: str = "CLOSED") -> None:
        async with self._session() as session:
            row = await session.get(SignalRow, signal_id)
            if not row:
                return
            row.status = status
            row.result = result
            row.exit_price = exit_price
            row.resolved_at = int(time.time())
            await session.commit()

    async def statistics(self) -> dict:
        async with self._session() as session:
            total = int((await session.scalar(select(func.count()).select_from(SignalRow))) or 0)
            resolved = int(
                (
                    await session.scalar(
                        select(func.count())
                        .select_from(SignalRow)
                        .where(SignalRow.status == "CLOSED", SignalRow.result.in_(("WIN", "LOSS", "DRAW")))
                    )
                )
                or 0
            )
            rows = (
                await session.execute(
                    select(SignalRow.result, func.count())
                    .where(SignalRow.status == "CLOSED")
                    .group_by(SignalRow.result)
                )
            ).all()
        counts = {str(result or "UNKNOWN"): int(n) for result, n in rows}
        wins = counts.get("WIN", 0)
        losses = counts.get("LOSS", 0)
        draws = counts.get("DRAW", 0)
        decided = wins + losses
        open_count = total - resolved - (counts.get("UNVERIFIED", 0))
        return {
            "total": total,
            "resolved": resolved,
            "wins": wins,
            "losses": losses,
            "draws": draws,
            "unverified": counts.get("UNVERIFIED", 0),
            "open": max(0, open_count),
            "accuracy": round(wins / decided * 100, 1) if decided else None,
            "measured": bool(decided),
        }

    async def per_market_accuracy(self) -> list[dict]:
        async with self._session() as session:
            rows = (
                await session.execute(
                    select(SignalRow.market, SignalRow.result, func.count())
                    .where(SignalRow.status == "CLOSED")
                    .group_by(SignalRow.market, SignalRow.result)
                )
            ).all()
        buckets: dict[str, dict[str, int]] = {}
        for market, result, n in rows:
            buckets.setdefault(str(market), {})[str(result)] = int(n)
        out = []
        for market, counts in buckets.items():
            wins, losses = counts.get("WIN", 0), counts.get("LOSS", 0)
            decided = wins + losses
            out.append(
                {
                    "market": market,
                    "wins": wins,
                    "losses": losses,
                    "draws": counts.get("DRAW", 0),
                    "accuracy": round(wins / decided * 100, 1) if decided else None,
                }
            )
        return sorted(out, key=lambda r: r["market"])

    async def purge_open(self) -> int:
        """Mark abandoned OPEN signals as UNVERIFIED (never guessed as WIN)."""
        now = int(time.time())
        cutoff = now - 6 * 3600
        stmt = select(SignalRow).where(SignalRow.status == "OPEN", SignalRow.expires_at < cutoff)
        changed = 0
        async with self._session() as session:
            for row in (await session.scalars(stmt)).all():
                row.status = "CLOSED"
                row.result = "UNVERIFIED"
                row.resolved_at = now
                changed += 1
            if changed:
                await session.commit()
        return changed

    async def close(self) -> None:
        await self._engine.dispose()


def day_bounds(now: datetime | None = None) -> tuple[int, int]:
    now = now or datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())
