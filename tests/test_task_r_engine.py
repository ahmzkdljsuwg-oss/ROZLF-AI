"""Task R: market-grade evidence scoring, durations and no-trade reporting."""
from types import SimpleNamespace

import pytest

from bot import formatting as fmt
from engines.technical.analyzer import analyze_market_data
from providers.catalog import Market, assets_for

from tests.conftest import make_candles
from tests.test_evidence_engine import _market


def _result(asset, tf, duration, drift=0.00008, seed=3):
    candles = make_candles(240, drift=drift, noise=0.00035, seed=seed)
    return analyze_market_data(_market(asset, candles, tf=tf), duration_seconds=duration)


@pytest.mark.parametrize("market", [Market.SMARTY, Market.FOOTBALL, Market.LUXURY, Market.AI, Market.FOREX])
def test_each_market_can_emit_a_directional_signal(market):
    asset = assets_for(market)[0]
    result = _result(asset, "1min", 60)
    assert result.direction in {"UP", "DOWN"}
    assert not result.blockers
    assert 50.0 <= result.confidence <= 92.0


def test_duration_changes_the_evidence_weighting():
    asset = assets_for(Market.FOREX)[0]
    short = _result(asset, "1min", 30)
    long = _result(asset, "5min", 300)
    assert short.direction in {"UP", "DOWN"}
    assert long.direction in {"UP", "DOWN"}
    assert short.confidence != long.confidence


@pytest.mark.parametrize(
    ("reason", "label"),
    [
        ("CONFIDENCE 61% IS BELOW YOUR 70% MINIMUM", "قوة الإشارة أقل من الحد المطلوب"),
        ("A fresh CHoCH reverses the setup", "تعارض بين الأدلة"),
        ("price is extended from EMA21; late entry refused", "دخول متأخر"),
        ("price is pressed against the opposing level", "السعر عند مستوى مهم"),
        ("STALE_DATA", "بيانات غير كافية أو غير محدثة"),
    ],
)
def test_no_trade_reason_is_specific(reason, label):
    result = SimpleNamespace(cancellation_reason=reason, blockers=[])
    assert fmt.no_trade_reason(result) == label


def test_no_trade_card_has_no_invented_numbers():
    text = fmt.signal_card_text(
        "smarty", "SMARTY", "NO TRADE", 60, 82.0, "INSUFFICIENT CONFIRMATION"
    )
    assert "⚪ الإشارة: <b>لا توجد فرصة تداول</b>" in text
    assert "⏱️ مدة الصفقة: —" in text
    assert "82%" not in text


def test_welcome_screen_is_the_single_nexus_panel():
    lines = [line for line in fmt.NEXUS_WELCOME.splitlines() if line.strip()]
    assert lines == ["أهلاً بك في <b>NEXUS AI</b> 📊✨", "اضغط على الزر أدناه للبدء 👇"]
    assert "NEXUS AI" in fmt.NEXUS_WELCOME
    assert not hasattr(fmt, "welcome_text")
