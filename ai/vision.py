"""Chart screenshot analysis through a Mistral vision model.

The image is validated and re-encoded locally before it is sent. The model is
only allowed to describe what is visible in the image; it is never used as a
source of live prices.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
from dataclasses import dataclass

import httpx
from PIL import Image, ImageStat, UnidentifiedImageError

logger = logging.getLogger(__name__)

API_URL = "https://api.mistral.ai/v1/chat/completions"
MAX_BYTES = 12 * 1024 * 1024
MIN_SIDE = 220
MAX_SIDE = 1800

SYSTEM_PROMPT = (
    "You are ROZLF AI's chart-image analyst. Read only what is visibly present "
    "in the screenshot. Never invent candles, indicators, prices or timeframes. "
    "If the image is not a readable trading chart, reply exactly: "
    "NOT_A_CHART: <short reason>. Otherwise answer in clear Arabic with English "
    "technical terms, using these sections: ASSET, TIMEFRAME, CANDLES, TREND, "
    "SUPPORT & RESISTANCE, BOS/CHoCH/FVG (only if visible), SCENARIO, "
    "INVALIDATION. State that the image is a snapshot and its prices are not "
    "live. If evidence is weak, say NO TRADE."
)


class VisionUnavailable(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ImageRejected(ValueError):
    pass


@dataclass(slots=True)
class PreparedImage:
    jpeg: bytes
    width: int
    height: int

    @property
    def data_url(self) -> str:
        encoded = base64.b64encode(self.jpeg).decode("ascii")
        return f"data:image/jpeg;base64,{encoded}"


def prepare_image(raw: bytes) -> PreparedImage:
    if not raw:
        raise ImageRejected("الصورة فارغة.")
    if len(raw) > MAX_BYTES:
        raise ImageRejected("حجم الصورة أكبر من 12MB.")
    try:
        with Image.open(io.BytesIO(raw)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"}:
                raise ImageRejected("الصيغة غير مدعومة. أرسل PNG أو JPG أو JPEG أو WEBP.")
            source.load()
            image = source.convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageRejected("تعذّر قراءة الصورة. أرسل صورة شارت واضحة.") from exc
    width, height = image.size
    if width < MIN_SIDE or height < MIN_SIDE:
        raise ImageRejected(f"أبعاد الصورة صغيرة جداً ({width}x{height}). الحد الأدنى {MIN_SIDE}px.")
    if max(width, height) < 400:
        raise ImageRejected("دقة الصورة منخفضة. أرسل صورة شارت أكبر.")
    grey = image.convert("L")
    if ImageStat.Stat(grey).stddev[0] < 4.0:
        raise ImageRejected("الصورة شبه فارغة أو بلا تفاصيل. أرسل صورة شارت فعلية.")
    if max(width, height) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88, optimize=True)
    return PreparedImage(jpeg=buffer.getvalue(), width=image.width, height=image.height)


def _content(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise VisionUnavailable("EMPTY_RESPONSE", "Vision model returned no choices.")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    text = str(content or "").strip()
    if not text:
        raise VisionUnavailable("EMPTY_RESPONSE", "Vision model returned an empty answer.")
    return text


class MistralVision:
    def __init__(self, api_key: str | None, model: str = "pixtral-12b-2409", client: httpx.AsyncClient | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def health(self) -> dict:
        return {"configured": self.configured, "model": self.model if self.configured else None}

    async def analyse(self, image: PreparedImage, question: str | None = None) -> str:
        if not self.api_key:
            raise VisionUnavailable("KEY_MISSING", "MISTRAL_API_KEY غير مهيأ لتحليل الصور.")
        prompt = question or "Analyse this trading chart screenshot using the required sections."
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "max_tokens": 1200,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": image.data_url},
                    ],
                },
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        client = self._client or httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0))
        owns = self._client is None
        try:
            last_error = "unknown error"
            for attempt in range(3):
                try:
                    response = await client.post(API_URL, json=payload, headers=headers)
                except httpx.HTTPError as exc:
                    last_error = f"network error: {type(exc).__name__}"
                    if attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    raise VisionUnavailable("NETWORK", f"تعذّر الاتصال بـ Mistral: {last_error}") from exc
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = f"HTTP {response.status_code}"
                    if attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    raise VisionUnavailable("UPSTREAM", "Mistral مشغول الآن. جرّب لاحقاً.")
                if response.status_code >= 400:
                    detail = redact(response.text[:300], self.api_key)
                    if response.status_code == 422 and "model" in detail.lower():
                        raise VisionUnavailable("MODEL", f"النموذج {self.model} لا يدعم الصور. حدّث MISTRAL_VISION_MODEL.")
                    raise VisionUnavailable("REJECTED", f"Mistral رفض الطلب (HTTP {response.status_code}): {detail}")
                try:
                    return _content(response.json())
                except ValueError as exc:
                    raise VisionUnavailable("BAD_JSON", "Mistral أعاد استجابة غير صالحة.") from exc
            raise VisionUnavailable("UPSTREAM", f"Mistral failed: {last_error}")
        finally:
            if owns:
                await client.aclose()


def redact(text: str, secret: str | None) -> str:
    if secret:
        return text.replace(secret, "***")
    return text
