"""One automatic, market-isolated analysis for the NEXUS Telegram flow."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from ai.review import AIReviewer
from config import Settings
from engines.markets import profile_for
from engines.technical.analyzer import AnalysisResult, analyze_market_data
from engines.technical.next_candle import forecast_frames
from engines.technical.delivery_window import (
    PREPUBLISH_SECONDS, LATE_REASON, UNVERIFIED_SMARTY_REASON, can_publish, is_research_only,
)
from providers.base import DataUnavailable, utc_now
from providers.catalog import Asset, Market, assets_for, timeframe
from providers.registry import DataSourceRegistry

logger = logging.getLogger(__name__)

MAX_ASSETS = 8
NATIVE_FRAMES = ("5sec", "30sec", "1min", "2min", "3min", "5min")

def native_frame_plan(asset, mode):
    profile = tuple(f for f in profile_for(asset.market).frames if f in NATIVE_FRAMES)
    if mode == "pro":
        return forecast_frames(asset.market.value, tuple(f for f in profile if timeframe(f).seconds > PREPUBLISH_SECONDS))
    return tuple(f for f in NATIVE_FRAMES if f in profile and timeframe(f).seconds > PREPUBLISH_SECONDS)[:3]
FETCH_TIMEOUT = 18.0
ANALYSIS_TIMEOUT = 22.0
LO_BUDGET = 12.0
LO_FRAME_BUDGET = 6.0
FAST_BUDGET = 12.0
DEEP_BUDGET = 15.0


@dataclass(slots=True)
class MarketAnalysis:
    market: Market
    result: AnalysisResult | None = None
    duration_seconds: int | None = None
    duration_reason: str = ""
    errors: list[str] = field(default_factory=list)
    conflict: str | None = None
    attempted: int = 0
    fetched: int = 0

    @property
    def actionable(self) -> bool:
        return (
            self.result is not None
            and self.result.direction in ("UP", "DOWN")
            and self.duration_seconds is not None
            and self.conflict is None
        )


class MarketAnalysisService:
    def __init__(self, registry: DataSourceRegistry, settings: Settings, inventory=None,
                 gemini=None, mistral=None, mode: str = "strong") -> None:
        self.registry = registry
        self.settings = settings
        self.inventory = inventory
        self.mode = mode if mode in {"strict", "strong", "lo", "fast", "pro"} else "strong"
        self.reviewer = AIReviewer(gemini, mistral)

    async def assets_for(self, market: Market, asset_key: str | None = None) -> list[Asset]:
        if market in (Market.FOREX, Market.GOLD):
            assets = list(assets_for(market))
        elif self.inventory is not None:
            assets = list(await self.inventory.assets(market))
        else:
            assets = list(assets_for(market))
        return [asset for asset in assets if asset.market is market
                and (not asset_key or asset.key == asset_key)][:MAX_ASSETS]

    async def analyse(self, market: Market, asset_key: str | None = None) -> MarketAnalysis:
        started = time.monotonic()
        outcome = await self._analyse(market, asset_key)
        logger.info("NEXUS manual market=%s mode=%s frames=%d received=%d actionable=%s elapsed_ms=%d",
                    market.value, self.mode, outcome.attempted, outcome.fetched, outcome.actionable,
                    round((time.monotonic() - started) * 1000))
        return outcome

    async def _analyse(self, market: Market, asset_key: str | None) -> MarketAnalysis:
        outcome = MarketAnalysis(market=market)
        try:
            assets = await asyncio.wait_for(self.assets_for(market, asset_key), 5)
        except (DataUnavailable, TimeoutError) as exc:
            outcome.errors.append("تأخر دليل الأصول" if isinstance(exc, TimeoutError) else (exc.detail or exc.message))
            return outcome
        if not assets:
            outcome.errors.append(f"no verified {market.label} instruments")
            return outcome

        profile_frames = profile_for(market).frames
        if self.mode in {"fast", "pro"}:
            frames = native_frame_plan(assets[0], self.mode)
        elif self.mode == "lo" and market is Market.SMARTY:
            frames = tuple(f for f in ("30sec", "1min", "15sec") if f in profile_frames)
        elif self.mode == "lo":
            frames = profile_frames[:3]
        else:
            frames = forecast_frames(market.value, profile_frames)
        frames = tuple(f for f in frames if timeframe(f).seconds > PREPUBLISH_SECONDS)
        jobs = [(asset, frame) for asset in assets for frame in frames]
        semaphore = asyncio.Semaphore(4)
        results: list[tuple[AnalysisResult, str]] = []
        failure_codes: list[str] = []

        def collect(item) -> None:
            if isinstance(item, DataUnavailable):
                outcome.errors.append(item.detail or item.message)
                failure_codes.append(item.code)
            elif isinstance(item, Exception):
                outcome.errors.append(type(item).__name__)
                failure_codes.append(type(item).__name__)
            elif item is not None:
                results.append(item)

        timeout = LO_BUDGET if self.mode == "lo" else FAST_BUDGET if self.mode == "fast" else DEEP_BUDGET
        deadline = time.monotonic() + timeout
        if self.mode == "lo" and len(assets) == 1:
            # Avoid launching all frames for the same asset at once. For EO a
            # quote and sibling requests share the same socket as history; for
            # Forex they consume extra credits. Use the first timely direction.
            if market is Market.SMARTY and all(frame != "1min" for _, frame in jobs):
                jobs.append((assets[0], "1min"))
            for asset, frame in jobs:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                outcome.attempted += 1
                try:
                    slice_budget = min(LO_FRAME_BUDGET, remaining)
                    item = await asyncio.wait_for(self._one(asset, frame, semaphore), timeout=slice_budget)
                    collect(item)
                    if item and (self._timely(item[0]) or (
                        market is Market.SMARTY and self._current_reading(item[0])
                    )):
                        break
                except TimeoutError:
                    collect(DataUnavailable("TIMEOUT", "تأخر مصدر الشموع في الرد."))
                except DataUnavailable as exc:
                    collect(exc)
                    if exc.code in {"RATE_LIMITED", "INVALID_KEY", "INACTIVE_ASSET",
                                    "EO_BRIDGE_UNAUTHORIZED", "EO_BRIDGE_NOT_CONFIGURED", "TOKEN_INVALID"}:
                        break
        else:
            if market is Market.SMARTY and self.mode != "pro" and all(frame != "1min" for _, frame in jobs):
                jobs.append((assets[0], "1min"))
            outcome.attempted = len(jobs)
            tasks = [asyncio.create_task(self._one(a, f, semaphore)) for a, f in jobs]
            try:
                for task in asyncio.as_completed(tasks, timeout=timeout):
                    try:
                        item = await task
                        collect(item)
                        if self.mode == "fast" and item and (self._timely(item[0]) or (
                            market is Market.SMARTY and self._current_reading(item[0])
                        )):
                            break
                    except DataUnavailable as exc:
                        collect(exc)
            except TimeoutError:
                collect(DataUnavailable("TIMEOUT", "انتهت مهلة جلب أحدث الشموع"))
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        outcome.fetched = len(results)
        if not results:
            mark = getattr(self.registry, "mark_unavailable", None)
            if (mark is not None and len(assets) == 1 and market.is_expertoption and failure_codes
                    and all(code in {"INACTIVE_ASSET", "EO_BRIDGE_NOT_CONFIGURED", "EO_BRIDGE_UNAUTHORIZED"}
                            for code in failure_codes)):
                mark(assets[0])
            if not outcome.errors:
                outcome.errors.append("no verified candles were returned")
            return outcome

        actionable = [item for item in results if item[0].direction in ("UP", "DOWN")]
        if actionable:
            now = utc_now()
            usable = [item for item in actionable if can_publish(
                timeframe(item[1]).seconds, item[0].target_open_at, now)]
            if not usable:
                outcome.result = actionable[0][0]
                outcome.conflict = LATE_REASON
                return outcome
            if is_research_only(market, self.mode == "pro" and any(r.confidence_verified for r, _ in usable)):
                outcome.result = usable[0][0]
                outcome.conflict = UNVERIFIED_SMARTY_REASON
                return outcome
            actionable = usable
        if actionable:
            actionable.sort(key=lambda item: _strength(item[0], self.mode), reverse=True)
            best, frame = actionable[0]
            if self.mode in {"lo", "fast"}:
                opposing = [
                    other for other, _ in actionable[1:]
                    if other.asset_key == best.asset_key and other.timeframe == best.timeframe
                    and other.target_open_at == best.target_open_at
                    and other.direction != best.direction and _strength(other, "lo") >= 6.0
                ]
                if opposing and _strength(best, "lo") < 12.0:
                    outcome.result = best
                    outcome.conflict = (
                        f"{best.direction} on {frame} conflicts with "
                        f"{opposing[0].direction} on {opposing[0].timeframe}"
                    )
                    return outcome
            else:
                opposing = [
                    other for other, _ in actionable[1:]
                    if other.asset_key == best.asset_key
                    and other.direction != best.direction
                    and other.confidence >= max(52.0, best.confidence - 8.0)
                ]
                if opposing:
                    outcome.result = best
                    outcome.conflict = (
                        f"{best.direction} {best.confidence:.0f}% on {frame} conflicts with "
                        f"{opposing[0].direction} {opposing[0].confidence:.0f}% on "
                        f"{opposing[0].timeframe}"
                    )
                    return outcome
            duration = timeframe(best.timeframe).seconds
            if self.mode in {"lo", "fast"}:
                reason = (
                    f"target candle {best.timeframe} chosen from live technical components; "
                    "confidence is UNVERIFIED (no walk-forward calibration)"
                )
            else:
                reason = (
                    f"target candle {best.timeframe} chosen because its walk-forward "
                    f"hit rate passed the gate; confidence {best.confidence:.0f}%"
                )
            minimum = (self.settings.min_confidence if self.mode == "pro"
                       else max(52.0, self.settings.min_confidence - 8.0))
            passes = self.mode in {"lo", "fast"} or best.confidence >= minimum
            if duration is not None and passes:
                outcome.result = best
                outcome.duration_seconds = duration
                outcome.duration_reason = reason
                # LO is a fast, explicitly unverified technical mode. External AI
                # reviewers can rate-limit (429) and delay the target candle.
                # Keep the independent AI veto for calibrated/strong mode only.
                review_budget = min(2.0, (best.target_open_at - utc_now()).total_seconds() - PREPUBLISH_SECONDS)
                if self.mode not in {"lo", "fast"} and review_budget >= 0.15 and self.reviewer.configured():
                    try:
                        review = await asyncio.wait_for(self.reviewer.review(
                            best.direction, _review_payload(best, duration, reason)
                        ), timeout=review_budget)
                    except TimeoutError:
                        review = None
                    if review and review.conflict:
                        outcome.conflict = review.conflict
                        return outcome
                    if review and review.verdicts:
                        best.reasons.append(
                            "AI review confirmed by " + ", ".join(v.model for v in review.verdicts)
                        )
                if not can_publish(duration, best.target_open_at, utc_now()):
                    outcome.conflict = LATE_REASON
                    outcome.duration_seconds = None
                return outcome
            outcome.errors.append("best setup did not pass the confidence or duration filter")
        results.sort(key=lambda item: item[0].confidence, reverse=True)
        outcome.result = results[0][0]
        return outcome

    @staticmethod
    def _timely(result: AnalysisResult) -> bool:
        return (result.direction in ("UP", "DOWN") and
                can_publish(timeframe(result.timeframe).seconds, result.target_open_at, utc_now()))

    @staticmethod
    def _current_reading(result: AnalysisResult) -> bool:
        return result.target_open_at is not None and result.target_open_at > utc_now()

    async def _one(self, asset: Asset, frame: str, semaphore: asyncio.Semaphore):
        async with semaphore:
            try:
                data = await asyncio.wait_for(
                    self.registry.fetch(asset, timeframe(frame), with_quote=False), timeout=FETCH_TIMEOUT
                )
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        analyze_market_data, data, None, None, self.mode, live_candle_target=True
                    ),
                    timeout=ANALYSIS_TIMEOUT,
                )
                return result, frame
            except DataUnavailable as exc:
                logger.info("NEXUS analysis skipped %s %s: %s", asset.key, frame, exc.code)
                raise
            except asyncio.TimeoutError as exc:
                raise DataUnavailable("TIMEOUT", "تأخر مصدر الشموع في الرد.") from exc
            except Exception:
                logger.exception("NEXUS analysis failed for %s %s", asset.key, frame)
                return None


def _strength(result: AnalysisResult, mode: str) -> float:
    if mode != "lo":
        return result.confidence
    raw = result.next_candle.get("raw_score") if result.next_candle else None
    return abs(float(raw)) if isinstance(raw, (int, float)) else result.evidence_score


def _review_payload(result: AnalysisResult, duration: int, reason: str) -> dict:
    indicators = {
        key: result.indicators.get(key)
        for key in (
            "close", "trend", "rsi", "macd", "macd_signal", "macd_hist",
            "ema9", "ema21", "ema50", "ema200", "sma50", "atr", "bb_upper",
            "bb_middle", "bb_lower", "stoch_k", "stoch_d", "adx",
        )
        if key in result.indicators
    }
    return {
        "asset": result.asset_display,
        "market": result.market,
        "timeframe": result.timeframe,
        "technical_decision": result.direction,
        "confidence": result.confidence,
        "entry_price": result.price,
        "closed_candles": result.closed_candles,
        "current_candle": result.current_candle,
        "indicators": indicators,
        "smc": result.smc,
        "alligator_ma": result.alligator_ma,
        "confirmed_strategies": result.confirmed_strategies,
        "opposing_strategies": result.opposing_strategies,
        "reasons": result.reasons,
        "warnings": result.warnings,
        "blockers": result.blockers,
        "auto_duration_seconds": duration,
        "duration_reason": reason,
        "source": result.source,
    }
