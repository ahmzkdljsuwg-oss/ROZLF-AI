from datetime import timedelta
from types import SimpleNamespace

import pytest

from bot import formatting as fmt
from bot.handlers import menus as handlers
from database.repository import Repository
from engines.technical.analyzer import AnalysisResult, analyze_market_data
from providers.base import utc_now
from providers.catalog import SMARTY_ASSET, Market, dynamic_asset, timeframe
from providers.registry import DataSourceRegistry
from services.market_analysis import MarketAnalysis
from tests.conftest import FakeProvider


class Message:
    def __init__(self, user_id):
        self.from_user = SimpleNamespace(id=user_id)
        self.sent = []

    async def answer(self, text, reply_markup=None, **kwargs):
        self.sent.append((text, reply_markup))


class Callback:
    def __init__(self, data, user_id):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = SimpleNamespace(edits=[])

        async def edit_text(text, reply_markup=None, **kwargs):
            self.message.edits.append((text, reply_markup))
            return SimpleNamespace(edit_date=utc_now())

        self.message.edit_text = edit_text

    async def answer(self, *args, **kwargs):
        return None


def _ctx(repo, inventory=None):
    return SimpleNamespace(
        registry=DataSourceRegistry([FakeProvider()]),
        settings=SimpleNamespace(min_confidence=60.0, scan_interval=90, scanner_enabled=False,
                                 subscriptions_enabled=False, owner_ids=[]),
        repo=repo,
        inventory=inventory,
        gemini=None,
        mistral=None,
    )


@pytest.mark.asyncio
async def test_mode_is_persisted_per_user_across_repository_restart(settings):
    first = Repository(settings)
    await first.init()
    await first.set_analysis_mode(11, "lo")
    await first.set_analysis_mode(22, "strong")
    assert await first.get_analysis_mode(11) == "lo"
    assert await first.get_analysis_mode(22) == "strong"
    await first.close()

    second = Repository(settings)
    await second.init()
    assert await second.get_analysis_mode(11) == "lo"
    assert await second.get_analysis_mode(22) == "strong"
    await second.close()


@pytest.mark.asyncio
async def test_lo_and_llo_commands_report_status(monkeypatch, repo):
    from bot import context

    monkeypatch.setattr(context, "_context", _ctx(repo), raising=False)
    lo_message = Message(11)
    await handlers.cmd_lo(lo_message)
    assert lo_message.sent[-1][0] == "NEXUS AI 🤖\nوضع LO شغّال ✅"
    assert await repo.get_analysis_mode(11) == "lo"

    llo_message = Message(11)
    await handlers.cmd_llo(llo_message)
    assert "STRONG ANALYSIS: ON" in llo_message.sent[-1][0]
    assert await repo.get_analysis_mode(11) == "strong"


@pytest.mark.asyncio
async def test_lo_engine_gives_direction_but_no_calibrated_confidence(monkeypatch):
    import engines.technical.next_candle as nc

    monkeypatch.setattr(nc, "load_calibration", lambda: {})
    from providers.catalog import find_by_symbol

    registry = DataSourceRegistry([FakeProvider()], cache_ttl=0)
    data = await registry.fetch(find_by_symbol("EUR/USD", Market.FOREX), timeframe("5min"))
    result = analyze_market_data(data, analysis_mode="lo")
    assert result.direction in {"UP", "DOWN"}
    assert result.confidence_verified is False
    assert result.confidence == 0.0
    assert result.win_probability is None
    text = fmt.nexus_signal_text(
        "forex", result.direction, 60, result.confidence, result.target_open_at,
        result.reasons, confidence_verified=False, mode="lo",
    )
    assert "الميل الفني" in text and "ليست إشارة دخول" in text
    assert "الشمعة المستهدفة" not in text and "الصفقة" not in text
    assert "UNCALIBRATED" not in text and "UNVERIFIED" not in text
    assert result.indicators["last_closed_direction"] in {"UP", "DOWN", "FLAT"}


