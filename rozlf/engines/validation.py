"""Data validation layer: every candle set passes through here before analysis."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..providers.base import Candle, DataUnavailable, now_ts

MIN_CANDLES = 60
MAX_GAP_RATIO = 0.2
FRESH_MULTIPLIER = 4


@dataclass
class ValidationReport:
    ok: bool
    code: str = "OK"
    detail: str = ""
    count: int = 0
    last_time: int | None = None
    age_seconds: int | None = None
    gaps: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def quality(self) -> str:
        if not self.ok:
            return "unusable"
        if self.warnings:
            return "degraded"
        return "good"


def validate_candles(
    candles: list[Candle],
    timeframe: int,
    *,
    min_count: int = MIN_CANDLES,
    now: int | None = None,
    require_fresh: bool = True,
) -> ValidationReport:
    now = now or now_ts()
    if not candles:
        return ValidationReport(False, "EMPTY", "لا توجد شموع من المصدر.")

    ordered = sorted(candles, key=lambda c: c.time)
    last = ordered[-1]
    age = max(0, now - last.time)

    for candle in ordered:
        if candle.time <= 0:
            return ValidationReport(False, "BAD_TIMESTAMP", "طابع زمني غير صالح في الشموع.", len(ordered))
        if candle.high < max(candle.open, candle.close) or candle.low > min(candle.open, candle.close):
            return ValidationReport(False, "BAD_OHLC", "شموع غير متسقة (high/low خارج النطاق).", len(ordered))
        if candle.low <= 0 or candle.high <= 0:
            return ValidationReport(False, "BAD_PRICE", "قيمة سعر غير صالحة في الشموع.", len(ordered))

    stamps = [c.time for c in ordered]
    if len(set(stamps)) != len(stamps):
        return ValidationReport(False, "DUPLICATE_TIME", "طوابع زمنية مكررة في الشموع.", len(ordered))

    if require_fresh and age > timeframe * FRESH_MULTIPLIER:
        return ValidationReport(
            False,
            "STALE",
            f"آخر شمعة عمرها {age} ثانية وهي أقدم من المسموح لهذا الفريم.",
            len(ordered),
            last.time,
            age,
        )

    gaps = 0
    for prev, cur in zip(ordered, ordered[1:]):
        if cur.time - prev.time > timeframe * 1.5:
            gaps += 1

    if len(ordered) < min_count:
        return ValidationReport(
            False,
            "TOO_FEW",
            f"عدد الشموع {len(ordered)} أقل من الحد المطلوب {min_count}.",
            len(ordered),
            last.time,
            age,
            gaps,
        )

    warnings: list[str] = []
    if gaps / max(1, len(ordered) - 1) > MAX_GAP_RATIO:
        warnings.append(f"فجوات زمنية في {gaps} موضعاً من البيانات.")
    if age > timeframe * 1.5:
        warnings.append(f"الشمعة الأخيرة عمرها {age} ثانية.")

    return ValidationReport(True, "OK", "بيانات صالحة.", len(ordered), last.time, age, gaps, warnings)


def require_valid(
    candles: list[Candle],
    timeframe: int,
    *,
    min_count: int = MIN_CANDLES,
    now: int | None = None,
) -> ValidationReport:
    report = validate_candles(candles, timeframe, min_count=min_count, now=now)
    if not report.ok:
        raise DataUnavailable(
            f"{report.detail} ({report.code})",
            code=report.code,
        )
    return report
