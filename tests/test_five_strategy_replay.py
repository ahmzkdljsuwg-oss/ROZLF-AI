import json
import sys
from hashlib import sha256

import numpy as np
import pandas as pd
import pytest

from engines.backtest import five_rules as lab
from scripts import replay_five_strategies as cli


def candles(n=800):
    rng = np.random.default_rng(72)
    times = pd.date_range("2026-11-20", periods=n, freq="1min", tz="UTC")
    c = 100 + rng.normal(0, .30, n).cumsum()
    o = np.r_[100, c[:-1]]
    return pd.DataFrame({
        "open": o, "high": np.maximum(o, c) + .05,
        "low": np.minimum(o, c) - .05, "close": c,
    }, index=times)


def test_frozen_strategies_never_see_future_ohlc():
    frame = candles()
    combined = lab.strategy_readings(frame, 60)
    assert tuple(combined.columns) == lab.RULES
    pd.testing.assert_frame_equal(combined.iloc[:590], lab.strategy_readings(frame.iloc[:590], 60))
    for rule in lab.RULES:
        assert combined[rule].iloc[:lab.WARMUP - 1].isna().all()
        assert set(combined[rule].dropna().unique()) <= {-1, 0, 1}
    labelled, regime = combined.iloc[lab.WARMUP - 1:], combined["atr_regime"]
    for index in regime[regime.isin([-1, 1])].index:
        assert regime.loc[index] in labelled.loc[index, ["ema_cross_9_21_200", "bollinger_rsi"]].values


@pytest.mark.parametrize("sign", [1, -1])
def test_breakout_requires_later_confirmed_retest(sign):
    n = 23
    close = np.repeat(100., n)
    close[-3:] = [102., 103., 101.6]
    open_ = np.r_[close[0], close[:-1]]
    open_[-1] = 101.1
    high, low = np.maximum(open_, close) + .2, np.minimum(open_, close) - .2
    high[:20], low[:20] = 101., 99.
    if sign == -1:
        open_, high, low, close = 200-open_, 200-low, 200-high, 200-close
    result = lab._breakout_retest(*(pd.Series(x) for x in (open_, high, low, close, np.ones(n))))
    assert result.iloc[-3:].tolist() == [0, 0, sign]


def test_invalid_bar_reset_and_cannot_be_a_target():
    frame = candles(450)
    cutoff = frame.index[-1] + pd.Timedelta(minutes=1)
    original = lab.replay(frame, 60, as_of=cutoff)
    assert original["eligible"] == 229
    frame.iloc[225, frame.columns.get_loc("low")] = -1.
    assert lab.replay(frame, 60, as_of=cutoff)["eligible"] == 7
    readings = lab.strategy_readings(frame, 60)
    assert readings.iloc[225:445].isna().all().all()


def test_target_settlement_cutoff_and_start_are_applied_to_distinct_timestamps(monkeypatch):
    frame = candles(225)
    frame.iloc[221, frame.columns.get_loc("close")] = frame.iloc[221]["open"] + .01
    frame.iloc[221, frame.columns.get_loc("high")] = max(frame.iloc[221]["high"], frame.iloc[221]["close"])
    monkeypatch.setattr(lab, "strategy_readings", lambda data, _: pd.DataFrame(
        {name: 1 for name in lab.RULES}, index=data.index).where(
            pd.Series(np.arange(len(data)) >= lab.WARMUP - 1, index=data.index), axis=0))
    cutoff = frame.index[222]
    result = lab.replay(frame, 60, as_of=cutoff, evaluate_from=frame.index[220], payout=.8, cost=.02)
    assert result["eligible"] == 1
    assert result["folds"][0]["first_decision"] == frame.index[220].isoformat()
    totals = result["rules"][lab.RULES[0]]
    assert totals["wins"] == 1 and totals["baselines"]["always_down_wins"] == 0
    assert totals["scenario_net_per_forecast"] == .78
    assert lab.replay(frame, 60, as_of=cutoff - pd.Timedelta(seconds=1))["eligible"] == 0
    assert lab.replay(frame, 60, as_of=cutoff, evaluate_from=frame.index[221])["eligible"] == 0


def test_replay_handles_no_reads_without_reporting_zero_accuracy():
    frame = candles(4)
    result = lab.replay(frame, 60, as_of=frame.index[-1])
    assert result["eligible"] == 0
    assert all(item["hit_rate_pct"] is None for item in result["rules"].values())


def test_folds_partition_same_test_rows_and_baselines_match_n():
    frame = candles()
    result = lab.replay(frame, 60, as_of=frame.index[-1])
    assert sum(fold["eligible"] for fold in result["folds"]) == result["eligible"]
    assert all(result["folds"][i]["last_decision"] < result["folds"][i + 1]["first_decision"]
               for i in range(len(result["folds"]) - 1))
    for name, metric in result["rules"].items():
        assert sum(fold["rules"][name]["selected"] for fold in result["folds"]) == metric["selected"]
        assert metric["wins"] + metric["losses"] + metric["draws"] == metric["selected"]
        assert metric["baselines"]["always_up_wins"] + metric["baselines"]["always_down_wins"] + metric["draws"] == metric["selected"]


def test_cli_requires_exact_source_and_keeps_missing_combinations_visible(tmp_path, monkeypatch):
    frame = candles(230)
    source = tmp_path / "240-1min.json"
    payload = {"source": "ExpertOption", "market": "smarty", "symbol": "SMRTY",
               "asset_id": 240, "timeframe": "60s", "active": True, "connected": True,
               "candles": [dict(row, time=at.isoformat()) for at, row in frame.iterrows()]}
    source.write_text(json.dumps(payload))
    out = tmp_path / "report.json"
    monkeypatch.setattr(sys, "argv", ["replay", str(tmp_path), "--asset", "240",
                                    "--as-of", "2026-11-21T00:00:00Z", "--frames", "1min,5min",
                                    "--output", str(out)])
    cli.main()
    result = json.loads(out.read_text())
    assert result["mode"] == "research_only" and "markets" not in result
    assert result["results"]["smarty:SMRTY:1min"]["snapshot_sha256"] == sha256(source.read_bytes()).hexdigest()
    assert result["unavailable"]["smarty:SMRTY:5min"] == "no snapshot"
    for field, value in (("market", "otc"), ("symbol", "OTHER"), ("active", False), ("connected", False)):
        source.write_text(json.dumps({**payload, field: value}))
        with pytest.raises(ValueError):
            cli._snapshot(source, "smarty", 240, "SMRTY", "1min")
