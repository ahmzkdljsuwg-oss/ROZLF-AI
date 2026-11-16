from datetime import timedelta
from types import SimpleNamespace

import pytest

from bot import formatting as fmt
from bot.handlers import menus as handlers
from bot.keyboards import menus
from engines.technical.analyzer import AnalysisResult
from providers.base import DataUnavailable, utc_now
from providers.catalog import Market, dynamic_asset
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
    assert [b.text for row in home.inline_keyboard for b in row] == ["ابدأ استلام الإشارات 🚀"]
    markets = menus.nexus_markets_menu()
    rows = [[b.text for b in row] for row in markets.inline_keyboard]
    assert [row[0] for row in rows[:9]] == [
        "Football Index ⚽", "Smarty 🧠", "Gold 🪙", "OTC 🌙", "Luxury Index 💎",
        "AI Index 🤖", "Cricket Index 🏏", "Forex 💱", "MT5 📈",
    ]
    assert all(len(row) == 1 for row in rows[:9])


@pytest.mark.asyncio
async def test_classic_panel_picks_real_assets_in_video_order(monkeypatch):
    from bot import context

    assets = [
        dynamic_asset("MCD_OTC", Market.OTC, bridge_id=61),
        dynamic_asset("AAPL_OTC", Market.OTC, bridge_id=38),
        dynamic_asset("USDNGN_OTC_R", Market.OTC, bridge_id=55),
        dynamic_asset("EURUSD", Market.OTC, bridge_id=23),
        dynamic_asset("XAGUSD_OTC", Market.OTC, bridge_id=31),
        dynamic_asset("GBPUSD", Market.FOREX),
    ]

    class Inventory:
        async def assets(self, market):
            assert market is Market.OTC
            return assets

    monkeypatch.setattr(context, "_context", SimpleNamespace(inventory=Inventory()))
    seen = []

    async def analyse(callback, market, asset_key=None):
        seen.append((market, asset_key))

    monkeypatch.setattr(handlers, "_nexus_analyse", analyse)
    callback = FakeCallback("nx:analyse")
    await handlers.cb_nx_analyse(callback)
    text, keyboard = callback.message.edits[-1]
    rows = keyboard.inline_keyboard
    assert text == "📊 اختر السوق المراد تحليله:"
    assert all(len(row) == 1 for row in rows)
    assert [row[0].text for row in rows[:8]] == [
        "Football Index ⚽", "Smarty 🧠", "USD/NGN (OTC) 🇳🇬",
        "EUR/USD (OTC) 🇪🇺", "Gold 🪙", "Silver ⚪", "Apple 🍎", "McDonald's 🍔",
    ]
    assert all("GBP/USD (OTC)" not in row[0].text for row in rows)
    await handlers.cb_nx_classic_asset(FakeCallback(rows[2][0].callback_data))
    await handlers.cb_nx_classic_smarty(FakeCallback(rows[1][0].callback_data))
    assert seen == [("OTC", "OTC_55"), ("SMARTY", None)]


