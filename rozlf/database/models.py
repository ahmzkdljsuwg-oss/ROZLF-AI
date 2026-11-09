"""Database models."""

from __future__ import annotations

import time

from sqlalchemy import BigInteger, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _now() -> int:
    return int(time.time())


class SignalRow(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    market: Mapped[str] = mapped_column(String(12), index=True)
    direction: Mapped[str] = mapped_column(String(8))
    timeframe: Mapped[int] = mapped_column(Integer)
    expiry_seconds: Mapped[int] = mapped_column(Integer)
    entry: Mapped[float] = mapped_column(Float)
    stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    target: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(32), default="")
    reasons: Mapped[str] = mapped_column(Text, default="")
    warnings: Mapped[str] = mapped_column(Text, default="")
    ai_note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    result: Mapped[str] = mapped_column(String(12), default="")
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=_now, index=True)
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True, default=_now)
    resolved_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resolve_attempts: Mapped[int] = mapped_column(Integer, default=0)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "market": self.market,
            "direction": self.direction,
            "timeframe": self.timeframe,
            "expiry_seconds": self.expiry_seconds,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "score": self.score,
            "source": self.source,
            "reasons": [r for r in (self.reasons or "").split("\n") if r],
            "warnings": [w for w in (self.warnings or "").split("\n") if w],
            "ai_note": self.ai_note,
            "status": self.status,
            "result": self.result,
            "exit_price": self.exit_price,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "resolved_at": self.resolved_at,
            "resolve_attempts": self.resolve_attempts,
        }
