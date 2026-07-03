"""
End-to-end dry run of RunEngine against requirements_input/example_login_flow.md,
using target_app/demo_login_app.py's headless-safe screen renderer instead of
a live Tkinter window (no display in CI/sandbox environments -- see that
module's docstring).

This is the test that proves Phases 2-5 actually work together as one
pipeline, not just as isolated unit-tested pieces.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from orchestrator.memory import RunMemoryStore
from orchestrator.run_engine import RunEngine
from orchestrator.schemas import RunStatus
from orchestrator.skill_store import SkillStore
from target_app.demo_login_app import render_login_screen

REQUIREMENT_PATH = Path(__file__).resolve().parent.parent / "requirements_input" / "example_login_flow.md"


@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def make_provider(tmp_dir: Path):
    """
    Maps (run_id, step_id) -> a pre-rendered screenshot matching what the
    real demo app would show at that point in the login flow:
      step 1 (click Login button)     -> initial screen
      step 2 (type username)          -> login form visible
      step 3 (type password)          -> login form visible
      step 4 (click Submit)           -> login form visible (button still there pre-click)
      final assertion (after step 4)  -> dashboard
    """
    screens = {
        1: "initial",
        2: "login_form",
        3: "login_form",
        4: "login_form",
    }

    def provider(run_id: str, step_id: int) -> str:
        state = screens.get(step_id, "dashboard")  # anything beyond the 4 known steps -> dashboard
        path = tmp_dir / f"{run_id}_{step_id}_{state}.png"
        if not path.exists():
            render_login_screen(state, path)
        return str(path)

    return provider


def test_run_engine_completes_full_login_flow(tmp_dir: Path):
    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")

    engine = RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)
    result = engine.run(requirement_text, run_id="e2e_test_run")

    assert result.spec.test_id.startswith("TC-")
    assert len(result.spec.steps) == 4

    report = result.report
    assert report.total_steps == 4
    # All 4 steps should have located their real, visible targets and the
    # final dashboard assertion should have passed -- a clean run, no healing needed.
    assert report.status == RunStatus.PASSED
    assert report.escalated_steps == 0
    assert report.self_healed_steps == 0


def test_run_engine_persists_resumable_run_state(tmp_dir: Path):
    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")

    engine = RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)
    engine.run(requirement_text, run_id="resumable_run")

    resume_point = memory.get_resume_point("resumable_run")
    assert resume_point == 4  # last step completed


def test_run_engine_escalates_when_target_never_appears(tmp_dir: Path):
    """
    If the screenshot provider never shows the expected UI (simulating a
    genuinely broken app), every step should escalate through the healing
    loop and eventually hit the guardrail hard_stop, landing in the
    escalation queue rather than looping forever.
    """
    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")

    blank_path = tmp_dir / "blank.png"
    render_login_screen("initial", blank_path)  # only ever shows the initial screen, never progresses

    def broken_provider(run_id: str, step_id: int) -> str:
        return str(blank_path)

    engine = RunEngine(screenshot_provider=broken_provider, skill_store=skill_store, memory=memory)
    result = engine.run(requirement_text, run_id="broken_run")

    assert result.report.escalated_steps > 0
    pending = memory.pending_escalations()
    assert len(pending) > 0
    assert pending[0]["run_id"] == "broken_run"


def test_run_engine_generates_and_reuses_cached_synthetic_data(tmp_dir: Path, monkeypatch):
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "project_root", tmp_dir)

    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")
    engine = RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)

    result1 = engine.run(requirement_text, run_id="data_run_1")
    from agents.data_synth.cache import load_cached

    cached = load_cached(result1.spec.test_id)
    assert cached is not None
    assert "username" in cached
