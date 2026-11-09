import io
import random

import pytest
from PIL import Image, ImageDraw

from ai.vision import ImageRejected, prepare_image


def _chart_png(width=900, height=600) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    random.seed(5)
    price = height // 2
    points = []
    for x in range(0, width, 6):
        price += random.randint(-12, 12)
        points.append((x, max(10, min(height - 10, price))))
    draw.line(points, fill="black", width=2)
    for x in range(0, width, 40):
        draw.line([(x, 0), (x, height)], fill="lightgrey", width=1)
    for y in range(0, height, 40):
        draw.line([(0, y), (width, y)], fill="lightgrey", width=1)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_valid_chart_is_prepared():
    prepared = prepare_image(_chart_png())
    assert prepared.mime_type == "image/png"
    assert prepared.data
    assert prepared.quality_score > 0
    reopened = Image.open(io.BytesIO(prepared.data))
    assert reopened.format == "PNG"


def test_small_image_rejected():
    buffer = io.BytesIO()
    Image.new("RGB", (120, 80), "white").save(buffer, format="PNG")
    with pytest.raises(ImageRejected) as excinfo:
        prepare_image(buffer.getvalue())
    assert "دقة" in str(excinfo.value)


def test_unsupported_format_rejected():
    buffer = io.BytesIO()
    Image.new("RGB", (900, 600), "white").save(buffer, format="BMP")
    with pytest.raises(ImageRejected) as excinfo:
        prepare_image(buffer.getvalue())
    assert "غير مدعومة" in str(excinfo.value)


def test_blank_image_flagged_as_low_quality():
    buffer = io.BytesIO()
    Image.new("RGB", (900, 600), "white").save(buffer, format="PNG")
    with pytest.raises(ImageRejected) as excinfo:
        prepare_image(buffer.getvalue())
    assert "واضحة" in str(excinfo.value) or "جودة" in str(excinfo.value)


def test_empty_and_oversized_payloads_rejected():
    with pytest.raises(ImageRejected):
        prepare_image(b"")
    with pytest.raises(ImageRejected):
        prepare_image(b"0" * (12 * 1024 * 1024 + 1))
