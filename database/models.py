"""SQLAlchemy models for signals, verification and per-user settings."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    asset_key: Mapped[str] = mapped_column(String(32), index=True)
    asset_display: Mapped[str] = mapped_column(String(32))
    market: Mapped[str] = mapped_column(String(16))
    timeframe: Mapped[str] = mapped_column(String(16))
    direction: Mapped[str] = mapped_column(String(8))
    confidence: Mapped[float] = mapped_column(Float)
    entry_price: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(64))
    reasons: Mapped[str] = mapped_column(Text, default="[]")
    warnings: Mapped[str] = mapped_column(Text, default="[]")
    expiry_seconds: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE", index=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Signal {self.id} {self.asset_display} {self.direction} {self.status}>"


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    markets: Mapped[str] = mapped_column(Text, default='["FOREX"]')
    min_confidence: Mapped[float] = mapped_column(Float, default=65.0)
    scanner_enabled: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
