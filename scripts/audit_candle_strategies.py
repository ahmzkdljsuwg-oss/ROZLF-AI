"""Replay fixed OHLC rules against matched baselines. Does not enable rules."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import pandas as pd

from engines.strategies.candle_lab import family_series, strategy_series
from engines.technical.delivery_window import PREPUBLISH_SECONDS
from scripts.replay_smarty_regime import load_smarty

FRAMES = {"5sec": 5, "30sec": 30, "1min": 60, "2min": 120, "3min": 180, "5min": 300}
OFFSET = 2


def evaluate(frame: pd.DataFrame, seconds: int) -> dict:
    if len(frame) < 230:
        raise ValueError("insufficient contiguous history for a fair replay")
    # Simulate a read just after the final feature bar closes. i+1 is already
    # open, so its OHLC is not observed and the target is i+2.
    step = pd.Timedelta(seconds=seconds)
    times = frame.index.to_series()
    body = frame.close - frame.open
    label = ((body > 0).astype(int) - (body < 0).astype(int)).shift(-OFFSET)
    valid = (times.shift(-1) == times + step) & (times.shift(-2) == times + 2*step)
    readings = strategy_series(frame, seconds)
    predictions = pd.concat([readings, family_series(readings).add_prefix("family:")], axis=1)
    # The first 40% supplies initial history. Before each remaining 20% fold,
    # fit the comparator to labels that have actually closed before that fold.
    folds = []
    for start, end in zip((.4, .6, .8), (.6, .8, 1.0)):
        lo, hi = int(len(frame)*start), int(len(frame)*end)
        past = label.where(valid & (times + (OFFSET+1)*step < times.iloc[lo])).dropna()
        constant = 1 if len(past) and (past == 1).sum() >= (past == -1).sum() else -1
        labels = label.iloc[lo:hi].where(valid.iloc[lo:hi])
        previous_side = body.iloc[lo:hi].apply(lambda v: 1 if v > 0 else -1 if v < 0 else constant)
        metrics = {}
        for key in predictions:
            side = predictions[key].iloc[lo:hi]
            selected = side.isin((-1, 1)) & labels.notna()
            actual = labels[selected]
            metrics[key] = {"n": int(selected.sum()), "wins": int((side[selected] == actual).sum()),
                            "ties": int((actual == 0).sum()), "majority": int((actual == constant).sum()),
                            "last_candle": int((actual == previous_side[selected]).sum())}
        folds.append({"target_start": (times.iloc[lo] + OFFSET*step).isoformat(), "eligible": int(labels.notna().sum()),
                      "majority_side": "UP" if constant == 1 else "DOWN", "metrics": metrics})
    summary = {}
    for key in predictions:
        rows = [fold["metrics"][key] for fold in folds]
        total = {column: sum(row[column] for row in rows) for column in rows[0]}
        n = total["n"]
        total["hit_pct"] = round(100 * total["wins"] / n, 2) if n else None
        total["above_both_in_all_folds"] = all(row["n"] >= 30 and row["wins"] > max(row["majority"], row["last_candle"]) for row in rows)
        summary[key] = total
    return {"bars": len(frame), "start": frame.index[0].isoformat(), "end": frame.index[-1].isoformat(),
            "eligible": sum(fold["eligible"] for fold in folds),
            "can_meet_manual_lead": seconds > PREPUBLISH_SECONDS, "rules": summary, "folds": folds}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    opts = parser.parse_args()
    now = datetime.now(timezone.utc)
    frames = {}
    for key, seconds in FRAMES.items():
        source = opts.directory / f"{key}.json"
        try:
            frames[key] = evaluate(load_smarty(source, seconds, now), seconds)
            frames[key]["snapshot_sha256"] = sha256(source.read_bytes()).hexdigest()
        except (OSError, KeyError, ValueError) as exc:
            frames[key] = {"error": f"Native {key} source history not available or invalid ({type(exc).__name__})"}
    if not any("rules" in frame for frame in frames.values()):
        raise SystemExit("no verifiable source data to audit")
    report = {"source": "ExpertOption Bridge SMARTY asset 240, native OHLC", "target_offset": OFFSET,
              "promotion": "none", "interpretation": "Exploratory historical replay, not prospective validation. "
              "Rules and frames can overlap and are not independent. Ties count as misses for all methods. "
              "Baseline selection uses matured labels only. Baselines are scored on exactly the same target candles.",
              "frames": frames}
    opts.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for name, row in frames.items():
        if "error" in row:
            print(name, row["error"])
            continue
        passed = {k:v for k,v in row["rules"].items() if v["above_both_in_all_folds"]}
        print(name, row["eligible"], "target candles", len(passed), "screened in", passed)


if __name__ == "__main__":
    main()
