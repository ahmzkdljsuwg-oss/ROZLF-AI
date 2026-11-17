"""Walk-forward test of next-candle prediction on real ExpertOption candles.

Every prediction at bar ``i`` uses bars ``0..i`` only. The next bar ``i+1`` is
skipped because it is already open. Bar i+2 is the realised label. Confidence calibration is fitted on past
samples only, then applied to the current sample (expanding walk-forward).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import defaultdict
from collections import Counter
from heapq import heappop, heappush
from math import isfinite
from datetime import timedelta
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import pandas as pd

from engines.technical.next_candle import DEFAULT_BINS, MIN_CALIBRATION_SAMPLES, _series, score_at
from engines.technical.indicators import frame_from_candles
from providers.base import Candle

ASSETS = {
    "otc": [(273, "AUDUSD_OTC"), (274, "USDCAD_OTC"), (275, "NZDUSD_OTC")],
    "smarty": [(240, "SMRTY")],
    "football": [(278, "FOOTBALL_INDEX_OTC_R")],
    "luxury": [(286, "LUXURY_INDEX_OTC_R")],
    "ai": [(285, "AI_INDEX_OTC_R")],
    "cricket": [(276, "CRICKET_INDEX_OTC_R")],
    "forex": [(142, "EURUSD"), (248, "USDJPY"), (250, "GBPUSD")],
    "gold": [(251, "XAUUSD")],
}
FRAMES = {"5sec": 5, "30sec": 30, "1min": 60, "2min": 120, "3min": 180, "5min": 300, "15min": 900}
MIN_HISTORY = 220


def _bucket_table(records: list[dict], bins=DEFAULT_BINS) -> list[dict]:
    table = []
    for low, high in zip(bins, bins[1:]):
        rows = [r for r in records if low <= r["abs_score"] < high]
        if not rows:
            continue
        table.append({
            "low": low, "high": high, "n": len(rows),
            "up_wins": sum(1 for r in rows if r["target"] == "UP"),
            "down_wins": sum(1 for r in rows if r["target"] == "DOWN"),
            "draws": sum(1 for r in rows if r["target"] == "DRAW"),
        })
    return table


def _lookup(table: list[dict], score: float, min_n: int = MIN_CALIBRATION_SAMPLES) -> dict | None:
    for row in table:
        if row["low"] <= abs(score) < row["high"]:
            return row if row["n"] >= min_n else None
    return None


def _stats(rows: list[dict]) -> dict:
    decided = [r for r in rows if r["prediction"] in ("UP", "DOWN")]
    wins = sum(1 for r in decided if r["prediction"] == r["target"])
    draws = sum(1 for r in decided if r["target"] == "DRAW")
    return {
        "signals": len(decided),
        "wins": wins,
        "draws": draws,
        "hit_rate": round(100 * wins / max(len(decided), 1), 2),
        "coverage": round(100 * len(decided) / max(len(rows), 1), 2),
    }


async def _fetch(session: aiohttp.ClientSession, base: str, asset_id: int, tf: str, limit: int) -> list[Candle]:
    params = {"id": asset_id, "timeframe": tf, "limit": limit, "ts": str(time.time())}
    for attempt in range(3):
        try:
            async with session.get(f"{base}/verify/history", params=params, timeout=90) as resp:
                body = await resp.json(content_type=None)
            if (resp.status != 200 or body.get("source") != "ExpertOption" or body.get("asset_id") != asset_id
                    or body.get("timeframe") != f"{FRAMES[tf]}s"):
                return []
            raw = body.get("candles") or []
            if raw:
                return [
                    Candle(
                        time=datetime.fromisoformat(row["time"].replace("Z", "+00:00")),
                        open=float(row["open"]), high=float(row["high"]),
                        low=float(row["low"]), close=float(row["close"]),
                    )
                    for row in raw
                ]
        except Exception:
            pass
        await asyncio.sleep(1.5 * (attempt + 1))
    return []


def _samples(frame: pd.DataFrame, market: str, tf: str, now=None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    step = timedelta(seconds=FRAMES[tf])
    frame = frame.loc[frame.index + step <= now]
    arrays = _series(frame)
    rows = []
    for index in range(MIN_HISTORY, len(frame) - 1):
        # Live uses the first unopened bar. At close of index, index+1 is
        # already open, so its OHLC is neither a feature nor the target.
        position = index + 2
        if position >= len(frame) or frame.index[position] - frame.index[index] != 2 * step:
            continue
        if any(b - a != step for a,b in zip(frame.index[index-15:index], frame.index[index-14:index+1])):
            continue
        score, components = score_at(frame, arrays, index)
        target_close = float(frame["close"].iloc[position])
        target_open = float(frame["open"].iloc[position])
        if not (isfinite(target_close) and isfinite(target_open) and target_close > 0 and target_open > 0):
            continue
        target = "UP" if target_close > target_open else "DOWN" if target_close < target_open else "DRAW"
        rows.append({
            "time": (frame.index[index]+step).isoformat(),
            "settled_at": (frame.index[position]+step).isoformat(),
            "market": market, "timeframe": tf, "asset": "",
            "score": score, "abs_score": abs(score), "target": target,
            "components": components,
        })
    return rows


def _strategy_rows(rows: list[dict]) -> dict[str, dict]:
    def direct(value, threshold=1.0):
        if value > threshold:
            return "UP"
        if value < -threshold:
            return "DOWN"
        return "NO TRADE"

    rules = {
        "trend": lambda c: direct(c.get("trend", 0.0), 3.0),
        "momentum": lambda c: direct(c.get("momentum", 0.0), 1.5),
        "price_action": lambda c: direct(c.get("price_action", 0.0), 1.5),
        "location_reversion": lambda c: direct(-c.get("location", 0.0), 1.0),
        "combo_raw": lambda c: direct(sum(c.values()), 4.0),
    }
    outputs = {}
    for name, rule in rules.items():
        projected = [dict(r, prediction=rule(r["components"])) for r in rows]
        outputs[name] = _stats(projected)
    return outputs


def _walk_forward(rows: list[dict]) -> tuple[dict, list[dict]]:
    """Calibrate on past rows, predict the next row, then add it to history."""
    tested = []
    prior = defaultdict(Counter)
    pending = []
    seen = 0
    edges = list(zip(DEFAULT_BINS, DEFAULT_BINS[1:]))

    def bucket_key(score):
        return next((i for i,(low,high) in enumerate(edges) if low <= abs(score) < high), None)

    for index, row in enumerate(sorted(rows, key=lambda r: r["time"])):
        # Across markets/assets, rows at the same timestamp cannot train
        # each other; realized labels become eligible only after settlement.
        while pending and pending[0][0] < row["time"]:
            _, _, group, target = heappop(pending)
            prior[group][target] += 1
            seen += 1
        group = bucket_key(row["score"])
        if group is not None:
            heappush(pending, (row["settled_at"], index, group, row["target"]))
        bucket = prior[group]
        n = sum(bucket.values())
        if seen < 300 or n < MIN_CALIBRATION_SAMPLES:
            tested.append(dict(row, prediction="NO TRADE", confidence=None))
            continue
        up = (bucket["UP"] + 0.5 * bucket["DRAW"]) / n
        direction = "UP" if row["score"] > 0 else "DOWN"
        confidence = 100 * (up if direction == "UP" else 1 - up)
        prediction = direction if confidence >= 52.0 else "NO TRADE"
        tested.append(dict(row, prediction=prediction, confidence=round(confidence, 2)))
    return _stats(tested), tested


def _summary(rows: list[dict], walk: list[dict]) -> dict:
    baseline_up = 100 * sum(1 for r in rows if r["target"] == "UP") / max(
        sum(1 for r in rows if r["target"] in ("UP", "DOWN")), 1
    )
    return {
        "samples": len(rows),
        "baseline_always_up": round(baseline_up, 2),
        "strategies": _strategy_rows(rows),
        "combo_walk_forward": _stats(walk),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://worker-production-03c94.up.railway.app")
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--output", default="docs/NEXT-CANDLE-BACKTEST.json")
    parser.add_argument("--calibration", default="docs/NEXT-CANDLE-CALIBRATION-CANDIDATE.json")
    parser.add_argument("--frames", default="1min,5min,15min")
    parser.add_argument("--market", choices=tuple(ASSETS), help="Analyze only the selected market")
    args = parser.parse_args()
    frames = [item.strip() for item in args.frames.split(",") if item.strip()]
    if not frames or any(item not in FRAMES for item in frames):
        parser.error("Unsupported native candle timeframe")
    if Path(args.calibration).resolve() == Path("engines/technical/calibration.json").resolve():
        parser.error("Write a candidate calibration. Production calibration must be reviewed separately.")
    all_rows: dict[str, list[dict]] = defaultdict(list)
    raw_meta = defaultdict(dict)
    async with aiohttp.ClientSession() as session:
        for market, assets in ASSETS.items():
            if args.market and market != args.market:
                continue
            for tf in frames:
                for asset_id, symbol in assets:
                    candles = await _fetch(session, args.base_url, asset_id, tf, args.limit)
                    if len(candles) < MIN_HISTORY + 2:
                        print(f"skip {market} {symbol} {tf}: {len(candles)} candles", flush=True)
                        continue
                    frame = frame_from_candles(candles)
                    rows = _samples(frame, market, tf)
                    for row in rows:
                        row["asset"] = symbol
                    all_rows[f"{market}:{tf}"].extend(rows)
                    raw_meta[f"{market}:{tf}"][symbol] = {
                        "candles": len(candles),
                        "first": candles[0].time.isoformat(),
                        "last": candles[-1].time.isoformat(),
                    }
                    print(f"ok {market} {symbol} {tf}: {len(candles)} candles -> {len(rows)} samples", flush=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "ExpertOption bridge /verify/history (real OHLC, read-only)",
        "method": "expanding walk-forward; features use bars <= i; first unopened target is i+2; train on settled past labels only",
        "assets": raw_meta,
        "results": {},
    }
    calibration = {
        "version": 2,
        "target_offset": 2,
        "generated_at": report["generated_at"],
        "source": report["source"],
        "method": report["method"],
        "min_samples": MIN_CALIBRATION_SAMPLES,
        "markets": {},
    }
    for key, rows in sorted(all_rows.items()):
        market, tf = key.split(":")
        rows.sort(key=lambda r: r["time"])
        if len(rows) < 400:
            print(f"skip report {key}: {len(rows)} samples", flush=True)
            continue
        walk_stats, walk_rows = _walk_forward(rows)
        summary = _summary(rows, walk_rows)
        summary["walk_forward_rows"] = walk_stats
        report["results"][key] = summary
        table = _bucket_table(rows)
        calibration["markets"].setdefault(market, {})[tf] = {
            "samples": len(rows),
            "enabled": False,  # candidate only; promotion requires review
            "walk_forward": walk_stats,
            "baseline_always_up": summary["baseline_always_up"],
            "bins": table,
        }

    if not report["results"]:
        raise SystemExit("No supported frame returned enough real samples; no calibration was written.")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    cal_path = Path(args.calibration)
    cal_path.parent.mkdir(parents=True, exist_ok=True)
    cal_path.write_text(json.dumps(calibration, indent=2), encoding="utf-8")
    _write_markdown(report, output.with_suffix(".md"))
    print(f"wrote {output} and {cal_path}", flush=True)


def _write_markdown(report: dict, path: Path) -> None:
    lines = [
        "# Next-Candle Walk-Forward Backtest",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "Real ExpertOption OHLC from the read-only bridge. Every prediction uses bars `0..i`;",
        "the target is bar `i+1`. Calibration is expanding and applied out of sample.",
        "",
        "| Market / TF | Samples | Baseline UP | Combo walk-forward | Coverage |",
        "|---|---:|---:|---:|---:|",
    ]
    for key, result in sorted(report["results"].items()):
        wf = result["walk_forward_rows"]
        lines.append(
            f"| {key} | {result['samples']} | {result['baseline_always_up']:.2f}% | "
            f"{wf['hit_rate']:.2f}% ({wf['wins']}/{wf['signals']}) | {wf['coverage']:.1f}% |"
        )
    lines += ["", "## Strategy comparison (same samples)", "",
              "| Market / TF | Trend | Momentum | Price action | Location | Combo raw |",
              "|---|---:|---:|---:|---:|---:|"]
    for key, result in sorted(report["results"].items()):
        s = result["strategies"]
        lines.append(
            f"| {key} | {s['trend']['hit_rate']:.1f}%/{s['trend']['signals']} | "
            f"{s['momentum']['hit_rate']:.1f}%/{s['momentum']['signals']} | "
            f"{s['price_action']['hit_rate']:.1f}%/{s['price_action']['signals']} | "
            f"{s['location_reversion']['hit_rate']:.1f}%/{s['location_reversion']['signals']} | "
            f"{s['combo_raw']['hit_rate']:.1f}%/{s['combo_raw']['signals']} |"
        )
    lines += ["", "Hit rate is wins / verified signals (draws are not wins). Coverage is signals / samples."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
