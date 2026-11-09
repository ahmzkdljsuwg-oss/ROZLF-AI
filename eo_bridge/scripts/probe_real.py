"""Live ExpertOption probe used to prove real data (local or against Railway).

Usage:
    python -m eo_bridge.scripts.probe_real                 # handshake only
    EO_TOKEN=... python -m eo_bridge.scripts.probe_real    # assets + real quotes
    BRIDGE_URL=https://... EO_BRIDGE_KEY=... python -m eo_bridge.scripts.probe_real --http
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

import aiohttp

from eo_bridge.catalog import classify
from eo_bridge.settings import BridgeSettings, REGIONS


async def socket_probe(token: str | None, region: str) -> None:
    url = REGIONS.get(region.upper(), region)
    print(f"[socket] connecting {url} (token={'yes' if token else 'no'})")
    headers = {"Origin": "https://app.expertoption.com"}
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url, headers=headers, heartbeat=20) as ws:
            print("[socket] TCP/TLS handshake OK", ws.protocol if hasattr(ws, "protocol") else "")
            await ws.send_str(json.dumps({"action": "ping", "v": 23, "message": {}}))
            if token:
                await ws.send_str(
                    json.dumps(
                        {
                            "action": "multipleAction",
                            "ns": "probe-1",
                            "token": token,
                            "message": {
                                "token": token,
                                "actions": [{"action": "assets", "ns": "probe-assets"}],
                            },
                        }
                    )
                )
            deadline = time.monotonic() + 12
            seen: list[str] = []
            while time.monotonic() < deadline:
                try:
                    msg = await ws.receive(timeout=deadline - time.monotonic())
                except asyncio.TimeoutError:
                    break
                if msg.type is aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except ValueError:
                        continue
                    action = data.get("action")
                    seen.append(str(action))
                    if action == "assets":
                        assets = (data.get("message") or {}).get("assets") or []
                        by_market: dict[str, int] = {}
                        for raw in assets:
                            by_market[classify(raw)] = by_market.get(classify(raw), 0) + 1
                        print(f"[socket] REAL assets received: total={len(assets)} by_market={by_market}")
                        for raw in assets:
                            if classify(raw) in {"otc", "smarty"}:
                                print(f"  - {raw.get('id')} {raw.get('symbol')} otc={raw.get('is_otc')}")
                        return
                    if action == "error":
                        print(f"[socket] server error: {data.get('message')}")
                        return
                elif msg.type in {aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR}:
                    print("[socket] closed by server")
                    return
            print(f"[socket] actions seen without valid token: {seen or 'none'} -> data not authorised")


async def http_probe(base_url: str, api_key: str) -> None:
    base = base_url.rstrip("/")
    headers = {"X-API-Key": api_key}
    async with aiohttp.ClientSession() as session:
        for path, params in (
            ("/health", None),
            ("/assets", {"market": "otc"}),
            ("/assets", {"market": "smarty"}),
            ("/quote", {"market": "otc", "symbol": "EURUSD"}),
            ("/candles", {"market": "otc", "symbol": "EURUSD", "timeframe": "1min", "limit": 60}),
        ):
            async with session.get(f"{base}{path}", params=params, headers=headers, timeout=30) as response:
                body = await response.text()
                print(f"[http] {path} {params or ''} -> {response.status}")
                print("       " + body[:500].replace("\n", " "))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true", help="probe a deployed bridge over HTTPS instead of the socket")
    args = parser.parse_args()
    if args.http:
        base = os.getenv("BRIDGE_URL", "")
        key = os.getenv("EO_BRIDGE_KEY", "")
        if not base or not key:
            raise SystemExit("BRIDGE_URL and EO_BRIDGE_KEY are required for --http")
        asyncio.run(http_probe(base, key))
        return
    settings = BridgeSettings.from_env()
    asyncio.run(socket_probe(settings.eo_token, settings.eo_region))


if __name__ == "__main__":
    main()
