from datetime import timedelta
from types import SimpleNamespace

import pytest

from bot import formatting as fmt
from bot.handlers import menus as handlers
from bot.keyboards import menus
from engines.technical.analyzer import AnalysisResult
from providers.base import DataUnavailable, utc_now
from providers.catalog import Market
from services.market_analysis import MarketAnalysis, MarketAnalysisService
from tests.conftest import FakeProvider
from providers.registry import DataSourceRegistry


class FakeMessage:
    def __init__(self):
        self.edits = []
        self.answers = []

    async def edit_text(self, text, reply_markup=None, **kwargs):
        self.edits.append((text, reply_markup))

    async def answer(self, text, reply_markup=None, **kwargs):
        self.answers.append((text, reply_markup))


class FakeCallback:
    def __init__(self, data, user_id=42):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = FakeMessage()
        self.answered = []

    async def answer(self, text="", show_alert=False, **kwargs):
        self.answered.append(text)


class FakeRepo:
    def __init__(self):
        self.signals = []

    async def add_signal(self, **kwargs):
        self.signals.append(kwargs)
        return SimpleNamespace(**kwargs)


def _result(direction="UP", confidence=78.0, price=1.10123):
    return AnalysisResult(
        asset_key="EUR_USD_FOREX",
        asset_display="EUR/USD (FOREX)",
        market="forex",
        timeframe="5min",
        direction=direction,
        confidence=confidence,
        score_up=40.0 if direction == "UP" else 3.0,
        score_down=3.0 if direction == "UP" else 40.0,
        price=price,
        source="Test Feed",
        generated_at=utc_now(),
        reasons=["Bullish market structure", "EMA confirmation"],
        suggested_expiry_seconds=60,
    )


def test_nexus_home_and_market_stack_order():
    home = menus.nexus_home_menu()
    assert [b.text for row in home.inline_keyboard for b in row] == ["حلل 🤖"]
    markets = menus.nexus_markets_menu()
    rows = [[b.text for b in row] for row in markets.inline_keyboard]
    assert [row[0] for row in rows[:7]] == [
        "1️⃣ OTC", "2️⃣ SMARTY", "3️⃣ FOOTBALL", "4️⃣ LUXURY",
        "5️⃣ AI INDEX", "6️⃣ CRICKET", "7️⃣ FOREX",
    ]
    assert all(len(row) == 1 for row in rows[:7])


def test_nexus_card_matches_required_format():
    text = fmt.nexus_signal_text("otc", "UP", 60, 78.4)
    assert "NEXUS AI 🤖" in text
    assert "📊 السوق: <b>OTC</b>" in text
    assert "⏱️ الشمعة المستهدفة: <b>1 MIN</b>" in text
    assert "📈 الصفقة: <b>فوق</b>" in text
    assert "🎯 الثقة: <b>78%</b>" in text
    down = fmt.nexus_signal_text("forex", "DOWN", 300, 64.0)
    assert "📈 الصفقة: <b>تحت</b>" in down
    no_trade = fmt.nexus_signal_text("forex", "NO TRADE", None, None)
    assert "📈 الصفقة: <b>NO TRADE</b>" in no_trade


@pytest.mark.asyncio
async def test_service_reads_closed_and_current_candles(settings):
    registry = DataSourceRegistry([FakeProvider()], cache_ttl=0)
    service = MarketAnalysisService(registry, settings)
    outcome = await service.analyse(Market.FOREX)
    assert outcome.fetched > 0
    assert outcome.result is not None
    assert outcome.result.closed_candles >= 60
    assert outcome.result.direction in {"UP", "DOWN", "NO TRADE"}
    assert outcome.result.confidence >= 0


@pytest.mark.asyncio
async def test_service_reports_data_unavailable_without_a_source(settings):
    class EmptyInventory:
        async def assets(self, market, force=False):
            raise DataUnavailable("EO_BRIDGE_NOT_CONFIGURED", "OTC UNAVAILABLE — bridge not configured")

    service = MarketAnalysisService(DataSourceRegistry([]), settings, EmptyInventory())
    outcome = await service.analyse(Market.OTC)
    assert outcome.result is None
    assert outcome.errors
    text = fmt.nexus_data_unavailable_text("otc", outcome.errors[0])
    assert "DATA UNAVAILABLE" in text
    assert "NEXUS AI" in text


@pytest.mark.asyncio
async def test_market_analysis_selects_auto_duration_and_never_repeats(monkeypatch):
    from bot import context

    repo = FakeRepo()
    ctx = SimpleNamespace(
        registry=DataSourceRegistry([]),
        settings=SimpleNamespace(min_confidence=60.0, scan_interval=90, scanner_enabled=False),
        repo=repo,
        inventory=None,
    )
    monkeypatch.setattr(context, "_context", ctx, raising=False)
    outcome = MarketAnalysis(
        market=Market.OTC,
        result=_result("UP", 78.0),
        duration_seconds=60,
        duration_reason="volatility and momentum",
        fetched=3,
    )

    class FakeService:
        def __init__(self, *args, **kwargs):
            pass

        async def analyse(self, market):
            return outcome

    monkeypatch.setattr(handlers, "MarketAnalysisService", FakeService)
    handlers._NEXUS_LAST.clear()

    callback = FakeCallback("nx:market:OTC")
    await handlers.cb_nx_market(callback)
    text, keyboard = callback.message.edits[-1]
    assert "NEXUS AI 🤖" in text
    assert "📊 السوق: <b>OTC</b>" in text
    assert "⏱️ الشمعة المستهدفة: <b>1 MIN</b>" in text
    assert "📈 الصفقة: <b>فوق</b>" in text
    assert "🎯 الثقة: <b>78%</b>" in text
    assert "خذ صفقة أخرى 🔄" in [b.text for row in keyboard.inline_keyboard for b in row]
    assert len(repo.signals) == 1
    assert repo.signals[0]["expiry_seconds"] == 60

    again = FakeCallback("nx:again:OTC")
    await handlers.cb_nx_again(again)
    repeated_text, _ = again.message.edits[-1]
    assert "لم تتغير ظروف السوق" in repeated_text
    assert len(repo.signals) == 1
    assert len(again.message.edits) == 2


