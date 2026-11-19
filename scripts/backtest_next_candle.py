"""Research-only walk-forward replay of first-unopened ExpertOption candles.

The forecast uses only completed, contiguous candles. The outcome is the
direction of bar i+2, not a broker settlement or a simulated trade.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import Counter, defaultdict
from hashlib import sha256
from heapq import heappop, heappush
from math import isfinite
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import pandas as pd

from engines.technical.delivery_window import PREPUBLISH_SECONDS
from engines.technical.next_candle import CALIBRATION_PATH, DEFAULT_BINS, MIN_CALIBRATION_SAMPLES, score_at
from engines.technical.regime_candle import TARGET_OFFSET
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
MAX_FEATURE_BARS = 299  # 300 provider rows minus the forming bar
MIN_SETTLED_HISTORY = 300
SCREENING_HIT_RATE = 52.0  # Historical research screen, not a break-even threshold.
METHOD = ("Expanding walk-forward by instrument, frame and score direction; "
          "learn only from labels closed strictly before the forecast; target bar i+2.")


def _direction(score: float) -> str | None:
    return "UP" if score > 0 else "DOWN" if score < 0 else None


def _bucket_key(score: float, bins=DEFAULT_BINS) -> tuple[str, int] | None:
    if not isfinite(score) or not (side := _direction(score)):
        return None
    for i, (low, high) in enumerate(zip(bins, bins[1:])):
        if low <= abs(score) < high:
            return side, i
    return None


def _bucket_table(records: list[dict], bins=DEFAULT_BINS) -> list[dict]:
    counts = defaultdict(Counter)
    for row in records:
        if (key := _bucket_key(row["score"], bins)) is not None:
            counts[key][row["target"]] += 1
    return [
        {"direction": side, "low": bins[i], "high": bins[i + 1],
         "n": sum(bucket.values()), "hits": bucket[side], "draws": bucket["DRAW"]}
        for (side, i), bucket in sorted(counts.items())
    ]


def _stats(rows: list[dict]) -> dict:
    decided = [r for r in rows if r["prediction"] in ("UP", "DOWN")]
    wins = sum(r["prediction"] == r["target"] for r in decided)
    draws = sum(r["target"] == "DRAW" for r in decided)
    return {
        "signals": len(decided),
        "wins": wins,
        "draws": draws,
        "hit_rate": round(100 * wins / len(decided), 2) if decided else None,
        "coverage": round(100 * len(decided) / len(rows), 2) if rows else 0.0,
    }


def _decode_candles(body: dict, market: str, asset_id: int, tf: str) -> list[Candle]:
    if (not isinstance(body, dict) or body.get("source") != "ExpertOption"
            or body.get("asset_id") != asset_id or body.get("market") != market
            or body.get("timeframe") != f"{FRAMES[tf]}s"):
        raise ValueError("bridge response is not for the requested source, instrument and native frame")
    return [
        Candle(
            time=datetime.fromisoformat(row["time"].replace("Z", "+00:00")),
            open=float(row["open"]), high=float(row["high"]),
            low=float(row["low"]), close=float(row["close"]),
        )
        for row in body.get("candles") or []
    ]


async def _fetch(session: aiohttp.ClientSession, base: str, market: str,
                 asset_id: int, tf: str, limit: int) -> list[Candle]:
    params = {"id": asset_id, "timeframe": tf, "limit": limit, "ts": str(time.time())}
    for attempt in range(3):
        try:
            async with session.get(f"{base}/verify/history", params=params, timeout=90) as resp:
                if resp.status != 200:
                    return []
                candles = _decode_candles(await resp.json(content_type=None), market, asset_id, tf)
            if candles:
                return candles
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError, AttributeError):
            pass
        if attempt < 2:
            await asyncio.sleep(1.5 * (attempt + 1))
    return []


def _samples(frame: pd.DataFrame, market: str, tf: str, now=None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    step = timedelta(seconds=FRAMES[tf])
    times = frame.index
    if times.tz is None or times.has_duplicates or not times.is_monotonic_increasing:
        raise ValueError("candle timestamps must be unique, increasing and timezone-aware")
    frame = frame.loc[times + step <= now]
    times = frame.index
    # A broken candle acts like a gap. Neither the feature window nor the
    # target can straddle one, even if the last 15 bars appear contiguous.
    block_start = 0
    last_side = []
    rows = []
    for i, prices in enumerate(frame[["open", "high", "low", "close"]].itertuples(index=False, name=None)):
        op, hi, lo, cl = prices
        if not (all(isfinite(p) and p > 0 for p in prices)
                and hi >= max(op, cl) and lo <= min(op, cl)):
            block_start = i + 1
            last_side.append(None)
            continue
        if i and times[i] - times[i - 1] != step:
            block_start = i
        last_side.append("UP" if cl > op else "DOWN" if cl < op else "DRAW")

        feature_idx = i - TARGET_OFFSET
        if feature_idx - block_start + 1 < MIN_HISTORY:
            continue
        left = max(block_start, feature_idx + 1 - MAX_FEATURE_BARS)
        score, components = score_at(frame.iloc[left:feature_idx + 1])
        if not isfinite(score):
            continue
        rows.append({
            "time": (times[feature_idx] + step).isoformat(),
            "target_open": times[i].isoformat(),
            "settled_at": (times[i] + step).isoformat(),
            "market": market, "timeframe": tf, "asset": "",
            "score": score, "target": last_side[i], "last_candle": last_side[feature_idx],
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


def _timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("forecast and settlement timestamps must carry a timezone")
    return result


def _walk_forward(rows: list[dict]) -> tuple[dict, list[dict]]:
    """The signed buckets learn only from labels known at each decision."""
    groups = {(row.get("market"), row.get("asset"), row.get("timeframe")) for row in rows}
    if len(groups) > 1:
        raise ValueError("walk-forward expects exactly one instrument and timeframe")
    tested = []
    prior = defaultdict(Counter)
    outcomes = Counter()
    pending = []

    ordered = sorted(((_timestamp(r["time"]), i, r) for i, r in enumerate(rows)))
    for at, index, row in ordered:
        settled = _timestamp(row["settled_at"])
        target = row["target"]
        if settled <= at or target not in ("UP", "DOWN", "DRAW"):
            raise ValueError("each forecast requires a valid outcome that closes after the decision")
        while pending and pending[0][0] < at:
            _, _, key, past_target = heappop(pending)
            outcomes[past_target] += 1
            if key is not None:
                prior[key][past_target] += 1
        key = _bucket_key(row["score"])
        heappush(pending, (settled, index, key, target))
        bucket = prior.get(key, Counter())
        n = sum(bucket.values())
        side = _direction(row["score"])
        majority = "UP" if outcomes["UP"] >= outcomes["DOWN"] else "DOWN"
        confidence = (100 * bucket[side] / n
                      if key is not None and n >= MIN_CALIBRATION_SAMPLES
                      and sum(outcomes.values()) >= MIN_SETTLED_HISTORY else None)
        prediction = side if confidence is not None and confidence >= SCREENING_HIT_RATE else "NO TRADE"
        tested.append(dict(row, prediction=prediction, confidence=confidence,
                           direction=side, past_majority=majority, bucket_samples=n))
    return _stats(tested), tested


def _summary(rows: list[dict], walk: list[dict]) -> dict:
    selected = [r for r in walk if r["prediction"] in ("UP", "DOWN")]
    probabilities = [r for r in walk if r["confidence"] is not None]
    baselines = {
        "always_up": "UP", "always_down": "DOWN",
        "past_majority": "past_majority", "last_candle": "last_candle",
    }
    matched = {}
    for name, side in baselines.items():
        predictions = [r.get(side) if side not in ("UP", "DOWN") else side for r in selected]
        # A flat previous candle falls back to the majority known at decision
        # time, keeping the comparison on exactly the same selected targets.
        wins = sum((p if p in ("UP", "DOWN") else r["past_majority"]) == r["target"]
                   for p, r in zip(predictions, selected))
        matched[name] = {"wins": wins, "signals": len(selected),
                         "hit_rate": round(100 * wins / len(selected), 2) if selected else None}
    brier = sum((r["confidence"] / 100 - (r["direction"] == r["target"])) ** 2 for r in probabilities)
    return {
        "samples": len(rows),
        "strategies_exploratory": _strategy_rows(rows),
        "walk_forward": _stats(walk),
        "matched_baselines": matched,
        "probability_check": {"samples": len(probabilities),
                              "brier": round(brier / len(probabilities), 6) if probabilities else None},
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://worker-production-03c94.up.railway.app")
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--as-of", help="ISO 8601 cutoff with timezone (default: replay start time)")
    parser.add_argument("--snapshot-dir", type=Path,
                        help="Replay saved /verify/history responses named ASSET_ID-FRAME.json")
    parser.add_argument("--output", default="docs/NEXT-CANDLE-BACKTEST.json")
    parser.add_argument("--calibration", default="docs/NEXT-CANDLE-CALIBRATION-CANDIDATE.json")
    parser.add_argument("--frames", default="1min,5min,15min")
    parser.add_argument("--market", choices=tuple(ASSETS), help="Analyze only the selected market")
    args = parser.parse_args()
    frames = [item.strip() for item in args.frames.split(",") if item.strip()]
    if args.limit < 1:
        parser.error("--limit must be positive")
    if not frames or any(item not in FRAMES for item in frames):
        parser.error("Unsupported native candle timeframe")
    output = Path(args.output)
    cal_path = Path(args.calibration)
    markdown = output.with_suffix(".md")
    outputs = {output.resolve(), cal_path.resolve(), markdown.resolve()}
    if len(outputs) != 3 or CALIBRATION_PATH.resolve() in outputs:
        parser.error("Use distinct research paths; the production calibration must not be overwritten.")
    all_rows: dict[str, list[dict]] = defaultdict(list)
    raw_meta = {}
    try:
        as_of = _timestamp(args.as_of).astimezone(timezone.utc) if args.as_of else datetime.now(timezone.utc)
    except ValueError as exc:
        parser.error(str(exc))
    async with aiohttp.ClientSession(trust_env=True) as session:
        for market, assets in ASSETS.items():
            if args.market and market != args.market:
                continue
            for tf in frames:
                for asset_id, symbol in assets:
                    snapshot_hash = None
                    if args.snapshot_dir is None:
                        candles = await _fetch(session, args.base_url, market, asset_id, tf, args.limit)
                    else:
                        try:
                            payload = (args.snapshot_dir / f"{asset_id}-{tf}.json").read_bytes()
                            candles = _decode_candles(json.loads(payload), market, asset_id, tf)[-args.limit:]
                            snapshot_hash = sha256(payload).hexdigest()
                        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                            print(f"skip {market} {symbol} {tf}: invalid or missing snapshot ({type(exc).__name__})",
                                  flush=True)
                            continue
                    if len(candles) < MIN_HISTORY + TARGET_OFFSET:
                        print(f"skip {market} {symbol} {tf}: {len(candles)} candles", flush=True)
                        continue
                    try:
                        if any(a.time >= b.time for a, b in zip(candles, candles[1:])):
                            raise ValueError("duplicate or unordered source timestamps")
                        rows = _samples(frame_from_candles(candles), market, tf, now=as_of)
                    except (TypeError, ValueError) as exc:
                        print(f"skip {market} {symbol} {tf}: {exc}", flush=True)
                        continue
                    for row in rows:
                        row["asset"] = symbol
                    key = f"{market}:{symbol}:{tf}"
                    all_rows[key] = rows
                    raw_meta[key] = {
                        "asset_id": asset_id,
                        "candles": len(candles),
                        "first": candles[0].time.isoformat(),
                        "last": candles[-1].time.isoformat(),
                        "snapshot_sha256": snapshot_hash,
                    }
                    print(f"ok {market} {symbol} {tf}: {len(candles)} candles -> {len(rows)} samples", flush=True)

    report = {
        "as_of": as_of.isoformat(),
        "source": "ExpertOption bridge /verify/history (native OHLC, read-only)",
        "method": METHOD,
        "limits": "Candle-motion research only. No broker entry/settlement prices, actual payouts or delivery latency.",
        "assets": raw_meta,
        "results": {},
    }
    calibration = {
        "schema": "next-candle-research-v3",
        "target_offset": TARGET_OFFSET,
        "as_of": report["as_of"],
        "source": report["source"],
        "method": METHOD,
        "min_samples": MIN_CALIBRATION_SAMPLES,
        "status": "research_only",
        "instruments": {},  # Deliberately incompatible with live market-level calibration.
    }
    for key, rows in sorted(all_rows.items()):
        tf = key.rsplit(":", 1)[1]
        if not rows:
            continue
        _, walk_rows = _walk_forward(rows)
        summary = _summary(rows, walk_rows)
        summary["manual_lead_possible"] = FRAMES[tf] > PREPUBLISH_SECONDS
        report["results"][key] = summary
        calibration["instruments"][key] = {
            "samples": len(rows),
            "buckets": _bucket_table(rows),
        }

    if not report["results"]:
        raise SystemExit("No supported frame returned eligible real samples; no calibration was written.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    cal_path.parent.mkdir(parents=True, exist_ok=True)
    cal_path.write_text(json.dumps(calibration, indent=2) + "\n", encoding="utf-8")
    _write_markdown(report, markdown)
    print(f"wrote {output} and {cal_path}", flush=True)


def _write_markdown(report: dict, path: Path) -> None:
    lines = [
        "# Next-Candle Walk-Forward Replay", "",
        f"As of `{report['as_of']}`.", "",
        "Features use bars ending at `i`, and the target is the first unopened bar, `i+2`.",
        "Only strictly earlier settled labels teach the instrument's signed score buckets.",
        "All baselines use the very same selected candles; draws count as misses for everyone.", "",
        "| Market / Instrument / TF | Samples | Selected | Forecast | Always UP | Always DOWN | Past majority | Previous candle |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def pct(value):
        return f"{value:.2f}%" if value is not None else "—"

    for key, result in sorted(report["results"].items()):
        wf, bases = result["walk_forward"], result["matched_baselines"]
        columns = [pct(bases[name]["hit_rate"])
                   for name in ("always_up", "always_down", "past_majority", "last_candle")]
        lines.append(f"| {key} | {result['samples']} | {wf['signals']} | {pct(wf['hit_rate'])} | "
                     + " | ".join(columns) + " |")
    lines += ["", report["limits"],
              "The 52% research screen is not a profitability threshold, and results cannot enable live signals."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
