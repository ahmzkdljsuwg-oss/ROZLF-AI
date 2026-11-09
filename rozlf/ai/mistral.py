"""Mistral AI client: separate text analysis and vision analysis."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass

import httpx

from ..config import Settings

log = logging.getLogger(__name__)

VISION_MODEL_ALLOWLIST = {
    "pixtral-12b-2409",
    "pixtral-large-latest",
    "pixtral-large-2411",
    "mistral-small-latest",
    "mistral-small-2503",
    "mistral-small-2506",
    "mistral-medium-latest",
    "mistral-medium-2508",
}

SYSTEM_TEXT = (
    "أنت محلل أسواق مالي مختص في الخيارات الثنائية. تُعطى بيانات مؤشرات محسوبة مسبقاً من شموع حقيقية. "
    "لا تختلق أسعاراً ولا نتائج، ولا تعد بأرباح. أعد JSON فقط بالمفاتيح: "
    '{"bias":"UP|DOWN|NO_TRADE","confidence":0-100,"summary":"جملتان","risks":["..."]}.'
)

SYSTEM_VISION = (
    "أنت محلل شارتات. حلّل الصورة المرسلة فقط، ولا تخمّن أسعاراً غير ظاهرة. "
    "أعد JSON فقط بالمفاتيح: "
    '{"trend":"UP|DOWN|SIDEWAYS|UNCLEAR","support":[...],"resistance":[...],"patterns":[...],'
    '"liquidity_zones":[...],"reversal_zones":[...],"quality":"good|fair|poor","summary":"...","request_new_image":true|false}.'
)


@dataclass
class AIResult:
    ok: bool
    text: str = ""
    data: dict | None = None
    model: str = ""
    error: str = ""
    code: str = "OK"


class MistralClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client or httpx.AsyncClient(timeout=settings.ai_timeout_seconds)
        self._owns_client = client is None

    @property
    def configured(self) -> bool:
        return bool(self.settings.mistral_api_key)

    def supports_vision(self, model: str | None = None) -> bool:
        return (model or self.settings.mistral_vision_model) in VISION_MODEL_ALLOWLIST

    async def analyze_signal(self, context: dict) -> AIResult:
        if not self.configured:
            return AIResult(False, error="MISTRAL_API_KEY غير مضبوط", code="NO_KEY")
        prompt = _signal_prompt(context)
        return await self._chat(self.settings.mistral_model, SYSTEM_TEXT, [{"type": "text", "text": prompt}])

    async def analyze_chart(self, image_bytes: bytes, mime: str = "image/png", note: str = "") -> AIResult:
        if not self.configured:
            return AIResult(False, error="MISTRAL_API_KEY غير مضبوط", code="NO_KEY")
        model = self.settings.mistral_vision_model
        if not self.supports_vision(model):
            return AIResult(
                False,
                error=f"الموديل {model} غير معروف بدعم الصور؛ لن تُرسل الصورة.",
                code="MODEL_NOT_VISION",
                model=model,
            )
        encoded = base64.b64encode(image_bytes).decode("ascii")
        content = [
            {"type": "text", "text": "حلّل هذا الشارت وأعد JSON كما هو مطلوب." + (f"\nملاحظة المستخدم: {note}" if note else "")},
            {"type": "image_url", "image_url": f"data:{mime};base64,{encoded}"},
        ]
        return await self._chat(model, SYSTEM_VISION, content)

    async def _chat(self, model: str, system: str, content: list[dict]) -> AIResult:
        body = {
            "model": model,
            "temperature": 0.1,
            "max_tokens": 700,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        }
        headers = {"Authorization": f"Bearer {self.settings.mistral_api_key}"}
        url = f"{self.settings.mistral_api_base.rstrip('/')}/chat/completions"
        attempts = max(1, self.settings.ai_retries + 1)
        last_error = ""
        for attempt in range(attempts):
            try:
                resp = await self._client.post(url, json=body, headers=headers)
            except httpx.TimeoutException:
                last_error, code = "انتهت مهلة Mistral.", "TIMEOUT"
            except httpx.HTTPError as exc:
                last_error, code = f"تعذر الوصول إلى Mistral: {exc.__class__.__name__}", "NETWORK"
            else:
                if resp.status_code == 200:
                    return self._parse(resp.json(), model)
                if resp.status_code in (401, 403):
                    return AIResult(False, error="مفتاح Mistral غير صالح.", code="AUTH", model=model)
                if resp.status_code == 429:
                    last_error, code = "Mistral: تجاوز حد الطلبات.", "RATE_LIMIT"
                elif resp.status_code >= 500:
                    last_error, code = "Mistral: خطأ خادم مؤقت.", "UPSTREAM"
                else:
                    detail = _safe_detail(resp)
                    return AIResult(False, error=f"Mistral HTTP {resp.status_code}: {detail}", code="BAD_REQUEST", model=model)
            if attempt + 1 < attempts:
                await asyncio.sleep(2.0 * (attempt + 1))
        return AIResult(False, error=last_error, code=code, model=model)

    def _parse(self, payload: dict, model: str) -> AIResult:
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return AIResult(False, error="استجابة Mistral بصيغة غير متوقعة.", code="BAD_RESPONSE", model=model)
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        text = str(text).strip()
        if not text:
            return AIResult(False, error="استجابة Mistral فارغة.", code="EMPTY", model=model)
        return AIResult(True, text=_strip_code_fence(text), data=_extract_json(text), model=model)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()


def _signal_prompt(context: dict) -> str:
    return (
        "بيانات الإشارة المحسوبة محلياً:\n"
        f"الأصل: {context.get('symbol')} ({context.get('market')})\n"
        f"الفريم: {context.get('timeframe')}  |  الاتجاه المحلي: {context.get('direction')}  |  الدرجة: {context.get('score')}\n"
        f"السعر: {context.get('price')}  |  ATR: {context.get('atr')}  |  RSI: {context.get('rsi')}  |  MACD hist: {context.get('macd_hist')}\n"
        f"هيكل السوق: {context.get('trend')}  |  BOS: {context.get('bos')}  |  CHoCH: {context.get('choch')}  |  المنطقة: {context.get('zone')}\n"
        f"أسباب محلية: {'; '.join(context.get('reasons') or [])}\n"
        f"تحذيرات: {'; '.join(context.get('warnings') or [])}\n"
        "قيّم فقط انسجام هذه المعطيات. لا تضف أسعاراً جديدة."
    )


def _strip_code_fence(text: str) -> str:
    if text.startswith("```"):
        parts = text.split("\n")
        if len(parts) >= 3:
            return "\n".join(parts[1:-1]).strip()
    return text


def _extract_json(text: str) -> dict | None:
    stripped = _strip_code_fence(text)
    try:
        value = json.loads(stripped)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if 0 <= start < end:
            try:
                value = json.loads(stripped[start : end + 1])
                return value if isinstance(value, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def _safe_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        message = data.get("message") if isinstance(data, dict) else None
        return str(message)[:160] if message else "طلب مرفوض"
    except ValueError:
        return "طلب مرفوض"
