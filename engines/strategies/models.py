"""Strategy results carry entry logic, invalidation and their evidence family."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True, slots=True)
class StrategySignal:
    name: str
    family: str
    direction: str  # UP | DOWN | NEUTRAL
    score: float
    reason: str
    invalidation: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class StrategyReport:
    signals: list[StrategySignal] = field(default_factory=list)
    mtf: dict = field(default_factory=dict)
    session: str = "NONE"
    context: dict = field(default_factory=dict)

    @property
    def actionable(self) -> list[StrategySignal]:
        return [item for item in self.signals if item.direction in ("UP", "DOWN") and item.score > 0]

    def confirmed(self, direction: str) -> list[StrategySignal]:
        return sorted(
            (item for item in self.actionable if item.direction == direction),
            key=lambda item: -item.score,
        )

    def opposed(self, direction: str) -> list[StrategySignal]:
        return sorted(
            (item for item in self.actionable if item.direction != direction),
            key=lambda item: -item.score,
        )
