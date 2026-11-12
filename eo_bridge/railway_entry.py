"""Railway/container launcher for ROZLF-EO-BRIDGE.

Some Railway services are configured with the literal command ``python main.py``.
The bridge itself is a package at /app/eo_bridge, so this launcher exists at
/app/main.py and simply runs the real package entry point. It contains no
bridge logic and no copy of the bot code.
"""
from __future__ import annotations

from eo_bridge.main import main

if __name__ == "__main__":
    main()
