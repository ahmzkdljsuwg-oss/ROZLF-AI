"""Production integration check: Mini App web proxy -> ROZLF AI bot engine.

Usage (no secret is stored in this file):

    WEB_BASE_URL=https://web-production-b044b.up.railway.app \
    BOT_BASE_URL=https://rozlf-ai-production.up.railway.app \
    INIT_DATA='query_id=...' python3 scripts/verify_engine_link.py

Without INIT_DATA the authenticated routes are expected to answer 401; they
still prove that the request reached the bot service because the bot's own
error payload comes back through the proxy.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

WEB = os.getenv("WEB_BASE_URL", "https://web-production-b044b.up.railway.app").rstrip("/")
BOT = os.getenv("BOT_BASE_URL", "https://rozlf-ai-production.up.railway.app").rstrip("/")
INIT_DATA = os.getenv("INIT_DATA", "").strip()

ROUTES = ("bootstrap", "markets", "history", "recommendations")


def call(url: str, init_data: str = "") -> tuple[int, dict | str, int]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    if init_data:
        request.add_header("X-Telegram-Init-Data", init_data)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        status = exc.code
    except Exception as exc:  # network failure
        return 0, {"error": f"{type(exc).__name__}: {exc}"}, int((time.monotonic() - started) * 1000)
    elapsed = int((time.monotonic() - started) * 1000)
    try:
        return status, json.loads(body), elapsed
    except Exception:
        return status, body[:300], elapsed


def main() -> int:
    failures = 0
    print(f"web: {WEB}\nbot: {BOT}\ninitData: {'present' if INIT_DATA else 'absent'}\n")

    probes = (
        ("bot /health", f"{BOT}/health", ""),
        ("bot /api/mini/health", f"{BOT}/api/mini/health", ""),
        ("web /api/mini/health?probe=1", f"{WEB}/api/mini/health?probe=1", ""),
    )
    for label, url, data in probes:
        status, body, elapsed = call(url, data)
        ready = isinstance(body, dict) and body.get("engine_ready")
        print(f"[{status}] {label} {elapsed}ms engine_ready={bool(ready)}")
        print(json.dumps(body, ensure_ascii=False)[:800])
        if status != 200 or (label != "bot /health" and not ready):
            failures += 1

    for route in ROUTES:
        status, body, elapsed = call(f"{WEB}/api/mini/{route}", INIT_DATA)
        ok = status == 200 if INIT_DATA else status == 401
        print(f"[{status}] web /api/mini/{route} {elapsed}ms expected={200 if INIT_DATA else 401} ok={ok}")
        print(json.dumps(body, ensure_ascii=False)[:600])
        if not ok:
            failures += 1

    print(f"\nresult: {'PASS' if failures == 0 else f'FAIL ({failures})'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
