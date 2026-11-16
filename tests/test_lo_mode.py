from types import SimpleNamespace

import pytest

from bot import formatting as fmt
from bot.handlers import menus as handlers
from database.repository import Repository
from engines.technical.analyzer import AnalysisResult, analyze_market_data
from providers.base import utc_now
from providers.catalog import Market, dynamic_asset, timeframe
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

        self.message.edit_text = edit_text

    async def answer(self, *args, **kwargs):
        return None


def _ctx(repo, inventory=None):
    return SimpleNamespace(
        registry=DataSourceRegistry([]),
        settings=SimpleNamespace(min_confidence=60.0, scan_interval=90, scanner_enabled=False),
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
    assert "LO MODE: ON" in lo_message.sent[-1][0]
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
    assert "LO MODE" in text
    assert "UNVERIFIED" in text


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
                ),
                duration_seconds=seconds,
                duration_reason="test",
                fetched=3,
            )

    monkeypatch.setattr(handlers, "MarketAnalysisService", Service)
    callback = Callback(f"nx:market:{market_name}", 77)
    await handlers.cb_nx_market(callback)
    if market_name == "SMARTY":
        pick = Callback("nx:pick:SMARTY:0", 77)
        pick.message = callback.message
        await handlers.cb_nx_pick(pick)
        assert seen["asset_key"]
    text, _ = callback.message.edits[-1]
    assert seen["mode"] == mode
    assert "NEXUS AI" in text
    if mode == "lo":
        assert "UNVERIFIED" in text
    else:
        assert "61%" in text
    if market_name == "SMARTY":
        assert "5 SEC" in text
