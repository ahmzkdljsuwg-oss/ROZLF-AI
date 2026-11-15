"""Automatic Gemini + Mistral review of the technical analysis.

Both models receive the same computed evidence. Any configured model that
disagrees blocks the recommendation; a model that is unavailable is simply
recorded as unavailable and never blocks with invented text.
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field

from ai.gemini import GeminiUnavailable
from ai.mistral import MistralUnavailable

_JSON_RE = re.compile(r"\{.*\}", re.S)
_VERDICT_RE = re.compile(r"\b(NO\s*TRADE|DOWN|UP)\b", re.I)


@dataclass(slots=True)
class ReviewVerdict:
    model: str
    decision: str
    confidence: float | None
    reason: str = ""


@dataclass(slots=True)
class ReviewOutcome:
    verdicts: list[ReviewVerdict] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    conflict: str | None = None

    @property
    def confirmed(self) -> bool:
        return bool(self.verdicts) and self.conflict is None


def parse_verdict(model: str, text: str) -> ReviewVerdict | None:
    decision = ""
    confidence: float | None = None
    reason = ""
    match = _JSON_RE.search(text or "")
    if match:
        try:
            data = json.loads(match.group(0))
            decision = str(data.get("decision", "")).upper().replace("_", " ")
            raw_conf = data.get("confidence")
            if isinstance(raw_conf, (int, float)):
                confidence = float(raw_conf)
            reason = str(data.get("reason", ""))[:300]
        except (ValueError, TypeError):
            decision = ""
    if decision not in {"UP", "DOWN", "NO TRADE"}:
        found = _VERDICT_RE.search(text or "")
        decision = found.group(1).upper().replace("_", " ") if found else ""
    if decision not in {"UP", "DOWN", "NO TRADE"}:
        return None
    if decision == "NO TRADE":
        decision = "NO TRADE"
    if confidence is not None:
        confidence = max(0.0, min(100.0, confidence))
    return ReviewVerdict(model=model, decision=decision, confidence=confidence, reason=reason)


class AIReviewer:
    def __init__(self, gemini=None, mistral=None, timeout: float = 18.0) -> None:
        self.gemini = gemini
        self.mistral = mistral
        self.timeout = timeout

    def configured(self) -> bool:
        return bool(
            getattr(self.gemini, "configured", False)
            or getattr(self.mistral, "configured", False)
        )

    async def review(self, technical_direction: str, payload: dict) -> ReviewOutcome:
        outcome = ReviewOutcome()
        jobs = []
        if getattr(self.gemini, "configured", False):
            jobs.append(("Gemini", self.gemini.analyse_setup(payload)))
        if getattr(self.mistral, "configured", False):
            jobs.append(("Mistral", self.mistral.analyse_setup(payload)))
        if not jobs:
            return outcome

        names = [name for name, _ in jobs]
        settled = await asyncio.gather(*(job for _, job in jobs), return_exceptions=True)
        for name, item in zip(names, settled):
            if isinstance(item, (GeminiUnavailable, MistralUnavailable)):
                outcome.unavailable.append(name)
                continue
            if isinstance(item, Exception):
                outcome.unavailable.append(name)
                continue
            verdict = parse_verdict(name, item)
            if verdict is None:
                outcome.unavailable.append(name)
            else:
                outcome.verdicts.append(verdict)

        opposing = [
            verdict for verdict in outcome.verdicts
            if verdict.decision != technical_direction
        ]
        if opposing:
            detail = ", ".join(
                f"{v.model}={v.decision}" + (f" {v.confidence:.0f}%" if v.confidence is not None else "")
                for v in outcome.verdicts
            )
            outcome.conflict = (
                f"technical={technical_direction}; AI review {detail}"
            )
        return outcome
