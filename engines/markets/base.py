"""Per-market analysis profiles.

Every market keeps its own entry requirements, trend/volatility filters,
supported frames and expiry map. The indicator maths is shared, but a market
cannot be traded with another market's rule set.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from providers.catalog import Market


@dataclass(frozen=True, slots=True)
class MarketProfile:
    market: Market
    name: str
    frames: tuple[str, ...]
    min_bars: int
    adx_floor: float
    min_separation: float
    min_families: int
    required_families: frozenset[str]
    max_extension_atr: float
    level_distance_atr: float
    data_quality_floor: int
    expiry_by_volatility: dict[str, int]
    family_weights: dict[str, float] = field(default_factory=dict)
    mtf_strict: bool = True
    allow_mean_reversion: bool = True
    min_confidence: float = 60.0
    note: str = ""

    def weight(self, family: str) -> float:
        return self.family_weights.get(family, 1.0)

    def expiry_for(self, volatility: str, frame_seconds: int) -> int:
        return self.expiry_by_volatility.get(volatility.upper(), frame_seconds)
