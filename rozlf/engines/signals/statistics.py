"""Measured statistics built only from resolved signals."""

from __future__ import annotations

from ...database.repository import SignalRepository


class StatisticsService:
    def __init__(self, repo: SignalRepository):
        self.repo = repo

    async def overview(self) -> dict:
        stats = await self.repo.statistics()
        stats["today"] = await self.repo.count_today()
        stats["per_market"] = await self.repo.per_market_accuracy()
        stats["streak"] = await self._streak()
        if stats["accuracy"] is None:
            stats["note"] = "لا توجد نتائج محسومة بعد — الدقة تُحسب فقط بعد انتهاء صلاحية الإشارات."
        return stats

    async def _streak(self) -> dict:
        rows = await self.repo.list(status="CLOSED", limit=50)
        ordered = [r for r in rows if r.result in ("WIN", "LOSS")]
        ordered.sort(key=lambda r: r.resolved_at or 0, reverse=True)
        kind = ordered[0].result if ordered else ""
        count = 0
        for row in ordered:
            if row.result != kind:
                break
            count += 1
        return {"kind": kind, "count": count}
