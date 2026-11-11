"""Fail the build/start if the deployed tree is not the fixed ROZLF AI bot."""
from __future__ import annotations

import os
import pathlib
import subprocess
import sys

FORBIDDEN = "set_my_bot" + "_commands"
ROOT = pathlib.Path(__file__).resolve().parent.parent
ENTRYPOINT = ROOT / "main.py"


def _git_sha() -> str:
    sha = os.getenv("ROZLF_BUILD_SHA") or os.getenv("RAILWAY_GIT_COMMIT_SHA") or ""
    if sha:
        return sha
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown-no-git-metadata"


def main() -> int:
    problems: list[str] = []
    print(f"ROZLF BUILD SHA: {_git_sha()}")
    print(f"ROZLF BUILD ENTRYPOINT: {ENTRYPOINT}")
    print(f"ROZLF BUILD PYTHON: {sys.version.split()[0]}")

    if not ENTRYPOINT.is_file():
        problems.append(f"entrypoint missing: {ENTRYPOINT}")

    duplicates = sorted(str(path.relative_to(ROOT)) for path in ROOT.rglob("main.py") if ".venv" not in path.parts)
    print(f"ROZLF BUILD MAIN.PY FILES: {duplicates}")
    if len(duplicates) > 1:
        print("  note: only the root main.py is executed; the others belong to other services")

    if ENTRYPOINT.is_file():
        source = ENTRYPOINT.read_text(encoding="utf-8")
        if FORBIDDEN in source:
            problems.append(f"entrypoint still calls {FORBIDDEN}; rebuild from the latest main branch")
        if "set_my_commands(" not in source:
            problems.append("entrypoint never calls bot.set_my_commands")
        print(f"ROZLF BUILD SOURCE MATCHES FIX: {FORBIDDEN not in source}")

    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if ".venv" in rel.parts or path == ENTRYPOINT:
            continue
        if rel.name.startswith("verify_build") or rel.parts[0] in {"tests", "eo_bridge"}:
            continue
        if FORBIDDEN in path.read_text(encoding="utf-8", errors="ignore"):
            problems.append(f"{rel} still calls {FORBIDDEN}")

    if problems:
        for problem in problems:
            print(f"ROZLF BUILD CHECK FAILED: {problem}", file=sys.stderr)
        return 1
    print("ROZLF BUILD CHECK OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
