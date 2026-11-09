"""Guards the Railway layout: the bridge must start from a folder that has no
/app/main.py in the repo (the image supplies one), and both supported start
commands must point at the real package entry point.
"""
from __future__ import annotations

from pathlib import Path

BRIDGE = Path(__file__).resolve().parents[1]


def test_dockerfile_installs_real_launcher_and_checks_imports():
    text = (BRIDGE / "Dockerfile").read_text()
    assert "COPY . /app/eo_bridge" in text
    assert "COPY railway_entry.py /app/main.py" in text
    assert "import eo_bridge.app, eo_bridge.main" in text


def test_launcher_runs_the_package_entrypoint():
    text = (BRIDGE / "railway_entry.py").read_text()
    assert "from eo_bridge.main import main" in text
    assert "main()" in text


def test_procfile_and_railway_use_module_entrypoint():
    assert "python -m eo_bridge.main" in (BRIDGE / "Procfile").read_text()
    config = (BRIDGE / "railway.json").read_text()
    assert "python -m eo_bridge.main" in config
    assert "/health" in config


def test_bridge_has_no_main_py_at_repo_level_dependency():
    # The launcher must not depend on the bot's root main.py.
    assert (BRIDGE / "main.py").exists()
    launcher = (BRIDGE / "railway_entry.py").read_text()
    assert "set_my_commands" not in launcher
