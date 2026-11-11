"""Cricket Index (ExpertOption 276) rules."""
from __future__ import annotations

from engines.markets.base import MarketProfile
from providers.catalog import Market

PROFILE = MarketProfile(
    market=Market.CRICKET,
    name="CRICKET INDEX",
    frames=("30sec", "1min", "5min"),
    min_bars=90,
    adx_floor=22.0,
    min_separation=0.60,
    min_families=3,
    required_families=frozenset({"structure", "liquidity"}),
    max_extension_atr=1.8,
    level_distance_atr=0.45,
    data_quality_floor=9,
    expiry_by_volatility={"LOW": 105, "NORMAL": 60, "HIGH": 30},
    family_weights={"trend": 1.0, "structure": 1.20, "location": 1.0,
                    "liquidity": 1.20, "momentum": 1.05, "price_action": 1.0},
    mtf_strict=True,
    allow_mean_reversion=False,
    min_confidence=66.0,
    note="Thin/event-driven index: requires HIGH data quality and a liquidity reaction.",
)
