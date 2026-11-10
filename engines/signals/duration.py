"""AUTO duration selection from the live analysis, never a random value."""
from __future__ import annotations

from engines.technical.analyzer import AnalysisResult
from engines.signals.generator import supported_durations
from providers.catalog import Asset, Market, timeframe


def auto_frames(asset: Asset) -> tuple[str, ...]:
    if asset.market.is_expertoption:
        return ("1min", "5min")
    return ("5min", "15min")


def choose_auto_duration(result: AnalysisResult, asset: Asset) -> tuple[int | None, str]:
    if result.direction not in ("UP", "DOWN"):
        return None, "no actionable setup, so no duration was forced"
    allowed = supported_durations(asset, timeframe(result.timeframe))
    if not allowed:
        return None, "the source does not expose a supported expiry for this asset"
    volatility = str(result.indicators.get("volatility") or "NORMAL").upper()
    if volatility == "HIGH":
        target = min(allowed)
    elif volatility == "LOW":
        target = max(allowed)
    else:
        middle = (min(allowed) + max(allowed)) / 2
        target = min(allowed, key=lambda value: abs(value - middle))
    reason = (
        f"volatility {volatility} on {result.timeframe}, "
        f"momentum {result.momentum_strength}, evidence {result.confidence:.0f}%"
    )
    return target, reason
