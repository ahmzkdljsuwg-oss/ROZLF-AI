from __future__ import annotations

import time

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ... import __version__
from ...services.container import AppContainer

router = Router(name="commands")


@router.message(Command("ping"))
async def cmd_ping(message: Message) -> None:
    await message.answer("pong")


@router.message(Command("version"))
async def cmd_version(message: Message) -> None:
    await message.answer(f"ROZLF AI v{__version__}")


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(
        f"chat_id: <code>{message.chat.id}</code>\nالاستخدام: <code>TELEGRAM_CHAT_ID={message.chat.id}</code>",
    )


@router.message(Command("health"))
async def cmd_health(message: Message, container: AppContainer) -> None:
    ready = await container.readiness()
    stats = await container.stats.overview()  # type: ignore[union-attr]
    state = container.state.snapshot()
    await message.answer(
        "<b>الحالة</b>\n"
        f"FOREX: {'🟢' if ready['forex_ready'] else '🔴'} · "
        f"OTC: {'🟢' if ready['otc_ready'] else '🔴'} · "
        f"SMARTY: {'🟢' if ready['smarty_ready'] else '🔴'} · "
        f"Mistral: {'🟢' if ready['ai_ready'] else '🔴'}\n"
        f"الماسح: {'مُفعّل' if state['auto_enabled'] else 'متوقف'} · uptime {state['uptime_seconds']}s\n"
        f"الإشارات: {stats.get('total', 0)} (مفتوحة {stats.get('open', 0)}) · دقة {stats.get('accuracy') or '—'}\n"
        f"آخر مسح: {state['last_scan_at'] or '—'} · آخر حسم: {state['last_resolve_at'] or '—'}\n"
        f"آخر خطأ: {state['last_error'] or '—'}",
    )
