from datetime import timedelta

import pytest

from bot import formatting as fmt
from bot.keyboards import menus
from engines.markets import profile_for
from engines.signals.duration import choose_auto_duration
from engines.technical.analyzer import analyze_market_data
from providers.base import DataUnavailable, MarketData, Quote, ValidationReport, utc_now
from providers.catalog import Market, dynamic_asset, timeframe
from services import health
from services.scanner import SCAN_PLAN
from tests.conftest import make_candles

PROFILE_MARKETS = (Market.SMARTY, Market.FOOTBALL, Market.LUXURY, Market.AI, Market.CRICKET, Market.FOREX)


def _market(asset, code):
    tf = timeframe(code)
    candles = make_candles(220, tf_seconds=tf.seconds, noise=0.0001, seed=23)
    return MarketData(
        asset=asset,
        timeframe=tf,
        candles=candles,
        source="real-test-feed",
        quote=Quote(asset.symbol, candles[-1].close, candles[-1].close, candles[-1].time, "real-test-feed"),
        validation=ValidationReport(ok=True, bar_count=len(candles), last_candle_time=candles[-1].time),
    )


def test_each_market_has_its_own_rule_set():
    profiles = [profile_for(market) for market in PROFILE_MARKETS]
    assert len({profile.name for profile in profiles}) == len(profiles)
    assert len({profile.frames for profile in profiles}) >= 3
    assert len({tuple(sorted(profile.expiry_by_volatility.items())) for profile in profiles}) >= 4
    assert any(profile.allow_mean_reversion for profile in profiles)
    assert any(not profile.allow_mean_reversion for profile in profiles)
    assert {profile.market for profile in profiles} == set(PROFILE_MARKETS)


@pytest.mark.parametrize("market", PROFILE_MARKETS)
def test_analysis_uses_market_profile_and_expiry(market):
    asset = dynamic_asset(f"TEST_{market.value.upper()}", market, precision=4, bridge_id=1)
    code = profile_for(market).frames[0]
    result = analyze_market_data(_market(asset, code))
    profile = profile_for(market)
    assert result.market_profile == profile.name
    assert result.suggested_expiry_seconds in set(profile.expiry_by_volatility.values())


def test_market_refuses_another_markets_frame():
    asset = dynamic_asset("TEST_FOREX_FRAME", Market.FOREX, precision=5)
    with pytest.raises(DataUnavailable) as error:
        analyze_market_data(_market(asset, "30sec"))
    assert error.value.code == "UNSUPPORTED_FRAME"


def test_smart_duration_uses_profile_expiry():
    from types import SimpleNamespace

    asset = dynamic_asset("TEST_SMARTY_DURATION", Market.SMARTY, precision=2, bridge_id=240)
    result = SimpleNamespace(
        direction="UP",
        timeframe="1min",
        indicators={"volatility": "NORMAL"},
        momentum_strength="STRONG",
        confidence=70.0,
    )
    duration, reason = choose_auto_duration(result, asset)
    assert duration == 30
    assert "SMARTY profile" in reason


def test_otc_is_absent_from_all_menus_scanners_and_health():
    callbacks = [button.callback_data for row in menus.main_menu().inline_keyboard for button in row]
    assert not any(item and "OTC" in item for item in callbacks)
    assert Market.OTC not in SCAN_PLAN
    assert Market.OTC not in health.PROBE_PLAN
    assert "OTC" not in fmt.welcome_text(__import__("tests.conftest", fromlist=["base_settings"]).base_settings)


def test_status_panel_lists_cricket_and_not_otc():
    text = fmt.status_text(
        __import__("tests.conftest", fromlist=["base_settings"]).base_settings,
        [],
        {},
        {"ready": False},
    )
    assert "CRICKET INDEX" in text
    assert "OTC" not in text
