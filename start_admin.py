"""Railway start command for the second (owner-only admin) service.

Running this file adds the repository root to ``sys.path`` so the
``admin_bot`` package resolves no matter which directory Railway starts in.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from admin_bot.main import main

if __name__ == "__main__":
    main()
