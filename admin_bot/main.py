"""ROZLF AI admin bot entrypoint: activation codes and subscriptions only."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramConflictError
from aiogram.types import BotCommand

from admin_bot import handlers
from admin_bot.middleware import OwnerOnlyMiddleware
from bot import formatting as fmt
from config import settings
from database.repository import Repository

logger = logging.getLogger("rozlf.admin")


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


async def notification_loop(bot: Bot, repo: Repository, owners: frozenset[int]) -> None:
    while True:
        try:
            pending = await repo.pending_notifications()
            for item in pending:
                text = fmt.admin_notification_text(item.payload)
                errors: list[str] = []
                delivered = 0
                for owner in owners:
                    try:
                        await bot.send_message(owner, text, disable_web_page_preview=True)
                        delivered += 1
                    except Exception as exc:  # owner may not have started the bot yet
                        errors.append(f"{owner}:{type(exc).__name__}")
                        logger.warning("admin notification to %s failed: %s", owner, exc)
                if delivered:
                    await repo.mark_notification_sent(item.id)
                else:
                    logger.warning("notification %s kept queued: %s", item.id, ",".join(errors) or "no owners")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("admin notification loop error")
        await asyncio.sleep(3)


async def run() -> None:
    setup_logging()
    if not settings.admin_bot_token:
        logger.error("ADMIN_BOT_TOKEN is missing; admin bot cannot start")
        return
    owners = settings.owner_ids
    if not owners:
        logger.error("OWNER_TELEGRAM_IDS is missing; refusing to start an unprotected admin bot")
        return

    repo = Repository(settings)
    await repo.init()
    bot = Bot(
        token=settings.admin_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(repo=repo)
    dp.message.outer_middleware(OwnerOnlyMiddleware(owners))
    dp.callback_query.outer_middleware(OwnerOnlyMiddleware(owners))
    dp.include_router(handlers.router)

    async def on_startup() -> None:
        try:
            await bot.delete_webhook(drop_pending_updates=False)
            await bot.set_my_commands(
                [
                    BotCommand(command="start", description="لوحة إدارة الاشتراكات"),
                    BotCommand(command="id", description="عرض معرف المالك"),
                ]
            )
        except Exception:
            logger.exception("admin bot startup call failed; continuing")
        logger.info("ROZLF admin bot ready for owners=%s", sorted(owners))

    dp.startup.register(on_startup)
    notifier = asyncio.create_task(notification_loop(bot, repo, owners), name="admin-notifier")
    attempt = 0
    try:
        while True:
            try:
                await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), handle_signals=attempt == 0)
                break
            except TelegramConflictError:
                attempt += 1
                logger.error("admin bot token is polling elsewhere; retrying in 20s")
                await asyncio.sleep(20)
    finally:
        notifier.cancel()
        try:
            await notifier
        except (asyncio.CancelledError, Exception):
            pass
        await repo.close()
        await bot.session.close()


def main() -> None:
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
