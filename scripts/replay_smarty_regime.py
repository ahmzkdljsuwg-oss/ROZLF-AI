"""Compare fixed SMARTY next-candle rules against the live LO baseline on held-out bars."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from engines.technical.next_candle import _series, _technical_forecast, score_at
from engines.technical.regime_candle import (
    RULE_VERSION, TARGET_OFFSET, WARMUP, decide_regime, regime_features,
)

FRAMES = {"5sec": 5, "15sec": 15, "30sec": 30, "1min": 60}
MIN_SIGNALS = 100
# 99% two-sided Wilson bounds, conservative across the four frames.
Z = 2.576


def load_smarty(path: Path, seconds: int, as_of: datetime) -> pd.DataFrame:
    payload = json.loads(path.read_text())
    if (payload.get("source"), payload.get("asset_id"), payload.get("market"), payload.get("timeframe")) != (
        "ExpertOption", 240, "smarty", f"{seconds}s",
    ):
        raise ValueError(f"{path}: not a verified SMARTY frame")
    frame = pd.DataFrame(payload["candles"])
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("time"), utc=True))
    ohlc = frame[["open", "high", "low", "close"]].astype(float)
    if (ohlc.index.has_duplicates or not ohlc.index.is_monotonic_increasing
            or not np.isfinite(ohlc).all().all() or not (ohlc > 0).all().all()
            or (ohlc.high < ohlc[["open", "close", "low"]].max(axis=1)).any()
            or (ohlc.low > ohlc[["open", "close"]].min(axis=1)).any()):
        raise ValueError(f"{path}: malformed, duplicate, or unordered candles")
    return ohlc[ohlc.index + pd.Timedelta(seconds=seconds) <= as_of]


def metrics(predictions: list[str], labels: list[str]) -> dict:
    selected = [(p, y) for p, y in zip(predictions, labels) if p in ("UP", "DOWN")]
    wins = sum(p == y for p, y in selected)
    draws = sum(y == "DRAW" for p, y in selected)
    n = len(selected)
    p = wins / n if n else 0.0
    lower = None
    if n:
        lower = (p + Z**2 / (2 * n) - Z * math.sqrt((p * (1 - p) + Z**2 / (4 * n)) / n)) / (1 + Z**2 / n)
    return {"signals": n, "wins": wins, "draws": draws,
            "hit_rate": round(100 * p, 2) if n else None,
            "coverage": round(100 * n / len(labels), 2) if labels else 0.0,
            "wilson_99_lower": round(100 * lower, 2) if lower is not None else None}


def _window(frame: pd.DataFrame, seconds: int) -> list[dict]:
    features = regime_features(frame)
    delta = pd.Timedelta(seconds=seconds)
    groups = (frame.index.to_series().diff() != delta).cumsum().to_numpy()
    rows = []
    for i in range(WARMUP - 1, len(frame) - TARGET_OFFSET):
        j = i + TARGET_OFFSET
        if groups[i - WARMUP + 1] != groups[j]:
            continue
        window = frame.iloc[max(0, i - 298):i + 1]
        score, components = score_at(window, _series(window))
        old = _technical_forecast(score, components, frame.index[j], seconds, []).direction
        decision = decide_regime(features.iloc[i])
        change = frame.close.iloc[j] - frame.open.iloc[j]
        rows.append({"target": frame.index[j], "legacy_lo": old,
                     "candidate": decision.direction,
                     "label": "UP" if change > 0 else "DOWN" if change < 0 else "DRAW"})
    return rows


def evaluate(frame: pd.DataFrame, seconds: int) -> dict:
    if len(frame) < 2 * WARMUP:
        raise ValueError("insufficient chronological history")
    # The evaluation target and all features are from the same chronological
    # sequence. The first 40% determines the constant-side comparator only.
    cut = frame.index[int(len(frame) * 0.40)]
    rows = _window(frame, seconds)
    past = [row for row in rows if row["target"] < cut]
    test = [row for row in rows if row["target"] >= cut]
    if not past or not test:
        raise ValueError("both chronological splits need eligible candles")
    side = "UP" if sum(r["label"] == "UP" for r in past) >= sum(r["label"] == "DOWN" for r in past) else "DOWN"
    labels = [r["label"] for r in test]
    baseline = metrics([side] * len(test), labels)
    old = metrics([r["legacy_lo"] for r in test], labels)
    candidate = metrics([r["candidate"] for r in test], labels)
    matched = [r for r in test if r["candidate"] in ("UP", "DOWN")]
    matched_labels = [r["label"] for r in matched]
    matched_old = metrics([r["legacy_lo"] for r in matched], matched_labels)
    matched_constant = metrics([side] * len(matched), matched_labels)
    floor = max(52.0, baseline["hit_rate"], old["hit_rate"] or 0.0,
                matched_old["hit_rate"] or 0.0, matched_constant["hit_rate"] or 0.0)
    return {"bars": len(frame), "split": cut.isoformat(), "first": frame.index[0].isoformat(),
            "last": frame.index[-1].isoformat(), "held_out": len(test),
            "constant_side": side, "constant": baseline, "legacy_lo": old,
            "legacy_lo_on_candidate_bars": matched_old, "constant_on_candidate_bars": matched_constant,
            "candidate": candidate, "passes_screen": candidate["signals"] >= MIN_SIGNALS
            and candidate["wilson_99_lower"] > floor}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    report = {"version": RULE_VERSION, "source": "ExpertOption SMARTY /verify/history",
              "asset_id": 240, "target_offset": TARGET_OFFSET, "frames": {}}
    for frame, seconds in FRAMES.items():
        try:
            report["frames"][frame] = evaluate(load_smarty(args.input / f"{frame}.json", seconds, now), seconds)
        except (OSError, KeyError, ValueError) as exc:
            report["frames"][frame] = {"error": str(exc)}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for frame, row in report["frames"].items():
        print(frame, row.get("candidate"), row.get("legacy_lo"), row.get("passes_screen"), row.get("error"), flush=True)


if __name__ == "__main__":
    main()
