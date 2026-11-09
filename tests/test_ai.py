import pytest

from ai.mistral import MistralClient, MistralUnavailable


async def test_unconfigured_client_is_honest():
    client = MistralClient(api_key=None)
    assert client.configured is False
    health = client.health()
    assert health["configured"] is False
    assert "connected" not in health or health.get("connected") is False
    with pytest.raises(MistralUnavailable):
        await client.chat("analyse EUR/USD")
    await client.close()


async def test_configured_client_reports_model():
    client = MistralClient(api_key="test-key", model="mistral-small-latest", vision_model="pixtral-12b-2409")
    assert client.configured is True
    health = client.health()
    assert health["configured"] is True
    assert health["model"] == "mistral-small-latest"
    assert health["vision_model"] == "pixtral-12b-2409"
    await client.close()


async def test_network_failure_is_wrapped(monkeypatch):
    client = MistralClient(api_key="test-key")

    async def boom(payload):
        raise MistralUnavailable("rate limited")

    monkeypatch.setattr(client, "_post", boom)
    with pytest.raises(MistralUnavailable):
        await client.chat("hello")
    await client.close()
