"""Telegram delivery: signal cards with real chart images and result cards."""

from __future__ import annotations

import io
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup

from ..bot import texts
from ..engines.signals.generator import SignalDraft

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot: Bot | None, chat_id: str):
        self.bot = bot
        self.chat_id = str(chat_id or "").strip()

    @property
    def enabled(self) -> bool:
        return self.bot is not None and bool(self.chat_id)

    async def send_signal(self, draft: SignalDraft, signal_id: int, chart: bytes | None, ai_note: str, ai_state: str) -> bool:
        caption = texts.signal_card(draft, ai_note=ai_note, ai_state=ai_state)
        caption = _fit(caption)
        if chart:
            return await self._photo(chart, caption, f"signal-{signal_id}.png")
        return await self._text(caption)

    async def send_result(self, payload: dict, chart: bytes | None) -> bool:
        caption = _fit(texts.result_card({**payload, "exit": payload.get("exit")}))
        if chart:
            return await self._photo(chart, caption, f"result-{payload['id']}.png")
        return await self._text(caption)

    async def send_text(self, text: str, keyboard: InlineKeyboardMarkup | None = None) -> bool:
        return await self._text(text, keyboard)

    async def _photo(self, image: bytes, caption: str, filename: str) -> bool:
        if not self.enabled:
            log.info("telegram disabled: skipping photo %s", filename)
            return False
        try:
            await self.bot.send_photo(  # type: ignore[union-attr]
                chat_id=self.chat_id,
                photo=BufferedInputFile(image, filename=filename),
                caption=caption,
                parse_mode="HTML",
            )
            return True
        except TelegramAPIError as exc:
            log.warning("telegram photo failed (%s): %s", exc.__class__.__name__, exc)
            return await self._text(caption if not image else caption + "\n\n<i>(تعذر إرفاق الصورة)</i>")

    async def _text(self, text: str, keyboard: InlineKeyboardMarkup | None = None) -> bool:
        if not self.enabled:
            log.info("telegram disabled: skipping text message")
            return False
        try:
            await self.bot.send_message(  # type: ignore[union-attr]
                chat_id=self.chat_id,
                text=_fit(text),
                parse_mode="HTML",
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
            return True
        except TelegramAPIError as exc:
            log.warning("telegram send failed (%s): %s", exc.__class__.__name__, exc)
            return False


def _fit(text: str, limit: int = 1000) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rsplit("\n", 1)[0] + "\n<i>…</i>"


def png_file(image: bytes, name: str) -> BufferedInputFile:
    return BufferedInputFile(io.BytesIO(image).read(), filename=name)
