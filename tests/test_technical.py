from engines.technical.analyzer import analyze_market_data
from engines.technical.indicators import compute_indicators, frame_from_candles
from engines.technical.smc import analyze_smc
from providers.base import MarketData, utc_now
from providers.catalog import get_asset, timeframe
from engines.validation import validate_candles

from tests.conftest import make_candles


def _market_data(asset, candles, code="5min"):
    tf = timeframe(code)
    return MarketData(
        asset=asset,
        timeframe=tf,
        candles=candles,
        source="Fake Feed",
        quote=None,
        validation=validate_candles(candles, tf, min_bars=60),
    )


def test_indicators_are_bounded(eurusd):
    frame = frame_from_candles(make_candles(250))
    values = compute_indicators(frame)
    assert 0 <= values["rsi"] <= 100
    assert values["ema9"] > 0 and values["ema200"] > 0
    assert values["atr"] > 0
    assert values["trend"] in {"UP", "DOWN", "RANGE"}


def test_uptrend_is_detected(eurusd):
    candles = make_candles(250, drift=0.00008, noise=0.00001)
    result = analyze_market_data(_market_data(eurusd, candles))
    assert result.direction in {"UP", "NO TRADE"}
    assert 0 <= result.confidence <= 92
    assert result.reasons
    assert result.price > 0


def test_downtrend_is_detected(eurusd):
    candles = make_candles(250, drift=-0.00008, noise=0.00001, seed=11)
    result = analyze_market_data(_market_data(eurusd, candles))
    assert result.direction in {"DOWN", "NO TRADE"}
    assert 0 <= result.confidence <= 92


def test_flat_market_can_return_no_trade(eurusd):
    candles = make_candles(250, drift=0.0, noise=0.000005, seed=3)
    result = analyze_market_data(_market_data(eurusd, candles))
    assert result.direction in {"UP", "DOWN", "NO TRADE"}
    if result.direction == "NO TRADE":
        assert result.confidence < 92


def test_smc_structure_has_all_concepts(eurusd):
    frame = frame_from_candles(make_candles(300, drift=0.00005, seed=5))
    indicators = compute_indicators(frame)
    smc = analyze_smc(frame, indicators["atr"])
    for key in ("trend", "events", "fair_value_gaps", "order_blocks", "liquidity_sweeps", "equal_highs", "equal_lows"):
        assert key in smc
    assert len(smc["events"]) >= 0
    assert 0 <= smc["premium_discount"]["position"] <= 1


def test_confidence_never_certain(eurusd):
    candles = make_candles(300, drift=0.00015, noise=0.000005, seed=9)
    result = analyze_market_data(_market_data(eurusd, candles))
    assert result.confidence <= 92
    assert result.score_up >= 0 and result.score_down >= 0
