"""Market profiles selected by the asset's own market."""
from __future__ import annotations

from engines.markets.ai_index import PROFILE as AI_PROFILE
from engines.markets.base import MarketProfile
from engines.markets.cricket import PROFILE as CRICKET_PROFILE
from engines.markets.football import PROFILE as FOOTBALL_PROFILE
from engines.markets.forex import PROFILE as FOREX_PROFILE
from engines.markets.luxury import PROFILE as LUXURY_PROFILE
from engines.markets.mt5 import PROFILE as MT5_PROFILE
from engines.markets.smarty import PROFILE as SMARTY_PROFILE
from providers.catalog import Market

_PROFILES: dict[Market, MarketProfile] = {
    profile.market: profile
    for profile in (
        SMARTY_PROFILE,
        FOOTBALL_PROFILE,
        LUXURY_PROFILE,
        AI_PROFILE,
        CRICKET_PROFILE,
        FOREX_PROFILE,
        MT5_PROFILE,
    )
}

GENERIC = MarketProfile(
    market=Market.GOLD,
    name="GOLD",
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
    family_weights={},
    mtf_strict=True,
    min_confidence=62.0,
    note="Generic fallback profile.",
)


def profile_for(market: Market) -> MarketProfile:
    return _PROFILES.get(market, GENERIC)
