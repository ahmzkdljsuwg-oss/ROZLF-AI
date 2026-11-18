"""Separate forecast time from the time left for a human to see it."""
from datetime import datetime, timedelta

from providers.catalog import Market

PREPUBLISH_SECONDS = 8
ACKNOWLEDGED_SECONDS = 5
SHORT_FRAME_REASON = "الفريم أقصر من مهلة العرض اللازمة. الشموع معروضة للقراءة فقط."
LATE_REASON = "الوقت المتبقي قبل فتح الشمعة غير كافٍ؛ ما نعرض إشارة متأخرة."
UNVERIFIED_SMARTY_REASON = "اختبار SMARTY التاريخي لم يثبت دقة التوقع. هذا الفريم للقراءة الفنية، وليس إشارة."


def can_publish(seconds: int, target: datetime | None, now: datetime,
                *, acknowledged: bool = False) -> bool:
    minimum = ACKNOWLEDGED_SECONDS if acknowledged else PREPUBLISH_SECONDS
    return (seconds > PREPUBLISH_SECONDS and target is not None
            and target - now >= timedelta(seconds=minimum))


def is_research_only(market: Market, independently_verified: bool) -> bool:
    # Legacy market-level calibration is not yet an approved, target-aligned
    # SMARTY model. Independently validated PRO is the only future exception.
    return market is Market.SMARTY and not independently_verified
