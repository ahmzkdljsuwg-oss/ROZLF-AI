"""AUTO duration selection from the live analysis, never a random value."""
from __future__ import annotations

from engines.markets import profile_for
from engines.technical.analyzer import AnalysisResult
from engines.signals.generator import supported_durations
from providers.catalog import TIMEFRAMES, Asset, Market, timeframe


def auto_frames(asset: Asset) -> tuple[str, ...]:
    profile = profile_for(asset.market)
    usable = [frame for frame in profile.frames if frame in TIMEFRAMES]
    preferred = [frame for frame in ("1min", "5min", "15min") if frame in usable]
    extras = [frame for frame in usable if frame not in preferred and frame != "5sec"]
    return tuple((preferred + extras)[:3])


def choose_auto_duration(result: AnalysisResult, asset: Asset) -> tuple[int | None, str]:
    if result.direction not in ("UP", "DOWN"):
        return None, "no actionable setup, so no duration was forced"
    allowed = supported_durations(asset, timeframe(result.timeframe))
    if not allowed:
        return None, "the source does not expose a supported expiry for this asset"
    volatility = str(result.indicators.get("volatility") or "NORMAL").upper()
    profile = profile_for(asset.market)
    preferred = profile.expiry_for(volatility, timeframe(result.timeframe).seconds)
    target = min(allowed, key=lambda value: abs(value - preferred))
    reason = (
        f"{profile.name} profile · volatility {volatility} on {result.timeframe}, "
        f"momentum {result.momentum_strength}, evidence {result.confidence:.0f}%"
    )
    return target, reason
