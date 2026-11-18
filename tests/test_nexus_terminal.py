from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from ai.provider_status import cloudflare_catalog_status, configured_providers
from bot.formatting import NEXUS_ANALYSIS_BANNER, nexus_data_unavailable_text, nexus_signal_text
from engines.technical.readings import READING_KEYS, read_indicators
from tests.conftest import make_candles


def test_terminal_eight_readings_and_gap_guard():
    now = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
    bars = make_candles(n=220, tf_seconds=60, end=now)
    result = read_indicators(bars, 60)
    assert tuple(r["key"] for r in result) == READING_KEYS
    readings = {r["key"]: r for r in result}
    assert readings["ema"]["value"] == "UP"
    assert 0 <= readings["rsi"]["value"] <= 100
    assert readings["candle"]["movement"] == "UP"
    assert readings["resistance"]["value"] is None or readings["resistance"]["value"] > bars[-1].close
    bars[-1] = replace(bars[-1], time=now + timedelta(minutes=2))
    gapped = {r["key"]: r for r in read_indicators(bars, 60)}
    assert all(gapped[key]["value"] is None for key in READING_KEYS if key != "candle")
    assert gapped["candle"]["movement"] == "UP"


@pytest.mark.parametrize("status,payload,expected", [
    (200, {"success": True, "result": [{"name": "Llama"}]}, "catalog_verified"),
    (200, {"success": False, "errors": [{"message": "secret"}]}, "unexpected_response"),
    (403, {"success": False}, "auth_or_permission_error"),
    (429, {}, "rate_limited"),
])
async def test_cloudflare_probe_only_sends_read_only_authenticated_request(status,payload,expected):
    account = "a" * 32
    token = "sample-test-token-not-credentials"
    def mock(request):
        assert request.method == "GET" and request.url.host == "api.cloudflare.com"
        assert request.url.path.endswith(f"/{account}/ai/models/search")
        assert request.headers["Authorization"] == f"Bearer {token}"
        assert request.content == b""
        return httpx.Response(status, json=payload)

    result = await cloudflare_catalog_status(account, token, transport=httpx.MockTransport(mock))
    assert result == expected


async def test_invalid_account_never_sends_http():
    def never(_request):
        pytest.fail("invalid account must not trigger an outbound request")
    assert await cloudflare_catalog_status("bad", "t", transport=httpx.MockTransport(never)) == "invalid_account_id"


def test_provider_configuration_reports_no_secrets(monkeypatch):
    for key in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"):
        monkeypatch.setenv(key, "test-sensitive-value")
    state = configured_providers()
    assert all(d["configured"] for d in state.values())
    assert state["cloudflare"]["status"] == "not_checked"
    assert state["openrouter"]["status"] == "not_connected"
    assert "test-sensitive-value" not in str(state)


def test_telegram_analysis_caption_and_observed_trend():
    text = nexus_signal_text("smarty", "NO TRADE", 30, None, mode="pro", trend="RANGE", volatility="HIGH")
    assert text.startswith(f"<b>{NEXUS_ANALYSIS_BANNER}</b>")
    assert "عرضي" in text and "NO TRADE" in text
    assert nexus_data_unavailable_text("smarty").startswith(f"<b>{NEXUS_ANALYSIS_BANNER}</b>")
