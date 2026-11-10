"""ROZLF AI — Telegram trading-analysis bot entrypoint (polling mode)."""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramConflictError
from aiogram.types import BotCommand
from aiohttp import web

from ai.mistral import MistralClient
from bot import formatting as fmt
from bot.context import AppContext, set_context
from bot.handlers import menus
from bot.middleware.auth import AccessMiddleware
from config import settings
from database.repository import Repository
from engines.signals.generator import SignalGenerator
from providers.eobridge import ExpertOptionBridgeProvider
from providers.inventory import MarketInventory
from providers.registry import build_registry
from services.health import MarketHealthService
from services.scanner import AutoScanner
from services.signal_tracker import SignalTracker

logger = logging.getLogger("rozlf")


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def _health_server(ctx: AppContext | None, state: dict) -> web.AppRunner | None:
    if not settings.port:
        return None

    async def health(_request: web.Request) -> web.Response:
        payload = {
            "status": "ok",
            "service": "ROZLF AI",
            "role": settings.role,
            "polling": state.get("polling", False),
            "scanner": bool(ctx.scanner and ctx.scanner.running) if ctx else False,
            "scanner_last_run": str(ctx.scanner.last_run) if ctx and ctx.scanner and ctx.scanner.last_run else None,
            "sources": ctx.source_map() if ctx else {},
            "ai": ctx.mistral.configured if ctx else settings.mistral_enabled,
            "bridge_configured": bool(settings.bridge_url and settings.eo_bridge_key),
            "build": os.getenv("ROZLF_BUILD_SHA") or os.getenv("RAILWAY_GIT_COMMIT_SHA") or "unknown",
            "error": state.get("error"),
        }
        return web.json_response(payload)

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.port)
    await site.start()
    logger.info("health server listening on :%s (role=%s)", settings.port, settings.role)
    return runner


async def main() -> None:
    setup_logging()

    if settings.web_only:
        if not settings.port:
            logger.error("web role requires PORT; exiting")
            sys.exit(1)
        state: dict = {"polling": False, "error": None}
        runner = await _health_server(None, state)
        logger.info("ROZLF AI started: web health role (no Telegram polling)")
        try:
            await asyncio.Event().wait()
        finally:
            if runner is not None:
                await runner.cleanup()
        return

    problems = settings.startup_problems()
    for problem in problems:
        logger.warning("startup: %s", problem)
    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN is required; exiting")
        sys.exit(1)

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    repo = Repository(settings)
    await repo.init()
    bridge = ExpertOptionBridgeProvider(settings.bridge_url, settings.eo_bridge_key)
    registry = build_registry(settings, bridge=bridge)
    inventory = MarketInventory(bridge)
    health = MarketHealthService(registry, inventory)
    mistral = MistralClient(
        api_key=settings.mistral_api_key,
        model=settings.mistral_model,
    )
    generator = SignalGenerator(registry, repo, settings)
    ctx = AppContext(
        settings=settings,
        bot=bot,
        registry=registry,
        repo=repo,
        generator=generator,
        mistral=mistral,
        inventory=inventory,
        health=health,
    )

    async def notify_signal(record) -> None:
        chat_id = settings.telegram_chat_id or record.user_id
        if not chat_id:
            return
        try:
            await bot.send_message(chat_id, fmt.signal_text(record), disable_web_page_preview=True)
        except Exception:
            logger.exception("failed sending scanner signal to %s", chat_id)

    async def notify_verification(record) -> None:
        chat_id = settings.telegram_chat_id or record.user_id
        if not chat_id:
            return
        try:
            await bot.send_message(chat_id, fmt.verification_text(record), disable_web_page_preview=True)
        except Exception:
            logger.exception("failed sending verification to %s", chat_id)

    tracker = SignalTracker(repo, registry, notifier=notify_verification, grace_seconds=600)
    scanner = AutoScanner(generator, repo, registry, settings, notifier=notify_signal, inventory=inventory)
    ctx.tracker = tracker
    ctx.scanner = scanner
    set_context(ctx)

    access = AccessMiddleware(settings)
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)
    dp.include_router(menus.router)

    async def verification_loop() -> None:
        while True:
            try:
                verified = await tracker.verify_due()
                if verified:
                    logger.info("verified %s signal(s)", verified)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("verification loop error")
            await asyncio.sleep(settings.verification_interval_seconds)

    state: dict = {"polling": False}
    runner = await _health_server(ctx, state)

    async def on_startup() -> None:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="فتح لوحة التحكم"),
                BotCommand(command="markets", description="فتح قائمة الأسواق السبعة"),
                BotCommand(command="status", description="حالة البيانات والذكاء الاصطناعي"),
                BotCommand(command="scan", description="فتح الماسح التلقائي"),
                BotCommand(command="stats", description="الإحصائيات"),
                BotCommand(command="id", description="عرض CHAT ID"),
            ]
        )
        if settings.scanner_enabled:
            await scanner.start()
        logger.info("ROZLF AI started: %s", settings.describe())

    async def on_shutdown() -> None:
        state["polling"] = False
        await scanner.stop()
        await repo.close()
        await registry.close()
        await mistral.close()
        if runner is not None:
            await runner.cleanup()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    verify_task = asyncio.create_task(verification_loop(), name="rozlf-verifier")
    state["polling"] = True
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), handle_signals=True)
    except TelegramConflictError:
        logger.error("another bot instance is polling with the same token; stop it and restart")
    finally:
        state["polling"] = False
        verify_task.cancel()
        try:
            await verify_task
        except (asyncio.CancelledError, Exception):
            pass
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
