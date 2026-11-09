from __future__ import annotations

import pytest

from rozlf.engines.signals.generator import (
    ALLOWED_EXPIRIES,
    RiskPolicy,
    SignalDraft,
    SignalRejected,
    choose_expiry,
    persist_signal,
)
from rozlf.engines.technical.analyzer import analyze
from rozlf.engines.validation import validate_candles
from rozlf.providers.base import Asset
from conftest import make_candles

ASSET = Asset(symbol="EURUSD", name="EUR/USD", market="FOREX", provider="test")


def draft(timeframe: int = 300, *, candles=None, source="test"):
    data = candles or make_candles(200, timeframe=timeframe)
    analysis = analyze(data, timeframe)
    if analysis.direction == "NO TRADE":
        analysis = analysis.__class__(**{**analysis.as_dict(), "direction": "UP", "score": 80})
    return SignalDraft(
        asset=ASSET,
        timeframe=timeframe,
        analysis=analysis,
        source=source,
        validation_quality=validate_candles(data, timeframe).quality,
        candles=data,
    )


def test_choose_expiry_only_allowed_values():
    for tf in (30, 60, 300, 900, 1800, 3600):
        assert choose_expiry(tf) in ALLOWED_EXPIRIES


async def test_persist_and_duplicate_blocked(repo):
    row = await persist_signal(repo, draft(), RiskPolicy(min_score=0))
    assert row.id
    with pytest.raises(SignalRejected) as exc:
        await persist_signal(repo, draft(), RiskPolicy(min_score=0))
    assert exc.value.code == "DUPLICATE"


async def test_daily_limit(repo):
    await persist_signal(repo, draft(), RiskPolicy(min_score=0, max_per_day=1))
    other = draft(900)
    other.analysis.direction = "DOWN"
    with pytest.raises(SignalRejected) as exc:
        await persist_signal(repo, other, RiskPolicy(min_score=0, max_per_day=1))
    assert exc.value.code == "DAILY_LIMIT"


async def test_low_score_rejected(repo):
    with pytest.raises(SignalRejected) as exc:
        await persist_signal(repo, draft(), RiskPolicy(min_score=99))
    assert exc.value.code == "LOW_SCORE"


async def test_statistics_counts(repo):
    await persist_signal(repo, draft(), RiskPolicy(min_score=0))
    stats = await repo.statistics()
    assert stats["open"] == 1
    assert stats["total"] == 1
