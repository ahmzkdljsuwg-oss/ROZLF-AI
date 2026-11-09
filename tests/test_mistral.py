from __future__ import annotations

import json

import httpx
import pytest

from rozlf.ai.mistral import MistralClient
from rozlf.config import Settings


def client_with(handler, **overrides) -> MistralClient:
    params = {
        "_env_file": None,
        "telegram_bot_token": "1:T",
        "mistral_api_key": "test-key",
        "ai_retries": 0,
    }
    params.update(overrides)
    settings = Settings(**params)
    transport = httpx.MockTransport(handler)
    return MistralClient(settings, httpx.AsyncClient(transport=transport))


def chat_response(text: str, status: int = 200) -> httpx.Response:
    body = {"choices": [{"message": {"content": text}}]}
    return httpx.Response(status, json=body)


async def test_missing_key_returns_no_key():
    compact = MistralClient(Settings(_env_file=None, mistral_api_key="", telegram_bot_token="1:T"))
    result = await compact.analyze_signal({"symbol": "EURUSD"})
    assert not result.ok
    assert result.code == "NO_KEY"


async def test_text_analysis_parses_json():
    text = '```json\n{"bias": "UP", "confidence": 78, "notes": "BOS صاعد"}\n```'

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert request.headers["authorization"] == "Bearer test-key"
        return chat_response(text)

    result = await client_with(handler).analyze_signal({"symbol": "EURUSD"})
    assert result.ok
    assert result.data and result.data["bias"] == "UP"


async def test_auth_error_is_reported():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthorized"})

    result = await client_with(handler).analyze_signal({"symbol": "EURUSD"})
    assert not result.ok
    assert result.code == "AUTH"


async def test_rate_limit_is_retried():
    calls = {"n": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"message": "slow down"})
        return chat_response('{"bias": "DOWN"}')

    client = client_with(handler, ai_retries=1)
    result = await client.analyze_signal({"symbol": "EURUSD"})
    assert result.ok and calls["n"] == 2


async def test_image_rejected_for_non_vision_model():
    client = client_with(lambda r: chat_response("{}"), mistral_vision_model="mistral-tiny")
    result = await client.analyze_chart(b"\x89PNG", "image/png")
    assert not result.ok
    assert result.code == "MODEL_NOT_VISION"


async def test_image_sent_to_vision_model():
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return chat_response('{"trend": "UP", "quality": "good"}')

    client = client_with(handler, mistral_vision_model="pixtral-12b-2409")
    result = await client.analyze_chart(b"binaryimage", "image/jpeg", note="EURUSD M5")
    assert result.ok
    parts = seen["body"]["messages"][1]["content"]
    assert any(p["type"] == "image_url" and p["image_url"].startswith("data:image/jpeg;base64,") for p in parts)
    assert result.data["quality"] == "good"


async def test_bad_payload_reports_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"nope": True})

    result = await client_with(handler).analyze_signal({})
    assert not result.ok
    assert result.code == "BAD_RESPONSE"
