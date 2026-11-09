"""Application container: one place that wires settings, data, AI and delivery."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from aiogram import Bot

from ..ai.mistral import MistralClient
from ..config import Settings
from ..database.repository import SignalRepository
from ..engines.signals.generator import RiskPolicy
from ..engines.signals.scanner import SignalScanner
from ..engines.signals.statistics import StatisticsService
from ..engines.signals.tracker import SignalTracker
from ..providers.base import MARKET_FOREX, MARKET_OTC, MARKET_SMARTY
from ..providers.registry import DataSourceRegistry
from .notifier import TelegramNotifier
from .signal_service import SignalService

log = logging.getLogger(__name__)


@dataclass
class RuntimeState:
    auto_enabled: bool = False
    scanning: bool = False
    last_scan_at: int = 0
    last_resolve_at: int = 0
    last_error: str = ""
    started_at: int = field(default_factory=lambda: int(time.time()))

    def snapshot(self) -> dict:
        return {
            "auto_enabled": self.auto_enabled,
            "scanning": self.scanning,
            "last_scan_at": self.last_scan_at,
            "last_resolve_at": self.last_resolve_at,
            "last_error": self.last_error,
            "uptime_seconds": int(time.time()) - self.started_at,
        }


class AppContainer:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.state = RuntimeState()
        self.registry = DataSourceRegistry.from_settings(settings)
        self.repo: SignalRepository | None = None
        self.ai = MistralClient(settings)
        self.policy = RiskPolicy(
            min_score=settings.min_signal_score,
            cooldown_minutes=settings.signal_cooldown_minutes,
            max_per_scan=settings.max_signals_per_scan,
        )
        self.scanner = SignalScanner(self.registry, self.policy)
        self.tracker = SignalTracker(self.registry, None)  # type: ignore[arg-type]
        self.service: SignalService | None = None
        self.stats: StatisticsService | None = None
        self.notifier = TelegramNotifier(None, settings.telegram_chat_id)
        self.bot: Bot | None = None

    async def startup(self, bot: Bot | None = None) -> None:
        self.repo = await SignalRepository.create(self.settings.database_url)
        self.tracker = SignalTracker(self.registry, self.repo)
        self.service = SignalService(self.registry, self.repo, self.scanner, self.tracker, self.ai, self.policy)
        self.stats = StatisticsService(self.repo)
        self.bot = bot
        self.service.notifier = self.notifier
        self.notifier.bot = bot
        if not self.notifier.enabled:
            log.warning("TELEGRAM_CHAT_ID غير مضبوط: لن تُرسل الإشارات إلى Telegram تلقائياً.")

    async def shutdown(self) -> None:
        await self.registry.close()
        await self.ai.close()
        if self.repo:
            await self.repo.close()
        if self.bot:
            await self.bot.session.close()

    async def readiness(self) -> dict:
        markets = await self.registry.market_overview()
        fx = next((m for m in markets if m["market"] == MARKET_FOREX), {})
        otc = next((m for m in markets if m["market"] == MARKET_OTC), {})
        smarty = next((m for m in markets if m["market"] == MARKET_SMARTY), {})
        return {
            "forex_ready": bool(fx.get("available")),
            "otc_ready": bool(otc.get("available")),
            "smarty_ready": bool(smarty.get("available")),
            "ai_ready": self.ai.configured,
            "markets": markets,
        }
