from __future__ import annotations

from rozlf.engines.technical import smc
from rozlf.engines.technical.indicators import macd, rsi, snapshot, to_frame

from conftest import make_candles


def test_frame_and_snapshot(candles):
    df = to_frame(candles)
    assert {"open", "high", "low", "close", "volume"} <= set(df.columns)
    snap = snapshot(candles)
    assert 0 <= snap["rsi"] <= 100
    assert snap["ema9"] > 0
    assert "macd_hist" in snap


def test_rsi_extremes(candles):
    rising = make_candles(150, trend=0.001)
    assert rsi(to_frame(rising)["close"]).iloc[-1] > 70


def test_macd_shapes(candles):
    frame = macd(to_frame(candles)["close"])
    assert len(frame) == len(candles)
    assert frame["hist"].iloc[-1] == frame["macd"].iloc[-1] - frame["signal"].iloc[-1]


def test_market_structure_detects_bos(candles):
    df = to_frame(candles)
    structure = smc.market_structure(df)
    assert structure["ok"] is True
    assert structure["trend"] in ("BULLISH", "BEARISH", "RANGE")
    assert structure["bos"] in ("BULLISH", "BEARISH", "NONE")
    assert structure["zone"] in ("PREMIUM", "DISCOUNT", "EQUILIBRIUM")


def test_fvg_and_order_blocks_types(candles):
    df = to_frame(candles)
    assert isinstance(smc.fair_value_gaps(df), list)
    assert isinstance(smc.order_blocks(df), list)
    assert isinstance(smc.liquidity_sweeps(df), list)
