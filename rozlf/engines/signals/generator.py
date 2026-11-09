"""Signal generation, expiry selection and persistence."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from ...database.repository import SignalRepository
from ..technical.analyzer import NO_TRADE, SignalScore
from ...providers.base import Asset, Candle
from ...providers.catalog import timeframe_label

ALLOWED_EXPIRIES: tuple[int, ...] = (30, 60, 120, 180, 300, 900, 1800, 3600)


def choose_expiry(timeframe: int) -> int:
    """Smallest supported expiration that still covers the analysis timeframe."""
    for expiry in ALLOWED_EXPIRIES:
        if expiry >= timeframe:
            return expiry
    return ALLOWED_EXPIRIES[-1]


@dataclass
class RiskPolicy:
    min_score: int = 62
    cooldown_minutes: int = 45
    max_per_day: int = 40
    max_per_scan: int = 3


@dataclass
class SignalDraft:
    asset: Asset
    timeframe: int
    analysis: SignalScore
    source: str
    validation_quality: str = "good"
    cross: dict | None = None
    ai_note: str = ""
    candles: list[Candle] = field(default_factory=list)

    @property
    def expiry(self) -> int:
        return choose_expiry(self.timeframe)

    @property
    def timeframe_label(self) -> str:
        return timeframe_label(self.timeframe)

    def reasons_text(self) -> str:
        return "\n".join(self.analysis.reasons[:12])

    def warnings_text(self) -> str:
        warnings = list(self.analysis.warnings)
        if self.validation_quality != "good":
            warnings.append(f"جودة البيانات: {self.validation_quality}.")
        if self.cross and self.cross.get("checked") and not self.cross.get("consistent", True):
            warnings.append("سعر السوق الحي بعيد عن إغلاق الشمعة.")
        return "\n".join(warnings[:10])


class SignalRejected(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


async def persist_signal(
    repo: SignalRepository,
    draft: SignalDraft,
    policy: RiskPolicy,
    *,
    now: int | None = None,
) -> object:
    now = now or int(time.time())
    analysis = draft.analysis
    if analysis.direction == NO_TRADE:
        raise SignalRejected("NO_TRADE", "التحليل لا يسمح بالدخول.")
    if analysis.score < policy.min_score:
        raise SignalRejected("LOW_SCORE", f"الدرجة {analysis.score} أقل من {policy.min_score}.")
    if analysis.entry is None:
        raise SignalRejected("NO_ENTRY", "لا يوجد سعر دخول صالح.")

    if await repo.recent_duplicate(
        draft.asset.symbol, analysis.direction, draft.timeframe, policy.cooldown_minutes * 60
    ):
        raise SignalRejected("DUPLICATE", "توجد إشارة مشابهة حديثاً لنفس الأصل والاتجاه والفريم.")

    today_count = await repo.count_today()
    if today_count >= policy.max_per_day:
        raise SignalRejected("DAILY_LIMIT", f"تم بلوغ الحد اليومي {policy.max_per_day} إشارة.")

    return await repo.add(
        symbol=draft.asset.symbol,
        market=draft.asset.market,
        direction=analysis.direction,
        timeframe=draft.timeframe,
        expiry_seconds=draft.expiry,
        entry=float(analysis.entry),
        stop=float(analysis.stop) if analysis.stop else None,
        target=float(analysis.target) if analysis.target else None,
        score=int(analysis.score),
        source=draft.source,
        reasons=draft.reasons_text(),
        warnings=draft.warnings_text(),
        ai_note=draft.ai_note,
        status="OPEN",
        created_at=now,
        expires_at=now + draft.expiry,
    )


def summary_line(row) -> str:
    return (
        f"#{row.id} {row.symbol} {row.market} {row.direction} "
        f"{timeframe_label(row.timeframe)} → {row.expiry_seconds}s · score {row.score}"
    )
