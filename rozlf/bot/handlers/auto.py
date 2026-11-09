from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from ...services.container import AppContainer
from .. import keyboards
from ..utils import edit_or_send

log = logging.getLogger(__name__)
router = Router(name="auto")


async def auto_text(container: AppContainer) -> str:
    state = "مُفعّل" if container.state.auto_enabled else "متوقف"
    return (
        "<b>الماسح الآلي</b>\n\n"
        f"الحالة: <b>{state}</b>\n"
        f"الدورة كل {container.settings.scanner_interval_seconds} ثانية\n"
        f"أعلى {container.settings.max_signals_per_scan} إشارات في الدورة\n"
        f"أدنى درجة {container.settings.min_signal_score} · تبريد {container.settings.signal_cooldown_minutes} دقيقة\n\n"
        "يبحث في FOREX وOTC وSMARTY معاً، ولا يُنشر إلا ما حقق الشروط كاملة."
    )


@router.callback_query(F.data == "auto:menu")
async def cb_auto_menu(query: CallbackQuery, container: AppContainer) -> None:
    await edit_or_send(
        query.message,  # type: ignore[arg-type]
        await auto_text(container),
        keyboards.auto_menu(container.state.auto_enabled, container.settings.scanner_interval_seconds),
    )
    await query.answer()


@router.callback_query(F.data == "auto:toggle")
async def cb_auto_toggle(query: CallbackQuery, container: AppContainer) -> None:
    container.state.auto_enabled = not container.state.auto_enabled
    await edit_or_send(
        query.message,  # type: ignore[arg-type]
        await auto_text(container),
        keyboards.auto_menu(container.state.auto_enabled, container.settings.scanner_interval_seconds),
    )
    await query.answer("تم التشغيل" if container.state.auto_enabled else "تم الإيقاف")


@router.callback_query(F.data == "auto:scan")
async def cb_auto_scan(query: CallbackQuery, container: AppContainer) -> None:
    if container.state.scanning:
        await query.answer("هناك مسح جارٍ الآن", show_alert=True)
        return
    await query.answer("جارٍ المسح…")
    container.state.scanning = True
    try:
        summary = await container.service.scan_and_publish()  # type: ignore[union-attr]
    finally:
        container.state.scanning = False
    lines = ["<b>نتيجة المسح</b>"]
    for row in summary["results"]:
        icon = "🟢" if row["available"] else "🔴"
        detail = f" · {row['detail']}" if row["detail"] else ""
        lines.append(f"{icon} {row['market']}: {len(row['signals'])} إشارة · {row['skipped']} مرفوض{detail[:80]}")
    lines.append(f"\nتم نشر {len(summary['published'])} إشارة.")
    await query.message.answer(  # type: ignore[union-attr]
        "\n".join(lines), reply_markup=keyboards.auto_menu(container.state.auto_enabled, container.settings.scanner_interval_seconds)
    )


@router.callback_query(F.data == "auto:interval")
async def cb_auto_interval(query: CallbackQuery, container: AppContainer) -> None:
    await query.answer(
        f"الفاصل {container.settings.scanner_interval_seconds} ثانية — يُضبط عبر SCANNER_INTERVAL_SECONDS.",
        show_alert=True,
    )


@router.message(Command("scan"))
async def cmd_scan_auto(message: Message, container: AppContainer) -> None:
    container.state.auto_enabled = True
    await message.answer(
        "تم تفعيل المسح الآلي.", reply_markup=keyboards.auto_menu(True, container.settings.scanner_interval_seconds)
    )


@router.message(Command("stop"))
async def cmd_stop(message: Message, container: AppContainer) -> None:
    container.state.auto_enabled = False
    await message.answer("تم إيقاف المسح الآلي.")
