"""Walk-forward test of next-candle prediction on real ExpertOption candles.

Every prediction at bar ``i`` uses bars ``0..i`` only. The next bar ``i+1`` is
used solely as the realised label. Confidence calibration is fitted on past
samples only, then applied to the current sample (expanding walk-forward).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp
import pandas as pd

from engines.validation import validate_candles
from engines.technical.next_candle import DEFAULT_BINS, MIN_CALIBRATION_SAMPLES, _series, score_at
from engines.technical.indicators import frame_from_candles
from providers.base import Candle
from providers.catalog import timeframe

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
FRAMES = {"1min": 60, "5min": 300, "15min": 900}
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
            "predicted_up_n": sum(1 for r in rows if r.get("prediction") == "UP"),
            "predicted_up_wins": sum(1 for r in rows
                                      if r.get("prediction") == "UP" and r["target"] == "UP"),
            "predicted_down_n": sum(1 for r in rows if r.get("prediction") == "DOWN"),
            "predicted_down_wins": sum(1 for r in rows
                                        if r.get("prediction") == "DOWN" and r["target"] == "DOWN"),
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
        "hit_rate": round(100 * wins / len(decided), 2) if decided else None,
        "coverage": round(100 * len(decided) / max(len(rows), 1), 2),
    }


def _wilson_lower_bound(wins: int, trials: int, z: float = 1.96) -> float:
    """95% Wilson lower bound; draws count as non-wins for this conservative gate."""
    if trials <= 0:
        return 0.0
    p = wins / trials
    z2 = z * z
    denominator = 1 + z2 / trials
    center = p + z2 / (2 * trials)
    margin = z * ((p * (1 - p) / trials + z2 / (4 * trials * trials)) ** 0.5)
    return max(0.0, (center - margin) / denominator)


async def _fetch(session: aiohttp.ClientSession, base: str, asset_id: int, tf: str, limit: int) -> list[Candle]:
    params = {"id": asset_id, "timeframe": tf, "limit": limit, "ts": str(time.time())}
    for attempt in range(3):
        try:
            async with session.get(f"{base}/verify/history", params=params, timeout=90) as resp:
                body = await resp.json(content_type=None)
            if not _history_matches(body, asset_id, tf):
                detail = (body.get("market"), body.get("symbol"), body.get("timeframe"), body.get("active"))
                print(f"skip {asset_id} {tf}: source metadata mismatch {detail}", flush=True)
                return []
            raw = body.get("candles") or []
            if raw:
                candles = [
                    Candle(
                        time=datetime.fromisoformat(row["time"].replace("Z", "+00:00")),
                        open=float(row["open"]), high=float(row["high"]),
                        low=float(row["low"]), close=float(row["close"]),
                    )
                    for row in raw
                ]
                candles.sort(key=lambda candle: candle.time)
                validation = validate_candles(
                    candles, timeframe(tf), min_bars=MIN_HISTORY + 2
                )
                if not validation.ok or validation.stale:
                    print(f"skip {asset_id} {tf}: invalid or stale history {validation.summary}", flush=True)
                    return []
                return candles
        except Exception as exc:
            if attempt == 2:
                print(f"history fetch failed for {asset_id} {tf}: {type(exc).__name__}: {exc}", flush=True)
        await asyncio.sleep(1.5 * (attempt + 1))
    return []


def _history_matches(payload: dict, asset_id: int, tf: str) -> bool:
    """Reject data served for another, inactive, or differently timed asset."""
    if not isinstance(payload, dict):
        return False
    expected_market = next(
        (market for market, assets in ASSETS.items()
         if any(item_id == asset_id for item_id, _ in assets)), None
    )
    expected_symbol = next(
        (symbol for assets in ASSETS.values() for item_id, symbol in assets if item_id == asset_id), None
    )
    if expected_market is None or expected_symbol is None:
        return False
    normalize = lambda value: "".join(ch for ch in str(value).upper() if ch.isalnum())
    try:
        response_seconds = int(str(payload.get("timeframe", "")).removesuffix("s"))
    except ValueError:
        return False
    return (
        payload.get("asset_id") == asset_id
        and str(payload.get("market", "")).lower() == expected_market
        and normalize(payload.get("symbol", "")) == normalize(expected_symbol)
        and response_seconds == FRAMES[tf]
        and payload.get("active") is True
        and payload.get("connected") is True
    )


def _samples(frame: pd.DataFrame, market: str, tf: str, horizon_bars: int = 1) -> list[dict]:
    arrays = _series(frame)
    rows = []
    for index in range(MIN_HISTORY, len(frame) - horizon_bars):
        score, components = score_at(frame, arrays, index)
        target_close = float(frame["close"].iloc[index + horizon_bars])
        target_open = float(frame["open"].iloc[index + horizon_bars])
        target = "UP" if target_close > target_open else "DOWN" if target_close < target_open else "DRAW"
        rows.append({
            "time": frame.index[index].isoformat(),
            "decision_time": (frame.index[index] + timedelta(seconds=FRAMES[tf])).isoformat(),
            "target_time": (frame.index[index + horizon_bars]
                            + timedelta(seconds=FRAMES[tf])).isoformat(),
            "market": market, "timeframe": tf, "asset": "",
            "score": score, "abs_score": abs(score), "target": target,
            "components": components, "horizon_bars": horizon_bars,
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


def _walk_forward(rows: list[dict], payout_ratio: float = 0.80,
                  cost_per_trade: float = 0.0) -> tuple[dict, list[dict]]:
    """Calibrate on past rows, predict the next row, then add it to history."""
    tested = []
    prior: list[dict] = []
    pending: list[dict] = []
    index = 0
    while index < len(rows):
        # Multiple assets often share the same timestamp. Do not let a target
        # from one asset at time T calibrate another asset's prediction at T.
        end = index + 1
        while end < len(rows) and rows[end]["time"] == rows[index]["time"]:
            end += 1
        group = rows[index:end]
        decision_time = group[0].get("decision_time", group[0]["time"])
        matured = [row for row in pending if row.get("target_time", row["time"]) <= decision_time]
        # Samples whose target candle has not closed cannot yet calibrate the
        # decision. Keep them pending until a later feature timestamp.
        pending = [row for row in pending if row not in matured]
        prior.extend(matured)
        if len(prior) < 300:
            tested.extend(dict(row, prediction="NO TRADE", confidence=None) for row in group)
        else:
            for row in group:
                score = row["score"]
                direction = "UP" if score > 0 else "DOWN" if score < 0 else "NO TRADE"
                limits = next(((low, high) for low, high in zip(DEFAULT_BINS, DEFAULT_BINS[1:])
                               if low <= abs(score) < high), None)
                bucket_rows = [
                    item for item in prior
                    if limits is not None and limits[0] <= abs(item["score"]) < limits[1]
                    and ((item["score"] > 0 and direction == "UP")
                         or (item["score"] < 0 and direction == "DOWN"))
                ]
                side_wins = sum(1 for item in bucket_rows if item["target"] == direction)
                side_count = len(bucket_rows)
                lower_bound = _wilson_lower_bound(side_wins, side_count)
                break_even = (1 + cost_per_trade) / (1 + payout_ratio)
                if (direction == "NO TRADE" or side_count < MIN_CALIBRATION_SAMPLES
                        or lower_bound <= break_even):
                    tested.append(dict(row, prediction="NO TRADE", confidence=None))
                    continue
                confidence = 100 * side_wins / side_count
                tested.append(dict(row, prediction=direction, confidence=round(confidence, 2)))
        pending.extend(group)
        index = end
    return _stats(tested), tested


def _walk_forward_legacy(rows: list[dict]) -> tuple[dict, list[dict]]:
    """Reproduce v1 expanding calibration for an apples-to-apples audit."""
    tested = []
    for index, row in enumerate(rows):
        prior = rows[:index]
        if len(prior) < 300:
            tested.append(dict(row, prediction="NO TRADE", confidence=None))
            continue
        bucket = _lookup(_bucket_table(prior), row["score"])
        if bucket is None:
            tested.append(dict(row, prediction="NO TRADE", confidence=None))
            continue
        up_rate = (bucket["up_wins"] + 0.5 * bucket["draws"]) / bucket["n"]
        direction = "UP" if row["score"] > 0 else "DOWN"
        confidence = 100 * up_rate if direction == "UP" else 100 * (1 - up_rate)
        prediction = direction if confidence >= 52.0 else "NO TRADE"
        tested.append(dict(row, prediction=prediction, confidence=round(confidence, 2)))
    return _stats(tested), tested


def _summary(rows: list[dict], walk: list[dict], payout_ratio: float, cost_per_trade: float) -> dict:
    baseline_up = 100 * sum(1 for r in rows if r["target"] == "UP") / max(
        sum(1 for r in rows if r["target"] in ("UP", "DOWN")), 1
    )
    wf = _stats(walk)
    losses = max(0, wf["signals"] - wf["wins"] - wf["draws"])
    expected_return = (
        (wf["wins"] * payout_ratio - losses - wf["signals"] * cost_per_trade) / wf["signals"]
        if wf["signals"] else None
    )
    lower_bound = _wilson_lower_bound(wf["wins"], wf["signals"])
    break_even_rate = (1 + cost_per_trade) / (1 + payout_ratio)
    return {
        "samples": len(rows),
        "baseline_always_up": round(baseline_up, 2),
        "strategies": _strategy_rows(rows),
        "strategy_comparison_note": "in-sample descriptive comparison; do not interpret as out-of-sample performance",
        "combo_walk_forward": wf,
        "payout_ratio": payout_ratio,
        "cost_per_trade": cost_per_trade,
        "expected_net_return_per_trade": round(expected_return, 4) if expected_return is not None else None,
        "wilson_95_lower_hit_rate": round(lower_bound * 100, 2),
        "break_even_hit_rate": round(break_even_rate * 100, 2),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://worker-production-03c94.up.railway.app")
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--output", default="docs/NEXT-CANDLE-BACKTEST.json")
    parser.add_argument("--calibration", default="engines/technical/calibration.json")
    parser.add_argument("--frames", default="1min,5min,15min")
    parser.add_argument("--horizon-bars", type=int, choices=(1, 2), nargs="+", default=(1, 2),
                        help="Target candle offset(s) from the last closed feature candle")
    parser.add_argument("--payout-ratio", type=float, default=0.80,
                        help="Net win payout per unit stake (default 0.80)")
    parser.add_argument("--cost-per-trade", type=float, default=0.0,
                        help="Additional cost as a fraction of stake per trade")
    args = parser.parse_args()
    if args.payout_ratio < 0 or args.cost_per_trade < 0:
        parser.error("payout ratio and cost per trade must be non-negative")
    frames = [item.strip() for item in args.frames.split(",") if item.strip()]
    all_rows: dict[str, list[dict]] = defaultdict(list)
    raw_meta = defaultdict(dict)
    async with aiohttp.ClientSession(trust_env=True) as session:
        for market, assets in ASSETS.items():
            for tf in frames:
                for asset_id, symbol in assets:
                    candles = await _fetch(session, args.base_url, asset_id, tf, args.limit)
                    if len(candles) < MIN_HISTORY + 2:
                        print(f"skip {market} {symbol} {tf}: {len(candles)} candles", flush=True)
                        continue
                    frame = frame_from_candles(candles)
                    for horizon in args.horizon_bars:
                        rows = _samples(frame, market, tf, horizon)
                        for row in rows:
                            row["asset"] = symbol
                        all_rows[f"{market}:{tf}:{horizon}"].extend(rows)
                    raw_meta[f"{market}:{tf}"][symbol] = {
                        "candles": len(candles),
                        "first": candles[0].time.isoformat(),
                        "last": candles[-1].time.isoformat(),
                    }
                    print(f"ok {market} {symbol} {tf}: {len(candles)} candles", flush=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "ExpertOption bridge /verify/history (real OHLC, read-only)",
        "method": ("expanding walk-forward grouped by timestamp; features use closed bars <= i; "
                   "target candle is i+horizon; entry at its open and one-candle expiry at its close"),
        "assets": raw_meta,
        "results": {},
    }
    calibration = {
        "version": 2,
        "generated_at": report["generated_at"],
        "source": report["source"],
        "method": report["method"],
        "min_samples": MIN_CALIBRATION_SAMPLES,
        "markets": {},
    }
    for key, rows in sorted(all_rows.items()):
        market, tf, horizon_text = key.split(":")
        horizon = int(horizon_text)
        rows.sort(key=lambda r: r["time"])
        if len(rows) < 400:
            print(f"skip report {key}: {len(rows)} samples", flush=True)
            continue
        walk_stats, walk_rows = _walk_forward(rows, args.payout_ratio, args.cost_per_trade)
        legacy_walk_stats, _ = _walk_forward_legacy(rows)
        summary = _summary(rows, walk_rows, args.payout_ratio, args.cost_per_trade)
        summary["walk_forward_rows"] = walk_stats
        summary["legacy_before_rows"] = legacy_walk_stats
        legacy_losses = max(0, legacy_walk_stats["signals"] - legacy_walk_stats["wins"]
                           - legacy_walk_stats["draws"])
        summary["legacy_expected_net_return_per_trade"] = round(
            (legacy_walk_stats["wins"] * args.payout_ratio - legacy_losses
             - legacy_walk_stats["signals"] * args.cost_per_trade)
            / legacy_walk_stats["signals"], 4
        ) if legacy_walk_stats["signals"] else None
        report["results"][key] = summary
        # Runtime confidence comes only from the predictions that were made
        # out of sample using past rows. Full-sample counts would leak future
        # target outcomes into the deployed probability table.
        out_of_sample_signals = [
            row for row in walk_rows if row["prediction"] in ("UP", "DOWN")
        ]
        table = _bucket_table(out_of_sample_signals)
        lower_bound = _wilson_lower_bound(walk_stats["wins"], walk_stats["signals"])
        break_even_rate = (1 + args.cost_per_trade) / (1 + args.payout_ratio)
        enabled = walk_stats["signals"] >= 100 and lower_bound > break_even_rate
        horizon_table = {
            "samples": len(rows),
            "horizon_bars": horizon,
            "expiry_seconds": FRAMES[tf],
            "baseline_always_up": summary["baseline_always_up"],
            "walk_forward": walk_stats,
            "payout_ratio": args.payout_ratio,
            "cost_per_trade": args.cost_per_trade,
            "wilson_95_lower_hit_rate": round(lower_bound * 100, 2),
            "break_even_hit_rate": round(break_even_rate * 100, 2),
            "enabled": enabled,
            "bins": table,
        }
        calibration["markets"].setdefault(market, {}).setdefault(tf, {}) \
            .setdefault("horizons", {})[str(horizon)] = horizon_table

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
        "Real OHLC from the read-only bridge. Features use closed bars through index `i`;",
        "entry is at the target candle open and expiry is at that candle close. Walk-forward",
        "calibration is fitted only on earlier timestamps, never peers at the same time.",
        "",
        "| Market / TF / lead | Samples | Legacy hit | Legacy EV | Corrected hit | 95% lower | Corrected EV | Signals |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, result in sorted(report["results"].items()):
        wf = result["walk_forward_rows"]
        old = result["legacy_before_rows"]
        expected = result["expected_net_return_per_trade"]
        expected_text = f"{expected:.3f}" if expected is not None else "—"
        old_hit = old["hit_rate"]
        new_hit = wf["hit_rate"]
        old_hit_text = f"{old_hit:.2f}%" if old_hit is not None else "—"
        new_hit_text = f"{new_hit:.2f}%" if new_hit is not None else "— (no trades)"
        old_ev = result.get("legacy_expected_net_return_per_trade")
        old_ev_text = f"{old_ev:+.3f}" if old_ev is not None else "—"
        lines.append(
            f"| {key} | {result['samples']} | {old_hit_text} | {old_ev_text} | "
            f"{new_hit_text} | {result['wilson_95_lower_hit_rate']:.2f}% | "
            f"{expected_text} | {wf['signals']} |"
        )
    lines += ["", "## Full-sample strategy comparison (descriptive only)", "",
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
    lines += ["", "Net EV assumes the configured payout and costs; draws return zero. Enablement requires "
              "at least 100 out-of-sample signals and a 95% Wilson lower bound above break-even. "
              "Coverage is signals / samples."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
