"""One automatic, market-isolated analysis for the NEXUS Telegram flow."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from ai.review import AIReviewer
from config import Settings
from engines.markets import profile_for
from engines.technical.analyzer import AnalysisResult, analyze_market_data
from engines.technical.next_candle import forecast_frames
from providers.base import DataUnavailable, utc_now
from providers.catalog import Asset, Market, assets_for, timeframe
from providers.registry import DataSourceRegistry

logger = logging.getLogger(__name__)

MAX_ASSETS = 8
NATIVE_FRAMES = ("5sec", "30sec", "1min", "2min", "3min", "5min")

def native_frame_plan(asset, mode):
    profile = tuple(f for f in profile_for(asset.market).frames if f in NATIVE_FRAMES)
    if mode == "pro":
        return forecast_frames(asset.market.value, profile)
    return tuple(f for f in NATIVE_FRAMES if f in profile)[:3]
FETCH_TIMEOUT = 18.0
ANALYSIS_TIMEOUT = 22.0


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
        if asset_key:
            assets = [asset for asset in assets if asset.key == asset_key]
        return assets[:MAX_ASSETS]

    async def analyse(self, market: Market, asset_key: str | None = None) -> MarketAnalysis:
        outcome = MarketAnalysis(market=market)
        try:
            assets = await asyncio.wait_for(self.assets_for(market, asset_key), 5)
        except (DataUnavailable, TimeoutError) as exc:
            outcome.errors.append("تأخر دليل الأصول" if isinstance(exc, TimeoutError) else (exc.detail or exc.message))
            return outcome
        if not assets:
            outcome.errors.append(f"no verified {market.label} instruments")
            return outcome

        jobs: list[tuple[Asset, str]] = []
        for asset in assets:
            profile_frames = profile_for(asset.market).frames
            frames = (tuple(profile_frames[:3]) if self.mode == "lo"
                      else forecast_frames(asset.market.value, profile_frames))
            if self.mode in {"fast", "pro"}:
                frames = native_frame_plan(asset, self.mode)
            for frame in frames:
                jobs.append((asset, frame))
        semaphore = asyncio.Semaphore(4)
        results: list[tuple[AnalysisResult, str]] = []

        def collect(item) -> None:
            if isinstance(item, DataUnavailable):
                outcome.errors.append(item.detail or item.message)
            elif isinstance(item, Exception):
                outcome.errors.append(type(item).__name__)
            elif item is not None:
                results.append(item)

        if self.mode in {"fast", "pro"}:
            outcome.attempted = len(jobs)
            tasks = [asyncio.create_task(self._one(a, f, semaphore)) for a, f in jobs]
            try:
                for task in asyncio.as_completed(tasks, timeout=12 if self.mode == "fast" else 18):
                    try:
                        item = await task
                        collect(item)
                        if self.mode == "fast" and item is not None and self._timely(item[0]):
                            break
                    except DataUnavailable as exc:
                        collect(exc)
            except TimeoutError:
                outcome.errors.append("انتهت مهلة جلب أحدث الشموع")
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        elif self.mode == "lo" and len(assets) == 1:
            # Avoid launching all frames for the same asset at once. For EO a
            # quote and sibling requests share the same socket as history; for
            # Forex they consume extra credits. Use the first timely direction.
            if market is Market.SMARTY and all(frame != "1min" for _, frame in jobs):
                jobs.append((assets[0], "1min"))
            for asset, frame in jobs:
                outcome.attempted += 1
                try:
                    collect(await self._one(asset, frame, semaphore))
                except DataUnavailable as exc:
                    collect(exc)
                    if exc.code in {"RATE_LIMITED", "INVALID_KEY", "INACTIVE_ASSET",
                                    "EO_BRIDGE_UNAUTHORIZED", "EO_BRIDGE_NOT_CONFIGURED", "TOKEN_INVALID"}:
                        break
                if results and self._timely(results[-1][0]):
                    break
        else:
            outcome.attempted = len(jobs)
            gathered = await asyncio.gather(
                *(self._one(asset, frame, semaphore) for asset, frame in jobs),
                return_exceptions=True,
            )
            for item in gathered:
                collect(item)
            if not results and market is Market.SMARTY and all(frame != "1min" for _, frame in jobs):
                outcome.attempted += 1
                try:
                    collect(await self._one(assets[0], "1min", semaphore))
                except DataUnavailable as exc:
                    collect(exc)
        outcome.fetched = len(results)
        if not results:
            mark = getattr(self.registry, "mark_unavailable", None)
            if mark is not None and len(assets) == 1 and market.is_expertoption:
                mark(assets[0])
            if not outcome.errors:
                outcome.errors.append("no verified candles were returned")
            return outcome

        actionable = [item for item in results if item[0].direction in ("UP", "DOWN")]
        if (market is Market.SMARTY or self.mode in {"lo", "fast", "pro"}) and actionable:
            now = utc_now()
            usable = [item for item in actionable
                      if item[0].target_open_at is not None and item[0].target_open_at > now]
            if not usable:
                outcome.result = actionable[0][0]
                outcome.conflict = "بدأت الشمعة المستهدفة قبل اكتمال التحليل"
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
                    if (self.mode != "pro" or other.asset_key == best.asset_key)
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
                if self.mode not in {"lo", "fast"} and self.reviewer.configured():
                    try:
                        review = await asyncio.wait_for(self.reviewer.review(
                            best.direction, _review_payload(best, duration, reason)
                        ), timeout=2)
                    except TimeoutError:
                        review = None
                    if review and review.conflict:
                        outcome.conflict = review.conflict
                        return outcome
                    if review and review.verdicts:
                        best.reasons.append(
                            "AI review confirmed by " + ", ".join(v.model for v in review.verdicts)
                        )
                if (market is Market.SMARTY or self.mode in {"lo", "fast", "pro"}) and best.target_open_at is not None and best.target_open_at <= utc_now():
                    outcome.conflict = "بدأت الشمعة المستهدفة قبل اكتمال التحليل"
                    outcome.duration_seconds = None
                return outcome
            outcome.errors.append("best setup did not pass the confidence or duration filter")
        results.sort(key=lambda item: item[0].confidence, reverse=True)
        outcome.result = results[0][0]
        return outcome

    @staticmethod
    def _timely(result: AnalysisResult) -> bool:
        return (result.direction in ("UP", "DOWN") and result.target_open_at is not None
                and result.target_open_at > utc_now())

    async def _one(self, asset: Asset, frame: str, semaphore: asyncio.Semaphore):
        async with semaphore:
            try:
                data = await asyncio.wait_for(
                    self.registry.fetch(asset, timeframe(frame), with_quote=self.mode not in {"lo", "fast", "pro"}), timeout=FETCH_TIMEOUT
                )
                result = await asyncio.wait_for(
                    asyncio.to_thread(
                        analyze_market_data, data, None, None, self.mode
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