@pytest.mark.asyncio
async def test_strong_engine_refuses_without_calibration(monkeypatch):
    import engines.technical.next_candle as nc
    from providers.catalog import find_by_symbol

    monkeypatch.setattr(nc, "load_calibration", lambda: {})
    registry = DataSourceRegistry([FakeProvider()], cache_ttl=0)
    data = await registry.fetch(find_by_symbol("EUR/USD", Market.FOREX), timeframe("5min"))
    result = analyze_market_data(data, analysis_mode="strong")
    assert result.direction == "NO TRADE"
    assert "no calibrated walk-forward table" in result.reasons[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("market_name, command, mode, seconds", [
    ("SMARTY", "lo", "lo", 5),
    ("FOREX", "llo", "strong", 60),
])
async def test_telegram_market_path_uses_saved_mode(monkeypatch, repo, market_name, command, mode, seconds):
    from bot import context

    if command == "lo":
        await repo.set_analysis_mode(77, "lo")
    else:
        await repo.set_analysis_mode(77, "strong")
    class OneAsset:
        def __init__(self, market):
            self.asset = dynamic_asset(f"{market.value.upper()}USD", market, bridge_id=5)

        async def assets(self, market, force=False):
            return [self.asset]

    monkeypatch.setattr(context, "_context", _ctx(repo, OneAsset(Market[market_name])), raising=False)

    seen = {}

    class Service:
        def __init__(self, *args, **kwargs):
            seen["mode"] = kwargs.get("mode")

        async def analyse(self, market, asset_key=None):
            seen["asset_key"] = asset_key
            return MarketAnalysis(
                market=market,
                result=AnalysisResult(
                    asset_key=f"{market_name}_ASSET",
                    asset_display=market_name,
                    market=market.value,
                    timeframe="5sec" if market_name == "SMARTY" else "1min",
                    direction="UP",
                    confidence=0.0 if mode == "lo" else 61.0,
                    score_up=30.0,
                    score_down=2.0,
                    price=100.0,
                    source="test",
                    generated_at=utc_now(),
                    reasons=["trend +8.0"],
                    confidence_verified=mode != "lo",
                    analysis_mode=mode,
                    target_open_at=utc_now() + timedelta(seconds=30),
                ),
                duration_seconds=seconds,
                duration_reason="test",
                fetched=3,
            )

    monkeypatch.setattr(handlers, "MarketAnalysisService", Service)
    callback = Callback(f"nx:market:{market_name}", 77)
    await handlers.cb_nx_market(callback)
    pick = Callback(f"nx:pick:{market_name}:0", 77)
    pick.message = callback.message
    await handlers.cb_nx_pick(pick)
    assert seen["asset_key"]
    text, _ = callback.message.edits[-1]
    assert seen["mode"] == mode
    assert "السوق:" in text
    if market_name == "SMARTY":
        assert "NO TRADE" not in text
        assert "قراءة فنية فقط" in text and "الشمعة المستهدفة" not in text
    else:
        assert "61%" in text


@pytest.mark.asyncio
async def test_start_resets_lo_but_menu_does_not(monkeypatch, repo):
    from bot import context

    monkeypatch.setattr(context, "_context", _ctx(repo))
    message = Message(11)
    message.text = "/lo"
    await handlers.cmd_lo(message)
    message.text = "/menu"
    await handlers.cmd_start(message)
    assert await repo.get_analysis_mode(11) == "lo"
    message.text = "/start@ExampleBot"
    await handlers.cmd_start(message)
    assert await repo.get_analysis_mode(11) == "strong"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["balanced", "late", "unavailable"])
async def test_lo_retries_same_asset_and_never_fabricates_a_signal(monkeypatch, case):
    from bot import context

    async def get_mode(_):
        return "lo"

    async def add_signal(**_):
        pytest.fail("A blocked forecast cannot be saved as a signal")

    calls = []

    class Service:
        def __init__(self, *_args, mode, **_kwargs):
            assert mode == "lo"

        async def analyse(self, market, asset_key=None):
            calls.append((market, asset_key))
            if case == "unavailable":
                return MarketAnalysis(market, errors=["NO TRADE / DATA UNAVAILABLE"])
            result = AnalysisResult(SMARTY_ASSET.key, SMARTY_ASSET.display, "smarty", "30sec",
                                    "UP" if case == "late" else "NO TRADE", 0, 1, 0, 10, "test", utc_now(),
                                    indicators={"trend": "DOWN", "volatility": "NORMAL", "last_closed_direction": "DOWN"},
                                    reasons=["technical components are too balanced"],
                                    target_open_at=utc_now() - timedelta(seconds=1))
            return MarketAnalysis(market, result, 30 if case == "late" else None)

    monkeypatch.setattr(context, "_context", _ctx(SimpleNamespace(get_analysis_mode=get_mode, add_signal=add_signal)))
    monkeypatch.setattr(handlers, "MarketAnalysisService", Service)
    callback = Callback(f"nx:again:SMARTY:{SMARTY_ASSET.key}", 77)
    await handlers.cb_nx_again(callback)
    text, keyboard = callback.message.edits[-1]
    assert calls == [(Market.SMARTY, SMARTY_ASSET.key)]
    assert keyboard.inline_keyboard[0][0].callback_data == callback.data
    assert all(s not in text for s in ("NO TRADE", "DATA UNAVAILABLE", "الأصل", "technical", "UNCALIBRATED"))
    if case == "unavailable":
        assert "بيانات السوق غير متاحة" in text
    else:
        assert "آخر شمعة مغلقة: <b>هبوط 🔴</b>" in text
    assert "الشمعة المستهدفة" not in text and "الاتجاه التجريبي" not in text


