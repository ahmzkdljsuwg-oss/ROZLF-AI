from __future__ import annotations

import asyncio

from .bot.app import run_bot
from .config import get_settings


def main() -> None:
    asyncio.run(run_bot(get_settings()))


if __name__ == "__main__":
    main()
