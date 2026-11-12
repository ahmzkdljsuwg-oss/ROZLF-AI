"""Sanity checks for the ExpertOption-native strategy pack."""
from __future__ import annotations

import numpy as np
import pandas as pd

from engines.strategies.expertoption import (
    alligator,
    aroon,
    expertoption_signals,
    parabolic_sar,
)


def _frame(closes: list[float], spread: float = 0.2) -> pd.DataFrame:
    close = pd.Series(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + spread,
            "low": close - spread,
            "close": close,
        }
    )


def test_alligator_reads_an_opening_uptrend():
    frame = _frame(list(np.linspace(100, 130, 80)))
    signal = alligator(frame, atr=1.0)
    assert signal is not None
    assert signal.direction == "UP"


def test_alligator_reads_an_opening_downtrend():
    frame = _frame(list(np.linspace(130, 100, 80)))
    signal = alligator(frame, atr=1.0)
    assert signal is not None
    assert signal.direction == "DOWN"


def test_parabolic_sar_returns_a_valid_direction():
    frame = _frame(list(np.linspace(100, 125, 60)))
    signal = parabolic_sar(frame)
    assert signal is not None
    assert signal.direction in {"UP", "DOWN"}
    assert 0 < signal.score <= 10


def test_aroon_detects_direction():
    up = aroon(_frame(list(np.linspace(100, 120, 60))))
    down = aroon(_frame(list(np.linspace(120, 100, 60))))
    assert up is not None and up.direction == "UP"
    assert down is not None and down.direction == "DOWN"


def test_aggregator_emits_unique_expertoption_names():
    frame = _frame(list(np.linspace(100, 125, 120)) + [124.0, 123.5, 123.0])
    signals = expertoption_signals(frame, {"atr": 1.0})
    names = [signal.name for signal in signals]
    assert len(names) == len(set(names))
    assert all(signal.direction in {"UP", "DOWN"} for signal in signals)
