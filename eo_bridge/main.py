"""Process entry point for ROZLF-EO-BRIDGE (Railway / Docker / local)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from aiohttp import web

from .app import create_app
from .settings import BridgeSettings


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def _run() -> None:
    settings = BridgeSettings.from_env()
    setup_logging(settings.log_level)
    logger = logging.getLogger("eo_bridge")
    if not settings.api_key:
        logger.warning("EO_BRIDGE_KEY is missing: every data endpoint will answer 401")
    if not settings.eo_token:
        logger.warning("EO_TOKEN is missing: the bridge can start but returns DATA_UNAVAILABLE")
    logger.info("Starting ROZLF-EO-BRIDGE on %s:%s (region=%s)", settings.host, settings.port, settings.eo_region)

    app = create_app(settings)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, settings.host, settings.port)
    await site.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    logger.info("Shutting down")
    await runner.cleanup()


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
