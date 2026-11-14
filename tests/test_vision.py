from __future__ import annotations

import io

import httpx
import pytest
import random

from PIL import Image, ImageDraw

from ai.vision import (
    API_URL,
    ImageRejected,
    MistralVision,
    VisionUnavailable,
    prepare_image,
    redact,
)


def _png(width: int = 640, height: int = 360) -> bytes:
    image = Image.new("RGB", (width, height), (12, 20, 30))
    draw = ImageDraw.Draw(image)
    rng = random.Random(7)
    price = height // 2
    step = max(2, width // 80)
    for x in range(0, width, step):
        price = max(10, min(height - 10, price + rng.randint(-12, 12)))
        draw.line((x, price, x, price + rng.randint(8, 40)), fill=(0, 220, 150), width=2)
    for y in range(0, height, 40):
        draw.line((0, y, width, y), fill=(40, 60, 80))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_prepare_image_accepts_real_png():
    prepared = prepare_image(_png())
    assert prepared.data_url.startswith("data:image/jpeg;base64,")
    assert prepared.width == 640 and prepared.height == 360


def test_prepare_image_rejects_non_image_and_tiny_images():
    with pytest.raises(ImageRejected):
        prepare_image(b"not an image at all")
    with pytest.raises(ImageRejected):
        prepare_image(_png(120, 120))


def test_prepare_image_downscales_huge_charts():
    prepared = prepare_image(_png(2600, 1400))
    assert prepared.width <= 1800 and prepared.height <= 1800


def test_health_reports_missing_key_honestly():
    vision = MistralVision(None)
    assert vision.configured is False
    assert vision.health() == {"configured": False, "model": None}


async def test_analyse_without_key_raises_unavailable():
    vision = MistralVision("")
    with pytest.raises(VisionUnavailable) as info:
        await vision.analyse(prepare_image(_png()))
    assert info.value.code == "KEY_MISSING"


async def test_analyse_returns_model_text_and_sends_image():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ASSET: EUR/USD\nTREND: UP"}}]},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    vision = MistralVision("test-key", client=client)
    text = await vision.analyse(prepare_image(_png()))
    await client.aclose()
    assert text.startswith("ASSET: EUR/USD")
    assert seen["model"] == "pixtral-12b-2409"
    image_part = seen["messages"][1]["content"][1]
    assert image_part["type"] == "image_url"
    assert image_part["image_url"].startswith("data:image/jpeg;base64,")


async def test_analyse_redacts_key_from_upstream_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad key test-key rejected")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    vision = MistralVision("test-key", client=client)
    with pytest.raises(VisionUnavailable) as info:
        await vision.analyse(prepare_image(_png()))
    await client.aclose()
    assert "test-key" not in str(info.value)
    assert "***" in str(info.value)


async def test_analyse_does_not_retry_client_errors_forever():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text="unauthorized")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    vision = MistralVision("test-key", client=client)
    with pytest.raises(VisionUnavailable):
        await vision.analyse(prepare_image(_png()))
    await client.aclose()
    assert calls["n"] == 1


def test_redact_removes_secret():
    assert redact(f"request to {API_URL}?apikey=abc", "abc").endswith("apikey=***")
