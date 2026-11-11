"""ROZLF AI panel v2 — exact card templates and navigation coverage."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from bot import formatting as fmt
from bot.handlers import menus as handlers
from bot.keyboards import menus as kb
from engines.technical.analyzer import AnalysisResult
from providers.catalog import Market, dynamic_asset


def _asset(market=Market.SMARTY, bridge_id=240, name="SMRTY"):
    return dynamic_asset(f"{market.value}_{bridge_id}", market, bridge_id=bridge_id, name=name)


def test_buy_template_exact():
    text = fmt.signal_card_text("smarty", "SMRTY", "UP", 30, 73.0)
    assert text == (
        "📊 MARKET: <b>SMARTY</b>\n"
        "💹 ASSET: <b>SMRTY</b>\n\n"
        "🟢 SIGNAL: <b>BUY 🟢</b>\n\n"
        "⏱️ TRADE TIME: <b>30 SEC</b>\n\n"
        "🎯 TRADE CONFIDENCE: <b>73%</b>"
    )


def test_sell_template_exact():
    text = fmt.signal_card_text("football", "Football Index", "DOWN", 60, 81.0)
    assert text == (
        "📊 MARKET: <b>FOOTBALL INDEX</b>\n"
        "💹 ASSET: <b>Football Index</b>\n\n"
        "🔴 SIGNAL: <b>SELL 🛑</b>\n\n"
        "⏱️ TRADE TIME: <b>1 MIN</b>\n\n"
        "🎯 TRADE CONFIDENCE: <b>81%</b>"
    )


def test_no_trade_template_hides_duration_and_confidence():
    text = fmt.signal_card_text("luxury", "Luxury Index", "NO TRADE", 300, 64.0)
    assert "⚪ SIGNAL: <b>NO TRADE</b>" in text
    assert "REASON: <b>INSUFFICIENT CONFIRMATION</b>" in text
    assert "TRADE TIME" not in text and "TRADE CONFIDENCE" not in text
    assert "300" not in text and "64%" not in text


def test_confidence_is_not_fixed():
    assert fmt.signal_card_text("ai", "AI Index", "UP", 30, 61.0) != fmt.signal_card_text(
        "ai", "AI Index", "UP", 30, 79.0
    )


def test_welcome_has_three_sections_and_no_removed_sections():
    text = fmt.welcome_text(SimpleNamespace(min_confidence=65.0, mistral_api_key="x"), ai_online=True)
    assert "WELCOME BACK" in text
    assert "The bot by lo and Q8" in text
    assert "API: 🟢 ONLINE" in text
    assert "OTC" not in text
    assert "GOLD" not in text


def test_market_page_separates_candle_frame_from_expiry():
    text = fmt.market_page_text(_asset(), "LIVE")
    assert "مدة الصفقة مستقلة" in text
    assert "TRADE DURATION" in text
    assert "SMART DURATION" in text


def test_original_duration_page_design_is_restored():
    text = fmt.smarty_card_text(_asset(), "LIVE", "ID 240")
    assert "EXPERTOPTION" in text
    assert "ASSET:" in text and "EO ASSET ID:" in text
    assert "اختر مدة الصفقة" in text
    assert "مدة الصفقة مستقلة" in text


def test_unavailable_hides_duration_actions():
    markup = kb.unavailable_menu(Market.CRICKET)
    data = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert not any(item.startswith(("dur:", "md:")) for item in data)
    assert "menu:main" in data


def test_signal_result_menu_has_details_and_reanalyse():
    asset = _asset()
    markup = kb.signal_result_menu(asset, "1min")
    data = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert f"whyd:{asset.key}:1min" in data
    assert f"an:{asset.key}:1min" in data
    assert "menu:main" in data


def _result(asset, direction="UP", confidence=77.0):
    return AnalysisResult(
        asset_key=asset.key,
        asset_display=asset.display,
        market=asset.market.value,
        timeframe="1min",
        direction=direction,
        confidence=confidence,
        score_up=3.0,
        score_down=1.0,
        price=1.2345,
        source="eo_bridge",
        generated_at=datetime.now(timezone.utc),
        reasons=["Bullish structure", "EMA confirmation"],
        indicators={"rsi": 58.2},
        trend_summary="BULLISH",
        momentum_strength="STRONG",
        data_quality_score=8.5,
    )


def test_analysis_details_render_honest_evidence():
    asset = _asset()
    result = _result(asset)
    record = SimpleNamespace(direction="UP", expiry_seconds=30, confidence=77.0)
    text = fmt.analysis_details_text(result, record)
    assert "EVIDENCE SCORE: 77%" in text
    assert "DATA QUALITY: 8.5/10" in text
    assert "RSI: 58.2" in text
    assert "Bullish structure" in text


async def test_why_handler_uses_cached_analysis():
    asset = _asset()
    result = _result(asset)
    record = SimpleNamespace(direction="UP", expiry_seconds=30, confidence=77.0)

    class Message:
        def __init__(self):
            self.edits = []

        async def edit_text(self, text, reply_markup=None, **kwargs):
            self.edits.append(text)

    class Callback:
        def __init__(self):
            self.data = f"whyd:{asset.key}:1min"
            self.from_user = SimpleNamespace(id=42)
            self.message = Message()
            self.answers = []

        async def answer(self, text="", show_alert=False, **kwargs):
            self.answers.append(text)

    handlers._LAST_ANALYSIS[(42, asset.key)] = (result, record, "SMART DURATION: volatility NORMAL")
    callback = Callback()
    await handlers.cb_why_signal(callback)
    assert "ANALYSIS DETAILS" in callback.message.edits[0]
    assert "SMART DURATION" in callback.message.edits[0]


def test_history_and_stats_show_unverified_separately():
    history = fmt.history_text([])
    assert "SIGNAL HISTORY" in history
    stats = fmt.stats_text(
        {
            "total": 4,
            "active": 1,
            "verified": 2,
            "wins": 1,
            "losses": 1,
            "draws": 0,
            "unverified": 1,
            "accuracy": 50.0,
            "avg_confidence": 70.0,
            "profit_factor": 1.4,
            "per_market": {"smarty": {"wins": 1, "losses": 1, "draws": 0, "win_rate": 50.0}},
        }
    )
    assert "UNVERIFIED: 1" in stats
    assert "WIN RATE (closed): <b>50.0%</b>" in stats
    assert "نسبة ربح مضمونة" in stats
