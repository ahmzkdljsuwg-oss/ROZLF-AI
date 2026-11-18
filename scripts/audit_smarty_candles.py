"""Read-only replay of exact SMARTY candles. Never promotes a model to production."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from engines.technical.delivery_window import PREPUBLISH_SECONDS
from engines.technical.fast import analyze_fast
from engines.technical.next_candle import _lo_components, _series, _technical_forecast, score_at
from providers.base import Candle, MarketData, ValidationReport
from providers.catalog import SMARTY_ASSET, timeframe
from scripts.replay_smarty_regime import FRAMES, load_smarty, metrics

LOOKBACK = 300


def audit(frame, code):
    tf = timeframe(code)
    step = timedelta(seconds=tf.seconds)
    cutoff = int(len(frame) * .6)
    groups = (frame.index.to_series().diff() != step).cumsum().to_numpy()
    bars = [Candle(t.to_pydatetime(), row.open, row.high, row.low, row.close) for t,row in frame.iterrows()]
    if cutoff < LOOKBACK:
        raise ValueError("Not enough candles for separate warm-up and test segments")
    prior = bars[LOOKBACK:cutoff-2]
    majority = "UP" if sum(b.close > b.open for b in prior) >= sum(b.close < b.open for b in prior) else "DOWN"
    labels, methods = [], {"constant": [], "lo": [], "fast": [], "agreement": []}
    for i in range(max(LOOKBACK, cutoff - 2), len(bars) - 2):
        target = bars[i + 2]
        if groups[i - LOOKBACK + 1] != groups[i + 2]:
            continue
        # Simulated decision time is the close of i plus a fixed 200 ms.
        # i+1 is already forming and its prices never enter the predictor.
        now = bars[i].time + step + timedelta(milliseconds=200)
        window = frame.iloc[i-LOOKBACK+1:i+1]
        arrays = _series(window)
        score, parts = score_at(window, arrays)
        score, parts = _lo_components(window, arrays, score, parts)
        lo = _technical_forecast(score, parts, target.time, tf.seconds, []).direction
        data = MarketData(SMARTY_ASSET, tf, bars[i-LOOKBACK+1:i+1], "ExpertOption",
                          None, ValidationReport(True, LOOKBACK), fetched_at=now)
        fast = analyze_fast(data, now).direction
        y = "UP" if target.close > target.open else "DOWN" if target.close < target.open else "DRAW"
        labels.append(y)
        methods["constant"].append(majority)
        methods["lo"].append(lo)
        methods["fast"].append(fast)
        methods["agreement"].append(fast if fast == lo else "NO TRADE")
    summaries = {name: metrics(predictions, labels) for name,predictions in methods.items()}
    for name, predictions in methods.items():
        if name != "constant":
            eligible = [label for predicted,label in zip(predictions,labels) if predicted in ("UP","DOWN")]
            baseline = metrics([majority] * len(eligible), eligible)
            summaries[name]["constant_same_bars_pct"] = baseline["hit_rate"]
            lower = summaries[name]["wilson_99_lower"]
            summaries[name]["exploratory_screen"] = bool(
                lower is not None and len(eligible) >= 100
                and lower > max(52.0, baseline["hit_rate"] or 0.0))
    return {"bars": len(bars), "holdout_start": frame.index[cutoff].isoformat(),
            "holdout_end": frame.index[-1].isoformat(), "eligible": len(labels),
            "can_offer_manual_target": tf.seconds > PREPUBLISH_SECONDS, "methods": summaries}


def main():
    args = argparse.ArgumentParser(__doc__)
    args.add_argument("--data", type=Path, required=True)
    args.add_argument("--output", type=Path, required=True)
    opts = args.parse_args()
    now = datetime.now(timezone.utc)
    report = {"source": "ExpertOption SMARTY asset 240",
              "sample": "Saved native OHLC snapshot; exploratory historical evaluation, not a new prospective trial.",
              "target": "i+2, forecast uses only the 300 completed bars through i",
              "frames": {key:audit(load_smarty(opts.data / f"{key}.json", secs, now),key)
                         for key,secs in FRAMES.items()}}
    opts.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for frame,row in report["frames"].items():
        print(frame, row["eligible"], {k:(t["wins"],t["signals"],t["hit_rate"],t.get("exploratory_screen"))
                                        for k,t in row["methods"].items()})


if __name__ == "__main__":
    main()
