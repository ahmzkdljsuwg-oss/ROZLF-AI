"""One-shot live market scan using the configured data sources (no Telegram)."""

import asyncio
import json

from rozlf.config import get_settings
from rozlf.services.container import AppContainer


async def main() -> None:
    container = AppContainer(get_settings())
    await container.startup(None)
    try:
        readiness = await container.readiness()
        results = await container.scanner.scan_all()
        print(json.dumps({"readiness": readiness, "scans": [r.as_dict() for r in results]}, ensure_ascii=False, indent=2))
    finally:
        await container.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
