"""Orchestrates analysis -> persistence -> notification, and expiry resolution."""

from __future__ import annotations

import logging
import time

from ..ai.mistral import AIResult, MistralClient
from ..database.repository import SignalRepository
from ..engines.signals.generator import RiskPolicy, SignalDraft, SignalRejected, persist_signal
from ..engines.signals.scanner import ScanResult, SignalScanner
from ..engines.signals.tracker import SignalTracker
from ..engines.technical.analyzer import NO_TRADE, SignalScore, analyze
from ..engines.validation import ValidationReport
from ..providers.base import Asset, Candle, DataUnavailable
from ..providers.registry import DataSourceRegistry
from .charts import render_result_chart, render_signal_chart
from .notifier import TelegramNotifier

log = logging.getLogger(__name__)


class SignalService:
    def __init__(
        self,
        registry: DataSourceRegistry,
        repo: SignalRepository,
        scanner: SignalScanner,
        tracker: SignalTracker,
        ai: MistralClient,
        policy: RiskPolicy,
    ):
        self.registry = registry
        self.repo = repo
        self.scanner = scanner
        self.tracker = tracker
        self.ai = ai
        self.policy = policy
        self.notifier = TelegramNotifier(None, "")
        self.last_scan_at = 0

    # ---- single asset analysis -------------------------------------------------
    async def analyze(self, symbol: str, timeframe: int) -> dict:
        asset = self.registry.asset(symbol)
        candles, report = await self.registry.candles(asset, timeframe, limit=220)
        cross = await self.registry.cross_check(asset, candles[-1])
        spread = cross.get("spread") if cross.get("checked") else None
        analysis = analyze(
            candles,
            timeframe,
            min_score=self.policy.min_score,
            validation=report,
            spread=spread,
        )
        return {
            "asset": asset,
            "candles": candles,
            "report": report,
            "cross": cross,
            "analysis": analysis,
            "timeframe": timeframe,
        }

    async def ai_comment(self, draft: SignalDraft) -> AIResult:
        a = draft.analysis
        context = {
            "symbol": draft.asset.symbol,
            "market": draft.asset.market,
            "timeframe": draft.timeframe,
            "direction": a.direction,
            "score": a.score,
            "price": a.entry,
            "atr": (a.snapshot or {}).get("atr"),
            "rsi": (a.snapshot or {}).get("rsi"),
            "macd_hist": (a.snapshot or {}).get("macd_hist"),
            "trend": (a.smc or {}).get("structure"),
            "bos": str(((a.smc or {}).get("structure") or {}).get("bos") or "NONE"),
            "choch": str(((a.smc or {}).get("structure") or {}).get("choch") or "NONE"),
            "zone": (a.snapshot or {}).get("zone"),
            "reasons": a.reasons,
            "warnings": a.warnings,
        }
        return await self.ai.analyze_signal(context)

    async def publish(self, draft: SignalDraft, *, notify: bool = True) -> dict | None:
        try:
            row = await persist_signal(self.repo, draft, self.policy)
        except SignalRejected as exc:
            log.info("signal rejected (%s): %s", exc.code, exc.detail)
            return None

        ai_result = await self.ai_comment(draft)
        ai_note, ai_state = _ai_text(ai_result)
        chart = render_signal_chart(
            draft.candles,
            symbol=draft.asset.symbol,
            timeframe_label=draft.timeframe_label,
            direction=draft.analysis.direction,
            entry=draft.analysis.entry,
            stop=draft.analysis.stop,
            target=draft.analysis.target,
            score=draft.analysis.score,
        ) if draft.candles else None
        if ai_note:
            await self.repo.set_ai_note(row.id, ai_note)
        if notify:
            await self.notifier.send_signal(draft, row.id, chart, ai_note, ai_state)
        return row.as_dict()

    # ---- scanner ---------------------------------------------------------------
    async def run_scan(self, market: str | None = None) -> list[ScanResult]:
        self.last_scan_at = int(time.time())
        if market:
            return [await self.scanner.scan_market(market)]
        return await self.scanner.scan_all()

    async def scan_and_publish(self, market: str | None = None) -> dict:
        results = await self.run_scan(market)
        published: list[dict] = []
        for result in results:
            for draft in result.signals:
                row = await self.publish(draft)
                if row:
                    published.append(row)
        return {
            "results": [r.as_dict() for r in results],
            "published": published,
        }

    # ---- resolution ------------------------------------------------------------
    async def resolve_due(self) -> list[dict]:
        resolved: list[dict] = []
        for payload in await self.tracker.resolve_due():
            resolved.append(payload)
            await self.notifier.send_result(payload, self._result_chart(payload))
        return resolved

    def _result_chart(self, payload: dict) -> bytes | None:
        candles = payload.get("candles") or []
        if not candles:
            return None
        return render_result_chart(
            candles,
            symbol=payload["symbol"],
            direction=payload["direction"],
            entry=payload["entry"],
            exit_price=payload.get("exit"),
            result=payload["result"],
        )


def _ai_text(result: AIResult) -> tuple[str, str]:
    if result.ok and result.data:
        data = result.data
        bias = str(data.get("bias") or "").upper()
        confidence = data.get("confidence")
        summary = str(data.get("summary") or "").strip()
        risks = [str(r) for r in (data.get("risks") or []) if str(r).strip()][:3]
        note = summary
        if risks:
            note += "\n" + "\n".join(f"• {r}" for r in risks)
        state = f"bias {bias or '—'} · ثقة {confidence if confidence is not None else '—'} · {result.model}"
        return note.strip(), state
    if result.ok:
        return result.text[:600], f"نص حر · {result.model}"
    return "", f"غير متاح ({result.code}) — التحليل الفني المحلي فقط، وليس تحليل Mistral"
