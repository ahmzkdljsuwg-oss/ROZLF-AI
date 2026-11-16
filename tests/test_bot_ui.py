from dataclasses import replace
from datetime import timedelta

from bot import formatting as fmt
from bot.keyboards import menus
from database.repository import SignalRecord
from providers.base import utc_now
from providers.catalog import find_by_symbol, Market


def _record(direction="UP", status="ACTIVE") -> SignalRecord:
    now = utc_now()
    return SignalRecord(
        id=1,
        user_id=42,
        asset_key="EUR_USD_FOREX",
        asset_display="EUR/USD (FOREX)",
        market="forex",
        timeframe="5min",
        direction=direction,
        confidence=78.0,
        entry_price=1.08432,
        source="Swissquote",
        reasons=["Bullish market structure", "EMA confirmation"],
        warnings=[],
        expiry_seconds=60,
        created_at=now,
        expires_at=now + timedelta(seconds=60),
        status=status,
    )


def test_single_nexus_home_menu_has_real_callbacks():
    home = menus.nexus_home_menu()
    data = [b.callback_data for row in home.inline_keyboard for b in row]
    texts = [b.text for row in home.inline_keyboard for b in row]
    assert texts == ["ابدأ استلام الإشارات 🚀"]
    assert data == ["nx:analyse"]

    markets = menus.nexus_markets_menu()
    market_data = [b.callback_data for row in markets.inline_keyboard for b in row]
    assert market_data[:2] == [
        "nx:market:FOOTBALL", "nx:classic:smarty",
    ]
    assert "nx:more" in market_data

    tools = menus.nexus_tools_menu()
    tool_data = [b.callback_data for row in tools.inline_keyboard for b in row]
    for route in ("scan:menu", "image:info", "live", "hist", "stats", "settings", "status"):
        assert route in tool_data
    assert not any(item.startswith("mkt:") for item in market_data + tool_data)


def test_market_menu_lists_all_assets():
    markup = menus.market_menu(Market.FOREX)
    data = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert any(item.startswith("pick:") for item in data)
    assert "nx:home" in data


def test_signal_text_contains_required_fields():
    text = fmt.signal_text(_record())
    for fragment in ("📊 السوق:", "💹 الأصل:", "الإشارة:", "⏱️ مدة الصفقة:", "🎯 قوة الإشارة:", "🧠 سبب الإشارة:"):
        assert fragment in text


def test_price_formatting_uses_precision():
    assert fmt.format_price(1.084321, "forex") == "1.08432"
    assert fmt.format_price(2389.4, "gold") in {"2389.40", "2,389.40"}
    assert fmt.format_price(None, "forex") == "N/A"


def test_duration_labels():
    assert fmt.duration_label(30) == "30 SEC"
    assert fmt.duration_label(60) == "1 MIN"
    assert fmt.duration_label(3600) == "1 HOUR"


def test_stats_text_handles_no_verified_data():
    text = fmt.stats_text({"total": 2, "active": 2, "verified": 0, "wins": 0, "losses": 0, "draws": 0, "unverified": 0, "accuracy": None})
    assert "N/A" in text


def test_history_text_marks_empty_history():
    assert "لا توجد" in fmt.history_text([])


def test_analysis_text_says_data_unavailable_when_needed():
    assert "DATA UNAVAILABLE" in fmt.DATA_UNAVAILABLE


def test_welcome_text_is_the_single_nexus_home(settings):
    assert "أهلاً بك" in fmt.NEXUS_WELCOME
    assert "NEXUS AI" in fmt.NEXUS_WELCOME
    assert not hasattr(fmt, "welcome_text")


def test_market_labels():
    assert fmt.market_label("forex") == "FOREX"
    assert fmt.market_label("otc") == "OTC"
    assert fmt.market_label("smarty") == "SMARTY"


def test_smarty_durations_are_expertoption_native_only():
    from providers.catalog import dynamic_asset

    asset = dynamic_asset("SMRTY", Market.SMARTY, precision=2, bridge_id=240, name="SMRTY")
    markup = menus.smarty_menu(asset)
    data = [button.callback_data for row in markup.inline_keyboard for button in row]
    for seconds in (5, 15, 30, 60, 300):
        assert f"sm:{asset.key}:{seconds}" in data
    # 180s returns ERROR_INCORRECT_DATA on ExpertOption; 120s is not offered.
    assert f"sm:{asset.key}:180" not in data
    assert f"sm:{asset.key}:120" not in data
