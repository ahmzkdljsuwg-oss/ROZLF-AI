"""Build-time check for the NEXUS-ADMIN service image."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED = [
    "start_admin.py",
    "admin_bot/__init__.py",
    "admin_bot/main.py",
    "admin_bot/handlers.py",
    "admin_bot/keyboards.py",
    "admin_bot/middleware.py",
]


def main() -> int:
    missing = [name for name in REQUIRED if not (ROOT / name).is_file()]
    if missing:
        print(f"ADMIN BUILD CHECK FAILED: missing {', '.join(missing)}", file=sys.stderr)
        return 1

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [sys.executable, "-c", "import admin_bot.main; print('ADMIN IMPORTS OK')"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ADMIN BUILD CHECK FAILED: import error\n{result.stderr}", file=sys.stderr)
        return 1

    print("ADMIN IMPORTS OK")
    print(f"ROZLF BUILD SHA: {os.environ.get('ROZLF_BUILD_SHA', 'unknown')}")
    print("ROZLF ADMIN BUILD CHECK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
