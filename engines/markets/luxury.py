"""Luxury Index (ExpertOption 286) rules."""
from __future__ import annotations

from engines.markets.base import MarketProfile
from providers.catalog import Market

PROFILE = MarketProfile(
    market=Market.LUXURY,
    name="LUXURY INDEX",
    frames=("30sec", "1min", "5min"),
    min_bars=90,
    adx_floor=18.0,
    min_separation=0.57,
    min_families=3,
    required_families=frozenset({"location", "structure"}),
    max_extension_atr=2.4,
    level_distance_atr=0.45,
    data_quality_floor=6,
    expiry_by_volatility={"LOW": 300, "NORMAL": 105, "HIGH": 60},
    family_weights={"trend": 1.0, "structure": 1.10, "location": 1.25,
                    "liquidity": 1.0, "momentum": 1.0, "price_action": 1.10},
    mtf_strict=True,
    allow_mean_reversion=True,
    min_confidence=64.0,
    note="Location-sensitive profile: entries need a verified level or FVG, not just trend.",
)
