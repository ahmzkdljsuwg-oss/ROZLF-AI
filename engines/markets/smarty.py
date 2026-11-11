"""SMARTY (ExpertOption synthetic index 240) rules."""
from __future__ import annotations

from engines.markets.base import MarketProfile
from providers.catalog import Market

PROFILE = MarketProfile(
    market=Market.SMARTY,
    name="SMARTY",
    frames=("5sec", "15sec", "30sec", "1min", "5min"),
    min_bars=90,
    adx_floor=20.0,
    min_separation=0.60,
    min_families=2,
    required_families=frozenset({"momentum", "structure"}),
    max_extension_atr=1.8,
    level_distance_atr=0.40,
    data_quality_floor=6,
    expiry_by_volatility={"LOW": 60, "NORMAL": 30, "HIGH": 15},
    family_weights={"trend": 0.95, "structure": 1.15, "location": 0.85,
                    "liquidity": 1.10, "momentum": 1.25, "price_action": 1.0},
    mtf_strict=True,
    allow_mean_reversion=False,
    min_confidence=62.0,
    note="Fast synthetic feed: momentum and structure must agree; late entries refused.",
)
