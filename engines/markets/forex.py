"""Forex majors rules."""
from __future__ import annotations

from engines.markets.base import MarketProfile
from providers.catalog import Market

PROFILE = MarketProfile(
    market=Market.FOREX,
    name="FOREX",
    frames=("1min", "5min", "15min", "30min", "1h"),
    min_bars=120,
    adx_floor=20.0,
    min_separation=0.57,
    min_families=2,
    required_families=frozenset({"trend", "structure"}),
    max_extension_atr=2.4,
    level_distance_atr=0.35,
    data_quality_floor=6,
    expiry_by_volatility={"LOW": 900, "NORMAL": 300, "HIGH": 60},
    family_weights={"trend": 1.15, "structure": 1.10, "location": 1.0,
                    "liquidity": 1.0, "momentum": 1.05, "price_action": 1.0},
    mtf_strict=True,
    allow_mean_reversion=True,
    min_confidence=62.0,
    note="Session-aware trend profile: higher frames must agree before entry.",
)