@pytest.mark.asyncio
async def test_lo_uses_candles_only_and_skips_external_review(settings, monkeypatch):
    from services import market_analysis
    from tests.conftest import make_candles

    from datetime import datetime, timezone
    from engines.technical import analyzer

    fixed = datetime(2026, 11, 18, 12, 28, 3, tzinfo=timezone.utc)
    monkeypatch.setattr(market_analysis, "utc_now", lambda: fixed)
    monkeypatch.setattr(analyzer, "utc_now", lambda: fixed)

    class Provider(FakeProvider):
        async def fetch_candles(self, asset, tf, limit=300):
            frames.append((asset.key, tf.code))
            return make_candles(n=300, tf_seconds=tf.seconds, end=fixed-timedelta(seconds=tf.seconds+3))

        async def fetch_quote(self, *args, **kwargs):
            pytest.fail("LO must not request a quote")

    class Reviewer:
        def configured(self):
            pytest.fail("LO must not ask external AI to review")

    frames = []
    service = market_analysis.MarketAnalysisService(DataSourceRegistry([Provider()], clock=lambda: fixed), settings, mode="lo")
    service.reviewer = Reviewer()
    outcome = await service.analyse(Market.FOREX, "EUR_USD_FOREX")
    assert not outcome.actionable and outcome.reading_direction == "UP"
    assert outcome.duration_seconds is None
    assert frames == [("EUR_USD_FOREX", "1min")]
    assert outcome.result.target_open_at > fixed
    assert not outcome.result.confidence_verified


@pytest.mark.asyncio
async def test_smarty_lo_returns_first_current_observation_without_unnecessary_fallback(settings, monkeypatch):
    from services import market_analysis

    attempted = []

    async def one(self, asset, frame, semaphore):
        attempted.append(frame)
        now = utc_now()
        result = AnalysisResult(
            asset.key, asset.display, "smarty", frame, "UP" if frame == "1min" else "NO TRADE",
            0, 10, 0, 1, "test", now, target_open_at=now + timedelta(seconds=20),
        )
        return result, frame

    monkeypatch.setattr(market_analysis.MarketAnalysisService, "_one", one)
    service = market_analysis.MarketAnalysisService(DataSourceRegistry([]), settings, mode="lo")
    outcome = await service.analyse(Market.SMARTY)
    assert attempted == ["30sec"]
    assert not outcome.actionable and outcome.result.timeframe == "30sec"
    assert outcome.conflict is None


def _closed_frame(*, direction=1, count=240):
    import pandas as pd

    end = pd.Timestamp("2026-11-20T04:00:00Z")
    times = pd.date_range(end=end, periods=count, freq="min")
    closes = [100 + i * direction * .05 for i in range(count)]
    opens = [close - direction * .04 for close in closes]
    return pd.DataFrame({"open": opens, "close": closes,
                         "high": [max(o, c) + .03 for o, c in zip(opens, closes)],
                         "low": [min(o, c) - .03 for o, c in zip(opens, closes)]}, index=times)


def _lo_forecast(frame, *, last_close=None):
    from engines.technical.next_candle import forecast_from_frame

    now = last_close or frame.index[-1] + timedelta(minutes=1)
    return forecast_from_frame(
        frame, market="forex", timeframe_code="1min", timeframe_seconds=60,
        now=now, target_open_at=now + timedelta(minutes=1), require_calibration=False,
    )


@pytest.mark.parametrize(("side", "bias"), [(1, "UP"), (-1, "DOWN")])
def test_lo_uses_closed_evidence_not_legacy_score(side, bias, monkeypatch):
    from engines.technical import next_candle

    def forbidden(*_args):
        pytest.fail("LO must not use the uncalibrated legacy score")

    monkeypatch.setattr(next_candle, "score_at", forbidden)
    frame = _closed_frame(direction=side)
    result = _lo_forecast(frame)
    assert result.direction == bias and not result.verified and result.confidence is None
    assert _lo_forecast(frame.tail(200)).as_dict() == result.as_dict()


@pytest.mark.parametrize(("change", "reason"), [
    ("contradict", "مو متوافقين"), ("shock", "التذبذب"), ("range", "عرضي"),
    ("gap", "شمعة مغلقة متتالية"),
])
def test_lo_declines_ambiguous_or_unsafe_readings(change, reason):
    frame = _closed_frame()
    end = frame.index[-1]
    if change == "contradict":
        frame.loc[end, "open"] = frame.loc[end, "close"] + .01
    elif change == "shock":
        frame.loc[end, "high"] += 1.
    elif change == "range":
        for i, timestamp in enumerate(frame.index):
            frame.loc[timestamp, ["open", "high", "low", "close"]] = [100., 100.1, 99.9, 100.04 if i % 2 else 99.96]
    else:
        frame = frame.drop(frame.index[-5])
    result = _lo_forecast(frame)
    assert result.direction == "NO TRADE" and result.confidence is None
    assert reason in result.blockers[0]


