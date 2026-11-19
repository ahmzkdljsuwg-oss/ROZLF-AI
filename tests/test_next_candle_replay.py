from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from scripts import backtest_next_candle as replay

START = datetime(2026, 11, 19, tzinfo=timezone.utc)


def row(t, score, target, *, settled=None, asset="SMRTY"):
    return {
        "time": (START + timedelta(seconds=t)).isoformat(),
        "settled_at": (START + timedelta(seconds=t + 1 if settled is None else settled)).isoformat(),
        "market": "smarty", "asset": asset, "timeframe": "1min",
        "score": score, "target": target, "last_candle": "DRAW", "components": {},
    }


def candles(n=225):
    index = pd.date_range(START, periods=n, freq="1min")
    price = pd.Series([100 + i * .01 for i in range(n)], index=index)
    return pd.DataFrame({"open": price, "high": price + 1, "low": price - 1, "close": price + .1})


def test_opposite_scores_in_same_magnitude_interval_never_train_each_other():
    history = [row(i * 3, 9, "UP") for i in range(301)]
    history += [row(1000 + i * 3, -9, "DOWN") for i in range(31)]
    history += [row(1100, 9, "UP"), row(1101, -9, "DOWN")]
    _, outputs = replay._walk_forward(history)
    assert outputs[301]["confidence"] is None
    assert outputs[301]["bucket_samples"] == 0
    assert [(r["prediction"], r["confidence"]) for r in outputs[-2:]] == [("UP", 100), ("DOWN", 100)]
    assert [(b["direction"], b["n"], b["hits"]) for b in replay._bucket_table(history)] == [
        ("DOWN", 32, 32), ("UP", 302, 302)
    ]


def test_walk_forward_rejects_mixed_instruments():
    with pytest.raises(ValueError, match="one instrument"):
        replay._walk_forward([row(1, 9, "UP"), row(2, 9, "UP", asset="ANOTHER")])


def test_labels_that_close_at_decision_time_are_not_yet_used():
    history = [row(i, -9, "DOWN", settled=500) for i in range(310)]
    same = row(500, -9, "DOWN")
    # Same instant as 00:08:20Z with different timezone formatting.
    same["time"] = (START + timedelta(seconds=500)).astimezone(timezone(timedelta(hours=3))).isoformat()
    _, outputs = replay._walk_forward([row(501, -9, "DOWN"), *history, same])
    assert outputs[-2]["confidence"] is None
    assert outputs[-1]["confidence"] == 100


def test_draws_are_misses_and_baselines_use_only_selected_targets(monkeypatch):
    monkeypatch.setattr(replay, "MIN_SETTLED_HISTORY", 4)
    monkeypatch.setattr(replay, "MIN_CALIBRATION_SAMPLES", 4)
    history = [row(i * 3, -9, outcome) for i, outcome in enumerate(("DOWN", "DRAW", "UP", "DOWN", "DOWN", "DRAW"))]
    _, tested = replay._walk_forward(history)
    assert tested[4]["confidence"] == 50
    assert tested[4]["prediction"] == "NO TRADE"
    assert tested[5]["confidence"] == 60
    out = replay._summary(history, tested)
    assert out["walk_forward"]["signals"] == out["walk_forward"]["draws"] == 1
    assert all(b["signals"] == 1 and b["wins"] == 0 for b in out["matched_baselines"].values())
    assert out["probability_check"]["brier"] == .305


def test_no_selection_is_not_reported_as_zero_percent_accuracy():
    out = replay._summary([], [])
    assert out["walk_forward"]["hit_rate"] is None
    assert out["probability_check"]["brier"] is None
    assert all(b["hit_rate"] is None for b in out["matched_baselines"].values())


def test_replay_scores_only_closed_feature_bars_and_excludes_open_target():
    frame = candles()
    at = START + timedelta(minutes=222)
    expected = replay._samples(frame, "smarty", "1min", now=at)
    assert len(expected) == 1
    result = expected[0]
    assert result["time"] == (START + timedelta(minutes=220)).isoformat()
    assert result["target_open"] == (START + timedelta(minutes=221)).isoformat()
    assert result["settled_at"] == at.isoformat()
    assert result["target"] == "UP"

    frame.iloc[220:223, frame.columns.get_loc("close")] = 102.0
    actual = replay._samples(frame, "smarty", "1min", now=at)[0]
    assert actual["target"] == "DOWN"
    assert actual["score"] == result["score"]
    assert actual["components"] == result["components"]
    assert not replay._samples(frame, "smarty", "1min", now=at - timedelta(microseconds=1))


def test_gap_or_invalid_candle_inside_warmup_cannot_be_bridged():
    frame = candles(230)
    at = START + timedelta(hours=5)
    assert replay._samples(frame, "smarty", "1min", now=at)
    assert not replay._samples(frame.drop(frame.index[20]), "smarty", "1min", now=at)
    frame.iloc[20, frame.columns.get_loc("high")] = 1.0
    assert not replay._samples(frame, "smarty", "1min", now=at)


@pytest.mark.asyncio
async def test_snapshot_cli_verifies_identity_and_only_writes_research_files(tmp_path, monkeypatch):
    import json
    import sys

    frame = candles()
    snapshot = tmp_path / "240-1min.json"
    report, candidate = tmp_path / "report.json", tmp_path / "candidate.json"
    argv = ["backtest_next_candle", "--snapshot-dir", str(tmp_path), "--output", str(report),
            "--calibration", str(candidate), "--market", "smarty", "--frames", "1min"]
    monkeypatch.setattr(sys, "argv", argv)
    payload = {"source": "ExpertOption", "asset_id": 240, "market": "otc", "timeframe": "60s",
               "candles": [dict(prices, time=at.isoformat()) for at, prices in frame.iterrows()]}
    snapshot.write_text(json.dumps(payload))
    with pytest.raises(SystemExit, match="no calibration was written"):
        await replay.main()
    assert not report.exists() and not candidate.exists()

    payload["market"] = "smarty"
    snapshot.write_text(json.dumps(payload))
    await replay.main()
    data = json.loads(report.read_text())
    assert data["assets"]["smarty:SMRTY:1min"]["snapshot_sha256"]
    assert data["results"]["smarty:SMRTY:1min"]["walk_forward"]["hit_rate"] is None
    research = json.loads(candidate.read_text())
    assert research["target_offset"] == 2
    assert research["status"] == "research_only" and "markets" not in research
    assert report.with_suffix(".md").exists()

    monkeypatch.setattr(replay, "CALIBRATION_PATH", candidate)
    with pytest.raises(SystemExit) as error:
        await replay.main()
    assert error.value.code == 2
