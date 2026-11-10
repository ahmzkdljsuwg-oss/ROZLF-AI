"""Shared application container wired once at startup."""
from __future__ import annotations

from dataclasses import dataclass

from aiogram import Bot

from ai.mistral import MistralClient
from config import Settings
from database.repository import Repository
from engines.signals.generator import SignalGenerator
from providers.catalog import Market, assets_for
from providers.registry import DataSourceRegistry
from providers.inventory import MarketInventory
from services.health import MarketHealthService
from services.scanner import AutoScanner
from services.signal_tracker import SignalTracker


@dataclass
class AppContext:
    settings: Settings
    bot: Bot
    registry: DataSourceRegistry
    repo: Repository
    generator: SignalGenerator
    mistral: MistralClient
    inventory: MarketInventory | None = None
    health: MarketHealthService | None = None
    tracker: SignalTracker | None = None
    scanner: AutoScanner | None = None

    def source_map(self) -> dict[str, str]:
        sources: dict[str, str] = {}
        for market in (
            Market.FOREX, Market.GOLD, Market.OTC, Market.SMARTY,
            Market.AI, Market.FOOTBALL, Market.LUXURY,
        ):
            assets = assets_for(market)
            if not assets:
                continue
            sources[market.value] = self.registry.source_summary(assets[0])
        return sources

    def ai_health(self) -> dict:
        return self.mistral.health()

    async def market_health(self, force: bool = False) -> dict:
        if self.health is None:
            return {}
        return await self.health.snapshot(force=force)


_context: AppContext | None = None


def set_context(context: AppContext) -> None:
    global _context
    _context = context


def get_context() -> AppContext:
    if _context is None:
        raise RuntimeError("Application context is not initialised")
    return _context
