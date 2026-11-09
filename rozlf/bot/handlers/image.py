from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from ...ai.mistral import AIResult
from ...services.container import AppContainer
from .. import keyboards
from ..utils import edit_or_send

log = logging.getLogger(__name__)
router = Router(name="image")

MAX_BYTES = 10 * 1024 * 1024
ALLOWED = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


@router.callback_query(F.data == "img:start")
async def cb_image_start(query: CallbackQuery, container: AppContainer) -> None:
    ready = container.ai.supports_vision()
    note = "" if ready else "\n\n<b>تنبيه:</b> موديل الصور الحالي غير معروف بدعم الصور؛ اضبط MISTRAL_VISION_MODEL على موديل يقبل الصور."
    await edit_or_send(  # type: ignore[arg-type]
        query.message,
        "<b>تحليل صورة شارت</b>\n\n"
        "أرسل الصورة الآن (PNG / JPG / WEBP، حتى 10MB).\n"
        "لا تُستخرج أسعار لحظية من صورة قديمة، والتحليل بصري فقط."
        + note,
        keyboards.image_prompt(),
    )
    await query.answer()


@router.message(F.photo)
async def on_photo(message: Message, container: AppContainer) -> None:
    sizes = sorted(message.photo, key=lambda p: p.file_size or 0)
    file_id = sizes[-1].file_id
    await _analyze(message, container, file_id, "image/jpeg")


@router.message(F.document)
async def on_document(message: Message, container: AppContainer) -> None:
    doc = message.document
    mime = (doc.mime_type or "").lower()
    if mime not in ALLOWED:
        await message.answer("الصيغة غير مدعومة. المدعوم: PNG / JPG / WEBP.", reply_markup=keyboards.back_to_menu())
        return
    if (doc.file_size or 0) > MAX_BYTES:
        await message.answer("الصورة كبيرة جداً (الحد 10MB).", reply_markup=keyboards.back_to_menu())
        return
    await _analyze(message, container, doc.file_id, mime)


async def _analyze(message: Message, container: AppContainer, file_id: str, mime: str) -> None:
    status = await message.answer("⏳ جارٍ قراءة الصورة…")
    try:
        file = await message.bot.download(file_id)  # type: ignore[union-attr]
        data = file.read()
    except Exception as exc:  # download failures must not crash the bot
        log.warning("image download failed: %s", exc.__class__.__name__)
        await status.edit_text("تعذر تحميل الصورة من Telegram. أعد المحاولة.")
        return
    if len(data) > MAX_BYTES:
        await status.edit_text("الصورة كبيرة جداً (الحد 10MB).")
        return

    result = await container.ai.analyze_chart(data, mime, note=message.caption or "")
    await status.edit_text(_format(result), reply_markup=keyboards.back_to_menu())


def _format(result: AIResult) -> str:
    if not result.ok:
        return f"<b>تعذر تحليل الصورة</b>\n<code>{result.code}</code>\n{result.text}"
    data = result.data or {}
    if not data:
        return f"<b>قراءة بصرية</b>\n{result.text}"
    quality = str(data.get("quality") or "unknown")
    lines = [f"<b>تحليل الصورة</b> · جودة {quality}", ""]
    if data.get("trend"):
        lines.append(f"الاتجاه: <b>{data['trend']}</b>")
    for key, label in (("support", "دعم"), ("resistance", "مقاومة")):
        levels = data.get(key) or []
        if levels:
            lines.append(f"{label}: {', '.join(str(x) for x in levels[:5])}")
    for key, label in (
        ("patterns", "نماذج"),
        ("liquidity_zones", "مناطق سيولة"),
        ("reversal_zones", "مناطق انعكاس محتملة"),
    ):
        items = data.get(key) or []
        if items:
            lines.append(f"{label}: {'; '.join(str(x) for x in items[:5])}")
    if data.get("summary"):
        lines.append(f"\n{data['summary']}")
    if data.get("request_new_image"):
        lines.append("\n⚠️ جودة الصورة غير كافية — أرسل صورة أوضح وأقرب للشموع.")
    lines.append("\n<i>التحليل من الصورة فقط، وليس أسعاراً لحظية.</i>")
    return "\n".join(lines)
