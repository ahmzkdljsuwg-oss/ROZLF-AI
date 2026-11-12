"""Live smoke check against real providers. No Telegram or database writes."""
from __future__ import annotations

import asyncio

from config import settings
from engines.signals.generator import supported_durations
from engines.technical.analyzer import analyze_market_data
from providers.base import DataUnavailable
from providers.catalog import assets_for, Market
from providers.registry import build_registry


async def main() -> None:
    registry = build_registry(settings)
    try:
        for market in (Market.FOREX, Market.GOLD, Market.OTC, Market.SMARTY):
            asset = assets_for(market)[0]
            print(f"\n== {asset.display} [{market.label}]")
            try:
                data = await registry.fetch(asset, "5min")
                result = analyze_market_data(data)
                print(
                    f"source={data.source} bars={len(data.candles)} valid={data.validation.is_tradeable} "
                    f"price={result.price} direction={result.direction} confidence={result.confidence}"
                )
                print("durations:", supported_durations(asset, data.timeframe))
            except DataUnavailable as exc:
                print("DATA UNAVAILABLE:", exc.message)
    finally:
        await registry.close()


if __name__ == "__main__":
    asyncio.run(main())
