"""Signal lifecycle: create, duplicate guard, verification, statistics."""
from datetime import timedelta

import pytest

from engines.signals.generator import SignalGenerator, supported_durations
from providers.base import DataUnavailable, utc_now
from providers.catalog import Market, dynamic_asset, find_by_symbol, timeframe
from providers.registry import DataSourceRegistry
from services.signal_tracker import SignalTracker

from tests.conftest import FakeProvider, make_candles


async def test_signal_is_stored_and_listed(settings, repo, eurusd):
    registry = DataSourceRegistry([FakeProvider(make_candles(noise=0.0001, seed=23), quote_price=1.1000)])
    generator = SignalGenerator(registry, repo, settings)

    result, record = await generator.generate(42, eurusd, "5min", duration_seconds=60, min_confidence=0.0)
    assert record is not None
    assert record.direction in {"UP", "DOWN"}
    assert record.status == "ACTIVE"
    assert record.reasons
    active = await repo.active_signals(42)
    assert [item.id for item in active] == [record.id]

    stats = await repo.statistics(42)
    assert stats["total"] == 1 and stats["active"] == 1 and stats["accuracy"] is None


async def test_no_trade_never_becomes_signal(settings, repo, eurusd):
    from engines.signals.generator import SignalGenerator as Gen

    class NoTradeGen(Gen):
        async def fetch_and_analyse(self, asset, tf, duration_seconds=None):
            _, result = await super().fetch_and_analyse(asset, tf, duration_seconds)
            result.direction = "NO TRADE"
            return None, result

    registry = DataSourceRegistry([FakeProvider()])
    generator = NoTradeGen(registry, repo, settings)
    result, record = await generator.generate(42, eurusd, "5min")
    assert record is None
    assert result.direction == "NO TRADE"


async def test_min_confidence_blocks_signal(settings, repo, eurusd):
    registry = DataSourceRegistry([FakeProvider(quote_price=1.1)])
    generator = SignalGenerator(registry, repo, settings)
    result, record = await generator.generate(42, eurusd, "5min", min_confidence=99.0)
    assert record is None
    assert result.confidence < 99.0


def test_durations_respect_timeframe(eurusd):
    allowed = supported_durations(eurusd, timeframe("1min"))
    assert {30, 45, 60, 105}.issubset(allowed)
    assert 5 not in allowed and 15 not in allowed
    otc = dynamic_asset("EURUSD_OTC", Market.OTC, precision=5, bridge_id=179)
    allowed_otc = supported_durations(otc, timeframe("1min"))
    assert 30 not in allowed_otc and 60 in allowed_otc


async def _add_signal(repo, asset, direction, entry, minutes_ago=8, expiry=300, user=42):
    return await repo.add_signal(
        user_id=user,
        asset_key=asset.key,
        asset_display=asset.display,
        market=asset.market.value,
        timeframe="5min",
        direction=direction,
        confidence=70.0,
        entry_price=entry,
        source="Fake Feed",
        reasons=["test fixture"],
        warnings=[],
        expiry_seconds=expiry,
        created_at=utc_now() - timedelta(minutes=minutes_ago),
    )


async def test_verification_win(settings, repo, eurusd):
    provider = FakeProvider(quote_price=1.1000)
    registry = DataSourceRegistry([provider])
    record = await _add_signal(repo, eurusd, "UP", 1.1000)
    provider.quote_price = 1.1010

    tracker = SignalTracker(repo, registry)
    assert await tracker.verify_due() == 1

    stats = await repo.statistics(42)
    assert stats["wins"] == 1 and stats["verified"] == 1 and stats["accuracy"] == 100.0


async def test_verification_loss_and_draw(settings, repo, eurusd):
    provider = FakeProvider(quote_price=1.1000)
    registry = DataSourceRegistry([provider])
    await _add_signal(repo, eurusd, "UP", 1.1000, user=42)
    await _add_signal(repo, eurusd, "DOWN", 1.1000, user=43)
    provider.quote_price = 1.0990

    tracker = SignalTracker(repo, registry)
    assert await tracker.verify_due() == 2
    stats = await repo.statistics()
    assert stats["wins"] == 1 and stats["losses"] == 1
    assert stats["accuracy"] == 50.0


async def test_draw_detected(settings, repo, eurusd):
    provider = FakeProvider(quote_price=1.1000)
    registry = DataSourceRegistry([provider])
    await _add_signal(repo, eurusd, "UP", 1.1000)
    provider.quote_price = 1.1000

    tracker = SignalTracker(repo, registry)
    assert await tracker.verify_due() == 1
    stats = await repo.statistics(42)
    assert stats["draws"] == 1 and stats["accuracy"] is None


async def test_unverifiable_marked_unverified(settings, repo, eurusd):
    registry = DataSourceRegistry([FakeProvider(quote_price=None)])
    await _add_signal(repo, eurusd, "UP", 1.1000, minutes_ago=20)
    tracker = SignalTracker(repo, registry, grace_seconds=60)
    assert await tracker.verify_due() == 1
    stats = await repo.statistics(42)
    assert stats["unverified"] == 1
    assert stats["verified"] == 0
    assert stats["accuracy"] is None


async def test_open_signals_excluded_from_accuracy(settings, repo, eurusd):
    registry = DataSourceRegistry([FakeProvider(make_candles(noise=0.0001, seed=23), quote_price=1.1000)])
    generator = SignalGenerator(registry, repo, settings)
    await generator.generate(42, eurusd, "5min", duration_seconds=60, min_confidence=0.0)
    stats = await repo.statistics(42)
    assert stats["active"] == 1
    assert stats["accuracy"] is None


async def test_duplicate_scan_suppressed(settings, repo, eurusd):
    from services.scanner import AutoScanner

    registry = DataSourceRegistry([FakeProvider(make_candles(noise=0.0001, seed=23), quote_price=1.1)])
    generator = SignalGenerator(registry, repo, settings)
    scanner = AutoScanner(generator, repo, registry, settings)
    first = await scanner.scan_once(user_ids=[42], min_confidence=0.0)
    second = await scanner.scan_once(user_ids=[42], min_confidence=0.0)
    assert first
    assert second == []


async def test_market_data_unavailable_is_honest(settings, repo, btc_otc):
    registry = DataSourceRegistry([FakeProvider(quote_price=1.1)])
    generator = SignalGenerator(registry, repo, settings)
    with pytest.raises(DataUnavailable):
        await generator.generate(42, btc_otc, "1min", min_confidence=0.0)


async def test_short_expiry_uses_server_clock(settings, repo, eurusd):
    from datetime import timedelta

    from providers.base import utc_now

    provider = FakeProvider(quote_price=1.1010)
    registry = DataSourceRegistry([provider])
    start = (utc_now() - timedelta(seconds=46)).replace(microsecond=0)
    record = await repo.add_signal(
        user_id=42,
        asset_key=eurusd.key,
        asset_display=eurusd.display,
        market=eurusd.market.value,
        timeframe="1min",
        direction="UP",
        confidence=70.0,
        entry_price=1.1000,
        source="Fake Feed",
        reasons=["test fixture"],
        warnings=[],
        expiry_seconds=45,
        created_at=start,
    )
    tracker = SignalTracker(repo, registry)

    assert await tracker.verify_due(now=start + timedelta(seconds=44)) == 0
    assert await tracker.verify_due(now=start + timedelta(seconds=46)) == 1
    stats = await repo.statistics(42)
    assert stats["wins"] == 1 and stats["verified"] == 1
