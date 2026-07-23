"""
End-to-end dry run of RunEngine against requirements_input/example_login_flow.md,
using target_app/demo_login_app.py's headless-safe screen renderer instead of
a live Tkinter window (no display in CI/sandbox environments -- see that
module's docstring).

This is the test that proves Phases 2-5 actually work together as one
pipeline, not just as isolated unit-tested pieces.
"""
from __future__ import annotations

import json
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


def test_run_engine_final_assertion_records_audit_evidence(tmp_dir: Path):
    """
    AA1 (docs/decisions.md D-057) regression test: the final spec-level
    assertion result must carry verification_source + raw_evidence (which
    method decided the verdict, and the per-assertion detail behind it) --
    not just the collapsed assertion_passed bool. This is exactly the
    audit-trail gap that let D-056's bug go undetected: a step could say
    "fulfilled" while its real check had failed, with nothing in the trace
    itself to show what was actually checked.
    """
    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")

    engine = RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)
    result = engine.run(requirement_text, run_id="aa1_audit_test_run")

    raw = json.loads(Path(result.report.report_paths["raw_json"]).read_text())
    step_results = raw["step_results"]

    final_step = step_results[-1]  # the spec-level assertion step, appended after all spec.steps
    assert final_step["verification_source"] == "ocr"
    assert final_step["raw_evidence"] is not None
    assert "assertions" in final_step["raw_evidence"]
    assert len(final_step["raw_evidence"]["assertions"]) >= 1
    for detail in final_step["raw_evidence"]["assertions"]:
        assert "expected" in detail
        assert "passed" in detail
        assert "method" in detail  # e.g. "literal_ocr" / "structural_fallback" / "structural_sentinel"


def test_run_engine_persists_resumable_run_state(tmp_dir: Path):
    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")

    engine = RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)
    engine.run(requirement_text, run_id="resumable_run")

    resume_point = memory.get_resume_point("resumable_run")
    assert resume_point == 4  # last step completed


def test_run_engine_visual_regression_first_run_creates_baseline(tmp_dir: Path, monkeypatch):
    # Phase G3 (decisions.md D-027): end-to-end proof that
    # TestStep.visual_baseline_key actually reaches
    # agents/vision/visual_regression.compare_to_baseline via RunEngine,
    # not just a unit test of the module in isolation.
    from config.settings import settings
    from orchestrator.schemas import ActionType, TestSpec, TestStep

    monkeypatch.setattr(settings, "project_root", tmp_dir)

    spec = TestSpec(
        test_id="TC-VISUAL-001",
        requirement_ref="visual regression smoke test",
        steps=[
            TestStep(
                step_id=1, action=ActionType.VISUAL_CLICK,
                target_description="Login button",
                visual_baseline_key="login_screen_g3_test",
            ),
        ],
    )
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")
    engine = RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)

    result = engine.run_spec(spec, run_id="visual_regression_run")

    raw_results = json.loads(Path(result.report.report_paths["raw_json"]).read_text())
    step_1 = raw_results["step_results"][0]
    assert step_1["visual_baseline_created"] is True
    assert step_1["visual_diff_ratio"] == 0.0
    assert (settings.baselines_dir / "login_screen_g3_test.png").exists()


def test_run_engine_visual_regression_second_run_compares_against_baseline(tmp_dir: Path, monkeypatch):
    from config.settings import settings
    from orchestrator.schemas import ActionType, TestSpec, TestStep

    monkeypatch.setattr(settings, "project_root", tmp_dir)

    spec = TestSpec(
        test_id="TC-VISUAL-002",
        requirement_ref="visual regression smoke test",
        steps=[
            TestStep(
                step_id=1, action=ActionType.VISUAL_CLICK,
                target_description="Login button",
                visual_baseline_key="login_screen_g3_test_2",
            ),
        ],
    )
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")
    provider = make_provider(tmp_dir)
    engine = RunEngine(screenshot_provider=provider, skill_store=skill_store, memory=memory)

    # First run creates the baseline from whatever screen the provider shows at step 1 ("initial").
    engine.run_spec(spec, run_id="visual_run_a")

    # Second run against the exact same screenshot -- should compare clean, zero diff.
    result_b = engine.run_spec(spec, run_id="visual_run_b")
    raw_results_b = json.loads(Path(result_b.report.report_paths["raw_json"]).read_text())
    step_1_b = raw_results_b["step_results"][0]
    assert step_1_b["visual_baseline_created"] is False
    assert step_1_b["visual_diff_ratio"] == 0.0
    assert step_1_b["assertion_passed"] is not False  # a clean visual match shouldn't fail the step



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


def test_run_engine_escalates_cleanly_on_no_display(tmp_dir: Path):
    """
    Regression test: previously, `self.screenshot_provider(...)` in the main
    vision branch was called with no try/except, so a NoDisplayError (raised
    by runtime/hooks/capture.py whenever no display/mss is available -- the
    normal case in headless CI/sandbox environments) propagated all the way
    up and crashed `aura execute`/`aura explore` with a raw traceback instead
    of escalating like every other action path already does. This test
    simulates that exact condition via a provider that raises NoDisplayError,
    and asserts the run completes with steps escalated instead of raising.
    """
    from runtime.hooks.capture import NoDisplayError

    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")

    def no_display_provider(run_id: str, step_id: int) -> str:
        raise NoDisplayError("no display available (simulated)")

    engine = RunEngine(screenshot_provider=no_display_provider, skill_store=skill_store, memory=memory)

    # This must NOT raise -- that's the whole point of the fix.
    result = engine.run(requirement_text, run_id="no_display_run")

    assert result.report.escalated_steps > 0
    assert result.report.status.value in ("escalated", "failed")
