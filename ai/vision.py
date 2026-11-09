"""Local image checks before any AI call: format, size, legibility heuristics."""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageFilter, ImageStat

ALLOWED_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
MAX_BYTES = 12 * 1024 * 1024
MIN_WIDTH = 400
MIN_HEIGHT = 250


class ImageRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class PreparedImage:
    data: bytes
    mime_type: str
    width: int
    height: int
    quality_score: float


def prepare_image(raw: bytes) -> PreparedImage:
    if not raw:
        raise ImageRejected("الصورة فارغة. أرسل صورة شارت واضحة بصيغة PNG/JPG/WEBP.")
    if len(raw) > MAX_BYTES:
        raise ImageRejected("حجم الصورة كبير جداً (الحد 12MB). أرسل صورة أصغر أو أوضح.")

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = (probe.format or "").upper()
            probe.verify()
    except Exception:
        raise ImageRejected("تعذر قراءة الصورة. الصيغ المدعومة: PNG, JPG, JPEG, WEBP.") from None
    if fmt not in ALLOWED_FORMATS:
        raise ImageRejected(f"صيغة {fmt or 'غير معروفة'} غير مدعومة. استخدم PNG أو JPG أو WEBP.")

    with Image.open(io.BytesIO(raw)) as image:
        image.load()
        width, height = image.size
        if width < MIN_WIDTH or height < MIN_HEIGHT:
            raise ImageRejected(
                f"دقة الصورة منخفضة ({width}×{height}). أرسل صورة شارت لا تقل عن {MIN_WIDTH}×{MIN_HEIGHT}."
            )
        grey = image.convert("L")
        contrast = ImageStat.Stat(grey).stddev[0]
        if contrast < 4.0:
            raise ImageRejected(
                "الصورة غير واضحة (تباين منخفض). أرسل صورة شارت أوضح وبدقة أعلى."
            )
        edges = grey.filter(ImageFilter.FIND_EDGES)
        variance = ImageStat.Stat(edges).var[0]
        quality = min(100.0, variance / 12.0)

        scale = min(1.0, 1600 / max(width, height))
        if scale < 1.0:
            image = image.resize((int(width * scale), int(height * scale)), Image.LANCZOS)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        data = buffer.getvalue()
        final_size = image.size

    if quality < 3.0:
        raise ImageRejected(
            "الصورة غير واضحة (تباين منخفض). أرسل لقطة شارت كاملة وواضحة الشموع بدون ضبابية."
        )
    return PreparedImage(
        data=data,
        mime_type="image/png",
        width=final_size[0],
        height=final_size[1],
        quality_score=round(quality, 1),
    )
