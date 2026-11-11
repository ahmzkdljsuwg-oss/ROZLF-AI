"""AI Index (ExpertOption 285) rules."""
from __future__ import annotations

from engines.markets.base import MarketProfile
from providers.catalog import Market

PROFILE = MarketProfile(
    market=Market.AI,
    name="AI INDEX",
    frames=("30sec", "1min", "5min"),
    min_bars=90,
    adx_floor=20.0,
    min_separation=0.58,
    min_families=3,
    required_families=frozenset({"momentum", "structure"}),
    max_extension_atr=1.9,
    level_distance_atr=0.40,
    data_quality_floor=6,
    expiry_by_volatility={"LOW": 105, "NORMAL": 60, "HIGH": 30},
    family_weights={"trend": 1.0, "structure": 1.15, "location": 0.95,
                    "liquidity": 1.0, "momentum": 1.30, "price_action": 1.0},
    mtf_strict=True,
    allow_mean_reversion=False,
    min_confidence=64.0,
    note="Momentum regime: MACD/ADX expansion must confirm the structural break.",
)
