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
from bot.keyboards import menus as keyboards
from bot.middleware.auth import AccessMiddleware
from config import normalise_database_url, settings
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
        live = state.get("ctx") or ctx
        payload = {
            "status": "ok" if not state.get("error") else "degraded",
            "service": "ROZLF AI",
            "role": settings.role,
            "polling": state.get("polling", False),
            "stage": state.get("stage"),
            "telegram_configured": bool(settings.telegram_bot_token),
            "database_driver": normalise_database_url(settings.database_url).split(":", 1)[0],
            "scanner": bool(live.scanner and live.scanner.running) if live else False,
            "scanner_last_run": str(live.scanner.last_run) if live and live.scanner and live.scanner.last_run else None,
            "sources": live.source_map() if live else {},
            "ai": live.mistral.configured if live else settings.mistral_enabled,
            "bridge_configured": bool(settings.bridge_url and settings.eo_bridge_key),
            "build": os.getenv("ROZLF_BUILD_SHA") or os.getenv("RAILWAY_GIT_COMMIT_SHA") or "unknown",
            "menu_version": "M3",
            "menu": [
                {"text": button.text, "callback": button.callback_data}
                for row in keyboards.main_menu().inline_keyboard
                for button in row
            ],
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
    state["health_started"] = True
    state["runner"] = runner
    logger.info("health server listening on :%s (role=%s)", settings.port, settings.role)
    return runner


async def _keep_alive_after_failure(state: dict) -> None:
    """If Telegram/DB init fails, keep serving health so the failure is visible."""
    runner = None
    if settings.port and not state.get("health_started"):
        app = web.Application()

        async def health(_request: web.Request) -> web.Response:
            return web.json_response(
                {
                    "status": "degraded",
                    "service": "ROZLF AI",
                    "role": settings.role,
                    "polling": False,
                    "stage": state.get("stage"),
                    "error": state.get("error"),
                }
            )

        app.router.add_get("/", health)
        app.router.add_get("/health", health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", settings.port)
        await site.start()
    try:
        await asyncio.Event().wait()
    finally:
        if runner is not None:
            await runner.cleanup()


async def _run_bot(state: dict) -> None:
    setup_logging()
    runner = await _health_server(None, state)

    if settings.web_only:
        if not settings.port:
            logger.error("web role requires PORT; exiting")
            sys.exit(1)
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
        logger.error("TELEGRAM_BOT_TOKEN is missing for role %s; keeping health endpoint only", settings.role)
        state["stage"] = "no-telegram-token"
        await asyncio.Event().wait()
        return

    state["stage"] = "database"
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

    state["ctx"] = ctx

    async def on_startup() -> None:
        try:
            await bot.delete_webhook(drop_pending_updates=False)
        except Exception:
            logger.exception("could not clear a stale Telegram webhook")
        menu_fingerprint = " | ".join(
            f"{button.text}={button.callback_data}"
            for row in keyboards.main_menu().inline_keyboard
            for button in row
        )
        logger.info("ROZLF MENU M3 READY: %s", menu_fingerprint)
        try:
            await bot.set_my_commands(
                [
                    BotCommand(command="start", description="فتح لوحة التحكم"),
                    BotCommand(command="markets", description="فتح قائمة الأسواق"),
                    BotCommand(command="status", description="حالة البيانات والذكاء الاصطناعي"),
                    BotCommand(command="scan", description="فتح الماسح التلقائي"),
                    BotCommand(command="stats", description="الإحصائيات"),
                    BotCommand(command="id", description="عرض CHAT ID"),
                ]
            )
        except Exception:
            logger.exception("could not publish bot commands; continuing")
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


async def main() -> None:
    state: dict = {"polling": False, "stage": "starting", "error": None}
    try:
        await _run_bot(state)
    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:
        logger.exception("ROZLF AI startup failed")
        state["error"] = f"{type(exc).__name__}"
        state["stage"] = "failed"
        await _keep_alive_after_failure(state)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
