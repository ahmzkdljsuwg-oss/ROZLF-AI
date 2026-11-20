"""Compare five research rules against matched baselines on bridge snapshots."""
from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path

from engines.backtest.five_rules import RULES, TARGET_OFFSET, replay
from engines.technical.delivery_window import PREPUBLISH_SECONDS
from engines.technical.indicators import frame_from_candles
from engines.technical.next_candle import CALIBRATION_PATH
from scripts.backtest_next_candle import ASSETS, FRAMES, _decode_candles, _timestamp


def _snapshot(path: Path, market: str, asset_id: int, symbol: str, frame: str):
    raw = path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("invalid bridge envelope")
    if not payload.get("candles"):
        raise ValueError(f"no source candles ({payload.get('code') or 'no error code'})")
    if payload.get("symbol") != symbol:
        raise ValueError("source instrument symbol does not match")
    if payload.get("connected") is not True or payload.get("active") is not True:
        raise ValueError("instrument not active or bridge disconnected on capture")
    candles = _decode_candles(payload, market, asset_id, frame)
    if any(a.time >= b.time for a, b in zip(candles, candles[1:])):
        raise ValueError("duplicate or unordered source candles")
    return frame_from_candles(candles), sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot_dir", type=Path, help="Unmodified bridge JSON: ASSET_ID-FRAME.json")
    parser.add_argument("--as-of", required=True, type=_timestamp)
    parser.add_argument("--evaluate-from", type=_timestamp, help="Reject decisions made before this timestamp")
    parser.add_argument("--market", action="append", choices=tuple(ASSETS), help="Repeat to include multiple markets")
    parser.add_argument("--asset", action="append", type=int, help="Repeat to select specific instrument IDs")
    parser.add_argument("--frames", default="30sec,1min,5min")
    parser.add_argument("--payout", default=.80, type=float, help="Hypothetical payout ratio, not actual broker payout")
    parser.add_argument("--cost", default=0., type=float, help="Hypothetical cost per unit per forecast")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frames = tuple(dict.fromkeys(item.strip() for item in args.frames.split(",") if item.strip()))
    if not frames or any(frame not in FRAMES for frame in frames):
        parser.error("unsupported native timeframe")
    if not (0 < args.payout <= 1 and 0 <= args.cost < args.payout):
        parser.error("payout must be in (0, 1]; cost must be nonnegative and below payout")
    if args.evaluate_from is not None and args.evaluate_from >= args.as_of:
        parser.error("evaluation start must precede the settlement cutoff")
    if args.output.resolve() == CALIBRATION_PATH.resolve():
        parser.error("research output must not overwrite live calibration")

    run = {
        "mode": "research_only",
        "as_of": args.as_of.isoformat(),
        "evaluate_from": args.evaluate_from.isoformat() if args.evaluate_from else None,
        "target_offset": TARGET_OFFSET,
        "scenario": {"payout": args.payout, "cost": args.cost, "draw_before_cost": 0},
        "strategies": list(RULES),
        "limits": "Candle direction only, no account return, delivery times or broker settlement. "
                  "Periods and instruments can overlap. No strategy is promoted.",
        "results": {}, "unavailable": {},
    }
    for market in args.market or ASSETS:
        for asset_id, symbol in ASSETS[market]:
            if args.asset and asset_id not in args.asset:
                continue
            for tf in frames:
                key = f"{market}:{symbol}:{tf}"
                try:
                    frame, digest = _snapshot(args.snapshot_dir / f"{asset_id}-{tf}.json", market, asset_id, symbol, tf)
                    result = replay(frame, FRAMES[tf], as_of=args.as_of, evaluate_from=args.evaluate_from,
                                    payout=args.payout, cost=args.cost)
                except FileNotFoundError:
                    run["unavailable"][key] = "no snapshot"
                    continue
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    run["unavailable"][key] = str(exc)
                    continue
                run["results"][key] = {
                    "asset_id": asset_id, "snapshot_sha256": digest,
                    "manual_lead_possible": FRAMES[tf] > PREPUBLISH_SECONDS, **result,
                }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(run, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Replayed {len(run['results'])} instrument/frames; {len(run['unavailable'])} unavailable.")
    if not any(row["eligible"] for row in run["results"].values()):
        raise SystemExit("No valid targets in the requested window; no strategy result.")


if __name__ == "__main__":
    main()
