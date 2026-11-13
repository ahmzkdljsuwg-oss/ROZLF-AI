"""MetaTrader 5 FX profile: Alligator + MA 200 with higher-frame agreement."""
from __future__ import annotations

from engines.markets.base import MarketProfile
from providers.catalog import Market

PROFILE = MarketProfile(
    market=Market.MT5,
    name="MT5",
    frames=("1min", "5min", "15min", "30min", "1h"),
    min_bars=200,
    adx_floor=20.0,
    min_separation=0.57,
    min_families=2,
    required_families=frozenset({"trend", "structure"}),
    max_extension_atr=2.4,
    level_distance_atr=0.35,
    data_quality_floor=6,
    expiry_by_volatility={"LOW": 1800, "NORMAL": 900, "HIGH": 300},
    family_weights={"trend": 1.20, "structure": 1.15, "location": 1.0,
                    "liquidity": 1.0, "momentum": 1.0, "price_action": 1.05},
    mtf_strict=True,
    allow_mean_reversion=True,
    min_confidence=62.0,
    note="MT5 trend profile: Alligator and MA 200 must agree before entry.",
)
