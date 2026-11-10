"""Run the causal backtester on real Yahoo Forex candles.

Usage: .venv/bin/python -m scripts.backtest_forex [--pairs EURUSD,GBPUSD]
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from engines.backtest.runner import BacktestConfig, run_backtest, walk_forward
from providers.catalog import FOREX_ASSETS, get_asset, timeframe
from providers.yahoo import YahooForexProvider

PLAN = (
    ("1min", (60, 300)),
    ("5min", (300, 900)),
)


async def main(pairs: list[str]) -> int:
    provider = YahooForexProvider()
    results = []
    try:
        for key in pairs:
            asset = get_asset(key)
            if asset is None or asset.market.value.upper() != "FOREX":
                print(f"skip unknown forex asset {key}")
                continue
            for frame_code, expiries in PLAN:
                tf = timeframe(frame_code)
                try:
                    candles = await provider.fetch_candles(asset, tf, limit=300)
                except Exception as exc:  # noqa: BLE001 - report data failures honestly
                    print(f"{asset.symbol} {frame_code}: DATA UNAVAILABLE ({exc})")
                    continue
                for expiry in expiries:
                    config = BacktestConfig(asset, tf, expiry, step_bars=2)
                    result = run_backtest(config, candles, "yahoo")
                    payload = result.as_dict()
                    payload["walk_forward"] = walk_forward(result.trades)
                    results.append(payload)
                    m = result.metrics
                    print(
                        f"{asset.symbol} {frame_code} exp={expiry}s bars={len(candles)} "
                        f"trades={m.trades} win={m.win_rate} pf={m.profit_factor} "
                        f"exp={m.expectancy:.3f} dd={m.max_drawdown:.1f}"
                    )
    finally:
        await provider.close()
    out = Path("docs/backtest-results.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"wrote {out} ({len(results)} runs)")
    return 0 if results else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", default=",".join(asset.key for asset in FOREX_ASSETS[:5]))
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main([p.strip() for p in args.pairs.split(",") if p.strip()])))
