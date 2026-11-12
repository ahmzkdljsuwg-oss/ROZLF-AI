import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "verify_build.py"


def _run(cwd: pathlib.Path, script: pathlib.Path = SCRIPT) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("ROZLF_BUILD_SHA", None)
    env.pop("RAILWAY_GIT_COMMIT_SHA", None)
    return subprocess.run([sys.executable, str(script)], cwd=cwd, capture_output=True, text=True, env=env)


def test_build_guard_passes_on_current_tree() -> None:
    result = _run(ROOT)
    assert result.returncode == 0, result.stderr
    assert "ROZLF BUILD CHECK OK" in result.stdout
    assert "ROZLF BUILD SOURCE MATCHES FIX: True" in result.stdout


def test_build_guard_rejects_stale_entrypoint(tmp_path: pathlib.Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "verify_build.py").write_text(SCRIPT.read_text())
    (tmp_path / "main.py").write_text(
        "async def on_startup():\n    await bot.set_my_bot" + "_commands([])\n"
    )
    result = _run(tmp_path, tmp_path / "scripts" / "verify_build.py")
    assert result.returncode == 1
    assert "ROZLF BUILD CHECK FAILED" in result.stderr
