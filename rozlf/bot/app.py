"""Bot bootstrap: dispatcher, background loops and polling."""

from __future__ import annotations

import asyncio
import contextlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError

from ..config import Settings
from ..logging_setup import setup_logging
from ..services.container import AppContainer
from ..services.health import start_server
from .handlers import ROUTERS
from .middlewares import AccessMiddleware, ThrottleMiddleware

log = logging.getLogger(__name__)

RESOLVE_INTERVAL = 20
RECONNECT_DELAY = 5


def build_dispatcher(container: AppContainer) -> Dispatcher:
    dp = Dispatcher(container=container)
    dp.message.middleware(AccessMiddleware(container.settings))
    dp.callback_query.middleware(AccessMiddleware(container.settings))
    dp.message.middleware(ThrottleMiddleware())
    for router in ROUTERS:
        dp.include_router(router)
    return dp


async def _resolver_loop(container: AppContainer, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            resolved = await container.service.resolve_due()  # type: ignore[union-attr]
            container.state.last_resolve_at = int(asyncio.get_running_loop().time())
            if resolved:
                log.info("resolved %s signals", len(resolved))
        except Exception as exc:  # resolver must survive any provider error
            container.state.last_error = f"resolve: {exc.__class__.__name__}: {exc}"
            log.exception("resolver loop error")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=RESOLVE_INTERVAL)


async def _scanner_loop(container: AppContainer, stop: asyncio.Event) -> None:
    interval = max(30, container.settings.scanner_interval_seconds)
    while not stop.is_set():
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval)
        if stop.is_set():
            break
        if not container.state.auto_enabled or container.state.scanning:
            continue
        container.state.scanning = True
        try:
            summary = await container.service.scan_and_publish()  # type: ignore[union-attr]
            container.state.last_scan_at = int(asyncio.get_running_loop().time())
            log.info("auto scan published %s signals", len(summary["published"]))
        except Exception as exc:
            container.state.last_error = f"scan: {exc.__class__.__name__}: {exc}"
            log.exception("scanner loop error")
        finally:
            container.state.scanning = False


async def run_bot(settings: Settings) -> None:
    setup_logging(settings.log_level)
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN غير مضبوط.")

    container = AppContainer(settings)
    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await container.startup(bot)
    dp = build_dispatcher(container)

    runner = await start_server(container, settings.port)
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(_resolver_loop(container, stop), name="resolver"),
        asyncio.create_task(_scanner_loop(container, stop), name="scanner"),
    ]

    try:
        me = await bot.get_me()
        log.info("bot started as @%s", me.username)
    except TelegramUnauthorizedError:
        await stop_background(tasks, stop, runner, container, bot)
        raise SystemExit("TELEGRAM_BOT_TOKEN غير صالح.")
    except TelegramNetworkError as exc:
        log.warning("telegram network error at startup: %s", exc.__class__.__name__)

    try:
        while True:
            try:
                await dp.start_polling(bot, handle_signals=False, polling_timeout=25, close_bot_session=False)
                break
            except TelegramNetworkError as exc:
                log.warning("polling disconnected (%s); retrying in %ss", exc.__class__.__name__, RECONNECT_DELAY)
                await asyncio.sleep(RECONNECT_DELAY)
    finally:
        await stop_background(tasks, stop, runner, container, bot)


async def stop_background(tasks, stop: asyncio.Event, runner, container: AppContainer, bot: Bot) -> None:
    stop.set()
    for task in tasks:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    with contextlib.suppress(Exception):
        await runner.cleanup()
    with contextlib.suppress(Exception):
        await container.shutdown()
    log.info("shutdown complete")
