from __future__ import annotations

import pytest

from rozlf.engines.signals.generator import RiskPolicy, SignalDraft
from rozlf.engines.signals.scanner import SignalScanner
from rozlf.providers.base import Asset, DataUnavailable, ProviderError, ProviderStatus
from rozlf.services.charts import render_result_chart, render_signal_chart
from rozlf.services.notifier import TelegramNotifier
from conftest import make_candles

ASSET = Asset(symbol="EURUSD", name="EUR/USD", market="FOREX", provider="test")


class BoomProvider:
    name = "boom"
    title = "Boom"
    can_serve_candles = True

    async def candles(self, asset, timeframe, limit=200):
        raise ProviderError("feed down", code="DOWN", retryable=True)

    async def status(self):
        return ProviderStatus("boom", "Boom", True, False, ["FOREX"], 0, "down", "bad")


class FlatRegistry:
    def __init__(self):
        self.provider = BoomProvider()

    def provider_for(self, asset):
        return self.provider

    async def candles(self, asset, timeframe, limit=200):
        return await self.provider.candles(asset, timeframe, limit)

    async def market_overview(self):
        return [{"market": "FOREX", "available": True, "detail": "", "assets": 7}]

    async def cross_check(self, asset, candle):
        return {"checked": False}


async def test_chart_renders_png(candles):
    png = render_signal_chart(
        candles, symbol="EURUSD", timeframe_label="5M", direction="UP", entry=1.1, stop=1.095, target=1.11, score=88
    )
    assert png and png[:8] == b"\x89PNG\r\n\x1a\n"


def test_chart_needs_enough_candles():
    assert (
        render_signal_chart(
            make_candles(5), symbol="EURUSD", timeframe_label="5M", direction="UP", entry=1.1, stop=1.0, target=1.2, score=80
        )
        is None
    )


def test_result_chart_renders(candles):
    png = render_result_chart(candles, symbol="EURUSD", direction="UP", entry=1.1, exit_price=1.104, result="WIN")
    assert png and png[:4] == b"\x89PNG"


async def test_notifier_sends_photo_and_text(bot, bot_session):
    notifier = TelegramNotifier(bot, "42")
    draft = SignalDraft(asset=ASSET, timeframe=300, analysis=None, source="test")  # type: ignore[arg-type]
    draft.analysis = _analysis()
    await notifier.send_signal(draft, 1, b"\x89PNG\r\n\x1a\n", "AI note", "ok")
    names = [c[0] for c in bot_session.calls]
    assert "SendPhoto" in names


async def test_notifier_disabled_without_chat(bot):
    assert TelegramNotifier(bot, "").enabled is False


async def test_scanner_reports_provider_failure():
    scanner = SignalScanner(FlatRegistry(), RiskPolicy())  # type: ignore[arg-type]
    result = await scanner.scan_market("FOREX")
    assert result.skipped
    assert all(item["code"] == "DOWN" for item in result.skipped)


def _analysis():
    from rozlf.engines.technical.analyzer import analyze

    return analyze(make_candles(200), 300)
