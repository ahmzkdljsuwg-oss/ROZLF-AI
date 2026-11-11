"""Football Index (ExpertOption 278) rules."""
from __future__ import annotations

from engines.markets.base import MarketProfile
from providers.catalog import Market

PROFILE = MarketProfile(
    market=Market.FOOTBALL,
    name="FOOTBALL INDEX",
    frames=("30sec", "1min", "5min"),
    min_bars=90,
    adx_floor=18.0,
    min_separation=0.56,
    min_families=2,
    required_families=frozenset({"trend", "structure"}),
    max_extension_atr=2.4,
    level_distance_atr=0.35,
    data_quality_floor=6,
    expiry_by_volatility={"LOW": 300, "NORMAL": 105, "HIGH": 60},
    family_weights={"trend": 1.20, "structure": 1.10, "location": 1.0,
                    "liquidity": 1.0, "momentum": 1.05, "price_action": 1.0},
    mtf_strict=True,
    allow_mean_reversion=False,
    min_confidence=62.0,
    note="Trend continuation profile: EMA/ADX alignment carries more weight than mean reversion.",
)
