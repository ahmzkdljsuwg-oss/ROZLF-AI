"""Chart image analysis through Mistral vision."""
from __future__ import annotations

import io
import logging

from aiogram import F, Router
from aiogram.types import Message

from ai.mistral import MistralUnavailable
from ai.vision import ImageRejected, prepare_image
from bot import formatting as fmt
from bot.context import get_context
from bot.keyboards import menus

logger = logging.getLogger(__name__)
router = Router(name="images")

IMAGE_MIME = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


async def _analyse(message: Message, payload: bytes, mime: str) -> None:
    ctx = get_context()
    status = await message.answer("🔍 ANALYSING CHART IMAGE...")
    try:
        prepared = prepare_image(payload)
    except ImageRejected as exc:
        await status.edit_text(
            f"<b>🖼 IMAGE REJECTED</b>\n\n{exc.reason}\n\n"
            "أرسل صورة شارت أوضح (PNG / JPG / JPEG / WEBP).",
            reply_markup=menus.image_help_back(),
        )
        return

    if not ctx.mistral.configured:
        await status.edit_text(
            "<b>🖼 IMAGE ANALYSIS</b>\n\n"
            "MISTRAL AI NOT CONFIGURED — تحليل الصور يتطلب MISTRAL_API_KEY.\n"
            "تم فحص الصورة بنجاح لكن لا يمكن تحليلها بدون نموذج الرؤية.",
            reply_markup=menus.image_help_back(),
        )
        return

    try:
        report = await ctx.mistral.analyse_image(prepared.data, prepared.mime_type)
    except MistralUnavailable as exc:
        logger.warning("vision failure: %s", exc)
        await status.edit_text(
            f"<b>🖼 IMAGE ANALYSIS</b>\n\n⚠️ تعذر تحليل الصورة الآن.\nDETAIL: {exc}\n\nحاول لاحقاً أو أرسل صورة أوضح.",
            reply_markup=menus.image_help_back(),
        )
        return

    text = (
        "<b>ROZLF AI — IMAGE ANALYSIS</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{report}\n\n"
        "<i>تحليل بصري للصورة المرسلة. لا يستخرج البوت سعراً حياً من صورة، "
        "ولا تُعد هذه النتيجة إشارة مؤكدة.</i>\n\n"
        f"<i>{fmt.DISCLAIMER}</i>"
    )
    await status.edit_text(text, reply_markup=menus.image_help_back(), disable_web_page_preview=True)


@router.message(F.photo)
async def on_photo(message: Message) -> None:
    photo = message.photo[-1]
    ctx = get_context()
    buffer = io.BytesIO()
    await ctx.bot.download(photo, destination=buffer)
    await _analyse(message, buffer.read(), "image/jpeg")


@router.message(F.document)
async def on_document(message: Message) -> None:
    document = message.document
    if document is None or not document.mime_type:
        return
    if document.mime_type.lower() not in IMAGE_MIME:
        return
    ctx = get_context()
    buffer = io.BytesIO()
    await ctx.bot.download(document, destination=buffer)
    await _analyse(message, buffer.read(), document.mime_type.lower())