def test_nexus_card_matches_required_format():
    text = fmt.nexus_signal_text("otc", "UP", 60, 78.4)
    assert "السوق:" in text
    assert "الوقت: <b>1 دقيقة</b> ⏱️" in text
    assert "الصفقة: <b>شراء / Buy 🟢</b>" in text
    assert "🎯 الثقة: <b>78%</b>" in text
    down = fmt.nexus_signal_text("forex", "DOWN", 300, 64.0)
    assert "الصفقة: <b>بيع / Sell 🔴</b>" in down
    no_trade = fmt.nexus_signal_text("forex", "NO TRADE", None, None)
    assert "الصفقة: <b>NO TRADE ⚪</b>" in no_trade


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
    otc_asset = dynamic_asset("EURUSD_OTC", Market.OTC, bridge_id=1)

    class OneAsset:
        async def assets(self, market, force=False):
            return [otc_asset]

    ctx = SimpleNamespace(
        registry=DataSourceRegistry([]),
        settings=SimpleNamespace(min_confidence=60.0, scan_interval=90, scanner_enabled=False),
        repo=repo,
        inventory=OneAsset(),
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

        async def analyse(self, market, asset_key=None):
            return outcome

    monkeypatch.setattr(handlers, "MarketAnalysisService", FakeService)
    handlers._NEXUS_LAST.clear()

    callback = FakeCallback("nx:market:OTC")
    await handlers.cb_nx_market(callback)
    assert "اختر الأصل" in callback.message.edits[-1][0]
    pick = FakeCallback("nx:pick:OTC:0", user_id=42)
    pick.message = callback.message
    await handlers.cb_nx_pick(pick)
    text, keyboard = callback.message.edits[-1]
    assert "السوق:" in text
    assert "الوقت: <b>1 دقيقة</b> ⏱️" in text
    assert "الصفقة: <b>شراء / Buy 🟢</b>" in text
    assert "🎯 الثقة: <b>78%</b>" in text
    assert [[(b.text, b.callback_data) for b in row] for row in keyboard.inline_keyboard] == [
        [("خذ صفقة أخرى 🔄", "nx:analyse")]
    ]
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

        async def analyse(self, market, asset_key=None):
            return outcome

    monkeypatch.setattr(handlers, "MarketAnalysisService", FakeService)
    callback = FakeCallback("nx:market:FOREX")
    await handlers.cb_nx_market(callback)
    text, _ = callback.message.edits[-1]
    assert "الصفقة: <b>NO TRADE ⚪</b>" in text
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

        async def analyse(self, market, asset_key=None):
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

        async def analyse(self, market, asset_key=None):
            assert market.value == market_key.lower()
            return outcome

    monkeypatch.setattr(handlers, "MarketAnalysisService", FakeService)
    callback = FakeCallback(f"nx:market:{market_key}")
    await handlers.cb_nx_market(callback)
    text, keyboard = callback.message.edits[-1]
    assert "DATA UNAVAILABLE" in text
    assert "NO TRADE" in text
    assert [[(b.text, b.callback_data) for b in row] for row in keyboard.inline_keyboard] == [
        [("خذ صفقة أخرى 🔄", "nx:analyse")]
    ]
    assert ctx.repo.signals == []


@pytest.mark.asyncio
async def test_gemini_and_mistral_review_run_inside_automatic_analysis(monkeypatch, settings):
    import services.market_analysis as market_analysis
    from ai.review import AIReviewer

    monkeypatch.setattr(market_analysis, "analyze_market_data", lambda data, *args, **kwargs: _result("UP", 80.0))

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


def test_otc_discovery_keeps_only_active_same_market_rows():
    from providers.inventory import MarketInventory

    rows = [
        {"id": 1, "symbol": "EURUSD_OTC", "market": "otc", "is_active": True},
        {"id": 2, "symbol": "GBPUSD_OTC", "market": "otc", "is_active": False},
        {"id": 3, "symbol": "EURUSD", "market": "forex", "is_active": True},
        {"id": 4, "symbol": "SMARTY", "market": "smarty", "is_active": True},
        {"id": 5, "symbol": "AUDUSD_OTC", "market": "otc"},
    ]
    assets = MarketInventory._to_assets(rows, Market.OTC, active_only=True)
    assert [asset.symbol for asset in assets] == ["EURUSD_OTC"]
    assert assets[0].market is Market.OTC


@pytest.mark.asyncio
async def test_selected_asset_is_the_only_one_analysed(settings):
    from providers.inventory import MarketInventory

    class Bridge:
        async def fetch_assets(self, market):
            return [
                {"id": 11, "symbol": "EURUSD_OTC", "market": "otc", "is_active": True},
                {"id": 12, "symbol": "GBPUSD_OTC", "market": "otc", "is_active": True},
            ]

    inventory = MarketInventory(Bridge(), ttl=0)
    service = MarketAnalysisService(DataSourceRegistry([]), settings, inventory)
    chosen = await service.assets_for(Market.OTC, asset_key="OTC_11")
    assert [asset.bridge_id for asset in chosen] == [11]


def test_card_shows_real_asset_and_unverified_confidence():
    text = fmt.nexus_signal_text(
        "otc", "UP", 60, 0.0, asset="EUR/USD OTC", confidence_verified=False, mode="lo",
    )
    assert "السوق: <b>EUR/USD OTC</b>" in text
    assert "LO MODE" in text
    assert "UNVERIFIED" in text