def test_forming_bar_does_not_change_lo_reading():
    import pandas as pd

    frame = _closed_frame()
    at = frame.index[-1] + timedelta(minutes=1)
    expected = _lo_forecast(frame, last_close=at)
    live = pd.concat([frame, pd.DataFrame(
        {"open": [70.], "high": [900.], "low": [1.], "close": [2.]}, index=[at]
    )])
    assert _lo_forecast(live, last_close=at).as_dict() == expected.as_dict()


@pytest.mark.asyncio
async def test_neutral_lo_does_not_hunt_for_a_direction_on_another_frame(settings, monkeypatch):
    from services import market_analysis

    attempted = []

    async def one(self, asset, frame, semaphore):
        attempted.append(frame)
        now = utc_now()
        result = AnalysisResult(
            asset.key, asset.display, "forex", frame, "NO TRADE" if frame == "1min" else "DOWN",
            0, 0, 0, 1, "test", now, target_open_at=now + timedelta(seconds=20),
        )
        return result, frame

    monkeypatch.setattr(market_analysis.MarketAnalysisService, "_one", one)
    service = market_analysis.MarketAnalysisService(DataSourceRegistry([]), settings, mode="lo")
    outcome = await service.analyse(Market.FOREX, "EUR_USD_FOREX")
    assert attempted == ["1min"]
    assert outcome.result.timeframe == "1min" and not outcome.actionable
    assert outcome.reading_direction is None


@pytest.mark.asyncio
async def test_lo_direction_is_never_saved_as_signal_on_repeat(settings, monkeypatch):
    from bot import context

    async def get_mode(_):
        return "lo"

    async def add_signal(**_):
        pytest.fail("a technical reading must not enter the signal ledger")

    class Service:
        def __init__(self, *_args, mode, **_kwargs):
            assert mode == "lo"

        async def analyse(self, market, asset_key=None):
            target = utc_now() + timedelta(seconds=30)
            result = AnalysisResult(
                asset_key, "EUR/USD", "forex", "1min", "UP", 0, 1, 0, 10, "test", utc_now(),
                reasons=["القراءة واضحة."], target_open_at=target,
            )
            return MarketAnalysis(market, result, 60, reading_direction="UP")

    monkeypatch.setattr(context, "_context", _ctx(SimpleNamespace(get_analysis_mode=get_mode, add_signal=add_signal)))
    monkeypatch.setattr(handlers, "MarketAnalysisService", Service)
    callback = Callback("nx:again:FOREX:EUR_USD_FOREX", 77)
    for _ in range(2):
        await handlers.cb_nx_again(callback)
        card, keyboard = callback.message.edits[-1]
        assert "الميل الفني: <b>صعود" in card and "ليست إشارة دخول" in card
        assert "الشمعة المستهدفة" not in card and "الثقة" not in card
        assert keyboard.inline_keyboard[0][0].callback_data == callback.data


def test_stale_closed_bars_do_not_create_a_current_lo_reading():
    frame = _closed_frame()
    result = _lo_forecast(frame, last_close=frame.index[-1] + timedelta(minutes=2))
    assert result.direction == "NO TRADE"
    assert "متأخرة" in result.blockers[0]


@pytest.mark.asyncio
async def test_lo_multi_asset_order_does_not_depend_on_fastest_result(settings, monkeypatch):
    import asyncio

    from providers.catalog import find_by_symbol
    from services import market_analysis

    first = find_by_symbol("EUR/USD", Market.FOREX)
    second = find_by_symbol("GBP/USD", Market.FOREX)
    arrived = asyncio.Event()

    async def assets(self, market, asset_key=None):
        return [first, second]

    async def one(self, asset, frame, semaphore):
        if asset == first:
            await arrived.wait()
            await asyncio.sleep(0)
        else:
            arrived.set()
        now = utc_now()
        result = AnalysisResult(
            asset.key, asset.display, "forex", frame, "NO TRADE" if asset == first else "UP",
            0, 0, 0, 1, "test", now, target_open_at=now + timedelta(seconds=20),
        )
        return result, frame

    service_type = market_analysis.MarketAnalysisService
    monkeypatch.setattr(service_type, "assets_for", assets)
    monkeypatch.setattr(service_type, "_one", one)
    service = service_type(DataSourceRegistry([]), settings, mode="lo")
    outcome = await service.analyse(Market.FOREX)
    assert outcome.result.asset_key == first.key and outcome.result.timeframe == "1min"
    assert outcome.reading_direction is None and not outcome.actionable