@pytest.mark.asyncio
async def test_market_analysis_conflict_returns_no_trade(monkeypatch):
    from bot import context

    ctx = SimpleNamespace(
        registry=DataSourceRegistry([]),
        settings=SimpleNamespace(min_confidence=60.0, scan_interval=90, scanner_enabled=False),
        repo=FakeRepo(),
        inventory=None,
    )
    monkeypatch.setattr(context, "_context", ctx, raising=False)
    outcome = MarketAnalysis(
        market=Market.FOREX,
        result=_result("UP"),
        duration_seconds=None,
        conflict="UP on 1min conflicts with DOWN on 5min",
        fetched=2,
    )

    class FakeService:
        def __init__(self, *args, **kwargs):
            pass

        async def analyse(self, market):
            return outcome

    monkeypatch.setattr(handlers, "MarketAnalysisService", FakeService)
    callback = FakeCallback("nx:market:FOREX")
    await handlers.cb_nx_market(callback)
    text, _ = callback.message.edits[-1]
    assert "📈 الصفقة: <b>NO TRADE</b>" in text
    assert "conflicts" in text
    assert ctx.repo.signals == []


@pytest.mark.asyncio
async def test_market_analysis_data_unavailable_renders_no_recommendation(monkeypatch):
    from bot import context

    ctx = SimpleNamespace(
        registry=DataSourceRegistry([]),
        settings=SimpleNamespace(min_confidence=60.0, scan_interval=90, scanner_enabled=False),
        repo=FakeRepo(),
        inventory=None,
    )
    monkeypatch.setattr(context, "_context", ctx, raising=False)
    outcome = MarketAnalysis(market=Market.SMARTY, errors=["bridge not configured"])

    class FakeService:
        def __init__(self, *args, **kwargs):
            pass

        async def analyse(self, market):
            return outcome

    monkeypatch.setattr(handlers, "MarketAnalysisService", FakeService)
    callback = FakeCallback("nx:market:SMARTY")
    await handlers.cb_nx_market(callback)
    text, _ = callback.message.edits[-1]
    assert "DATA UNAVAILABLE" in text
    assert "NO TRADE" in text
    assert ctx.repo.signals == []


@pytest.mark.parametrize("market_key", ["FOOTBALL", "LUXURY", "AI", "CRICKET"])
@pytest.mark.asyncio
async def test_every_dynamic_market_shows_data_unavailable_without_its_source(monkeypatch, market_key):
    from bot import context

    ctx = SimpleNamespace(
        registry=DataSourceRegistry([]),
        settings=SimpleNamespace(min_confidence=60.0, scan_interval=90, scanner_enabled=False),
        repo=FakeRepo(),
        inventory=None,
    )
    monkeypatch.setattr(context, "_context", ctx, raising=False)
    outcome = MarketAnalysis(market=Market[market_key], errors=[f"{market_key} bridge not configured"])

    class FakeService:
        def __init__(self, *args, **kwargs):
            pass

        async def analyse(self, market):
            assert market.value == market_key.lower()
            return outcome

    monkeypatch.setattr(handlers, "MarketAnalysisService", FakeService)
    callback = FakeCallback(f"nx:market:{market_key}")
    await handlers.cb_nx_market(callback)
    text, keyboard = callback.message.edits[-1]
    assert "DATA UNAVAILABLE" in text
    assert "NO TRADE" in text
    assert "خذ صفقة أخرى 🔄" in [b.text for row in keyboard.inline_keyboard for b in row]
    assert ctx.repo.signals == []


@pytest.mark.asyncio
async def test_gemini_and_mistral_review_run_inside_automatic_analysis(monkeypatch, settings):
    import services.market_analysis as market_analysis
    from ai.review import AIReviewer

    monkeypatch.setattr(market_analysis, "analyze_market_data", lambda data: _result("UP", 80.0))

    class FakeAI:
        configured = True

        def __init__(self, reply):
            self.reply = reply

        async def analyse_setup(self, payload):
            assert payload["technical_decision"] == "UP"
            assert payload["entry_price"] == _result("UP", 80.0).price
            return self.reply

    service = market_analysis.MarketAnalysisService(
        DataSourceRegistry([FakeProvider()], cache_ttl=0), settings
    )
    service.reviewer = AIReviewer(
        FakeAI('{"decision":"UP","confidence":72}'),
        FakeAI('{"decision":"UP","confidence":68}'),
    )
    outcome = await service.analyse(Market.FOREX)
    assert outcome.actionable
    assert any("AI review confirmed" in reason for reason in outcome.result.reasons)

    service.reviewer = AIReviewer(FakeAI('{"decision":"DOWN"}'), FakeAI('{"decision":"UP"}'))
    blocked = await service.analyse(Market.FOREX)
    assert not blocked.actionable
    assert "DOWN" in blocked.conflict
