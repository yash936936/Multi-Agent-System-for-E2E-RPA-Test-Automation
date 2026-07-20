"""
tests/test_run_engine_keep_browser_open.py

Regression coverage for the "chromium closes, then clicks land on VS Code /
taskbar" bug: RunEngine.run()/.run_spec() used to unconditionally close the
Playwright browser (runtime/hooks/browser.py) at the end of every run, even
when aura/cli/execute_cmd.py still needed the same live page for the
--scroll-test/--ui-audit post-passes. Those passes would then screenshot the
whole monitor (not the browser) and OCR-click whatever was on the desktop.

The fix: RunEngine.run()/.run_spec() take a `keep_browser_open` flag that,
when True, skips the browser_hook.close() call at the end of the run --
the caller is then responsible for closing it once it's actually done.
These tests mock runtime.hooks.browser directly so they don't need a real
display/Chromium binary.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orchestrator.memory import RunMemoryStore
from orchestrator.run_engine import RunEngine
from orchestrator.skill_store import SkillStore
from target_app.demo_login_app import render_login_screen

REQUIREMENT_PATH = Path(__file__).resolve().parent.parent / "requirements_input" / "example_login_flow.md"


@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def make_provider(tmp_dir: Path):
    screens = {1: "initial", 2: "login_form", 3: "login_form", 4: "login_form"}

    def provider(run_id: str, step_id: int) -> str:
        state = screens.get(step_id, "dashboard")
        path = tmp_dir / f"{run_id}_{step_id}_{state}.png"
        if not path.exists():
            render_login_screen(state, path)
        return str(path)

    return provider


def _make_engine(tmp_dir: Path) -> RunEngine:
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")
    return RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)


def test_default_run_closes_browser_at_end(tmp_dir: Path, monkeypatch):
    """Baseline behavior: keep_browser_open defaults to False, so a plain
    `aura execute` (no --scroll-test/--ui-audit) still tears the browser
    down at the end of the run, same as before this fix."""
    mock_close = MagicMock()
    monkeypatch.setattr("runtime.hooks.browser.close", mock_close)

    engine = _make_engine(tmp_dir)
    engine.run(REQUIREMENT_PATH.read_text(), run_id="default_close_run")

    mock_close.assert_called_once()


def test_keep_browser_open_true_skips_close_at_end_of_run(tmp_dir: Path, monkeypatch):
    """The core regression case: with keep_browser_open=True, RunEngine
    must NOT close the browser itself -- the caller (execute_cmd.py) owns
    closing it once --scroll-test/--ui-audit are done."""
    mock_close = MagicMock()
    monkeypatch.setattr("runtime.hooks.browser.close", mock_close)

    engine = _make_engine(tmp_dir)
    engine.run(REQUIREMENT_PATH.read_text(), run_id="keep_open_run", keep_browser_open=True)

    mock_close.assert_not_called()


def test_keep_browser_open_propagates_through_run_spec(tmp_dir: Path, monkeypatch):
    """run() delegates to run_spec() -- confirm the flag actually reaches
    the real close-guard in run_spec() and isn't dropped along the way."""
    mock_close = MagicMock()
    monkeypatch.setattr("runtime.hooks.browser.close", mock_close)

    engine = _make_engine(tmp_dir)
    result = engine.run(REQUIREMENT_PATH.read_text(), run_id="propagation_run", keep_browser_open=True)

    assert result.report is not None
    mock_close.assert_not_called()
