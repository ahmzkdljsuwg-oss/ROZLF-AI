"""Read-only credential health. Never log credentials or upstream response bodies."""
import os
import re

import httpx

_ACCOUNT_ID = re.compile(r"^[0-9a-fA-F]{32}$")
_MODEL = "@cf/meta/llama-3.1-8b-instruct"


def configured_providers():
    cf = all((os.getenv(key) or "").strip() for key in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"))
    gemini = bool((os.getenv("GEMINI_API_KEY") or "").strip())
    openrouter = bool((os.getenv("OPENROUTER_API_KEY") or "").strip())
    return {
        "cloudflare": {"configured": cf, "status": "not_checked" if cf else "not_configured"},
        "gemini": {"configured": gemini, "status": "existing_adapter_not_probed" if gemini else "not_configured"},
        "openrouter": {"configured": openrouter, "status": "not_connected" if openrouter else "not_configured"},
    }


async def cloudflare_catalog_status(account_id, token, *, transport=None):
    """Validate access without model inference, billable generated tokens, or candle payloads."""
    if not account_id or not token:
        return "not_configured"
    if not _ACCOUNT_ID.fullmatch(account_id):
        return "invalid_account_id"
    if any(ch.isspace() for ch in token):
        return "invalid_token_format"
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/models/search"
    try:
        async with httpx.AsyncClient(timeout=5, follow_redirects=False, transport=transport) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {token}"},
                                        params={"search": _MODEL, "per_page": 1})
        if response.status_code in (401, 403):
            return "auth_or_permission_error"
        if response.status_code == 429:
            return "rate_limited"
        if response.status_code != 200:
            return "upstream_http_error"
        data = response.json()
        if isinstance(data, dict) and data.get("success") is True and isinstance(data.get("result"), list):
            return "catalog_verified"
        return "unexpected_response"
    except httpx.TimeoutException:
        return "timeout"
    except (httpx.HTTPError, ValueError, UnicodeError):
        return "upstream_unavailable"


async def probe_cloudflare(status):
    item = status["cloudflare"]
    if item["configured"]:
        item["status"] = await cloudflare_catalog_status(
            (os.getenv("CLOUDFLARE_ACCOUNT_ID") or "").strip(),
            (os.getenv("CLOUDFLARE_API_TOKEN") or "").strip(),
        )
    return item["status"]
