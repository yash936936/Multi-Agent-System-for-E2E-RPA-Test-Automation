"""
Tests for the WAIT_FOR_HUMAN_ACTION step type (RunEngine.run_spec's
human-in-the-loop branch) -- the polling loop that waits for a real person
to perform an action instead of AURA acting autonomously.

Uses RunEngine.run_spec() directly (bypassing Planner) since these tests
are about the polling/verification logic, not spec generation.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from orchestrator.memory import RunMemoryStore
from orchestrator.run_engine import RunEngine
from orchestrator.schemas import ActionType, RunStatus, TestSpec, TestStep
from orchestrator.skill_store import SkillStore
from target_app.demo_login_app import render_login_screen


@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def _engine(tmp_dir: Path, screenshots: list[Path], sleep_fn=lambda s: None, **kwargs) -> RunEngine:
    """screenshot_provider returns screenshots[call_index], clamped to the last one."""
    calls = {"n": 0}

    def provider(run_id: str, step_id: int) -> str:
        idx = min(calls["n"], len(screenshots) - 1)
        calls["n"] += 1
        return str(screenshots[idx])

    return RunEngine(
        screenshot_provider=provider,
        skill_store=SkillStore(db_path=tmp_dir / "skills.db"),
        memory=RunMemoryStore(db_path=tmp_dir / "memory.db"),
        sleep_fn=sleep_fn,
        **kwargs,
    )


def test_wait_for_human_action_passes_once_screen_changes(tmp_dir: Path):
    before = render_login_screen("initial", tmp_dir / "before.png")
    after = render_login_screen("dashboard", tmp_dir / "after.png")

    # First provider call is the baseline; second call (after one poll
    # tick) already shows the changed screen -- simulates the human
    # having clicked in between.
    engine = _engine(tmp_dir, [before, after])
    spec = TestSpec(
        test_id="TC-INTERACTIVE-001", requirement_ref="REQ-INTERACTIVE",
        steps=[
            TestStep(
                step_id=1,
                action=ActionType.WAIT_FOR_HUMAN_ACTION,
                target_description="click the submit button",
                expected_state="dashboard_visible",
            )
        ],
    )

    result = engine.run_spec(spec, run_id="human_test_1")

    assert result.report.status == RunStatus.PASSED
    assert result.report.escalated_steps == 0


def test_wait_for_human_action_escalates_on_timeout_if_nothing_changes(tmp_dir: Path):
    same = render_login_screen("initial", tmp_dir / "same.png")

    engine = _engine(tmp_dir, [same])  # every call returns the identical screenshot
    spec = TestSpec(
        test_id="TC-INTERACTIVE-002", requirement_ref="REQ-INTERACTIVE",
        steps=[
            TestStep(
                step_id=1,
                action=ActionType.WAIT_FOR_HUMAN_ACTION,
                target_description="click the submit button",
                human_action_timeout_seconds=3,  # short, deterministic timeout for the test
            )
        ],
    )

    result = engine.run_spec(spec, run_id="human_test_2")

    assert result.report.status == RunStatus.ESCALATED
    assert result.report.escalated_steps == 1


def test_wait_for_human_action_calls_on_waiting_callback_each_poll_tick(tmp_dir: Path):
    same = render_login_screen("initial", tmp_dir / "same.png")
    ticks: list[float] = []

    engine = _engine(
        tmp_dir,
        [same],
        on_waiting_for_human=lambda step_id, step, elapsed: ticks.append(elapsed),
    )
    spec = TestSpec(
        test_id="TC-INTERACTIVE-003", requirement_ref="REQ-INTERACTIVE",
        steps=[
            TestStep(
                step_id=1,
                action=ActionType.WAIT_FOR_HUMAN_ACTION,
                target_description="click anything",
                human_action_timeout_seconds=4,
            )
        ],
    )

    engine.run_spec(spec, run_id="human_test_3")

    # Poll interval defaults to 2s -- with a 4s timeout we expect at least
    # two ticks (elapsed=0, elapsed=2) before giving up.
    assert len(ticks) >= 2
    assert ticks[0] == 0.0


def test_wait_for_human_action_uses_mutation_observer_when_live_page_available(tmp_dir: Path, monkeypatch):
    """
    Phase 4 (docs/decisions.md D-077): when a live DOM page exists, a
    real DOM mutation drives `changed`, proven the same way as
    tests/test_ui_audit_runner.py's proof -- every screenshot returned is
    byte-identical (would never pass under hash-diff-only polling) while
    the mutation observer reports a real mutation on the first poll.
    """
    same = render_login_screen("initial", tmp_dir / "same.png")

    class FakePage:
        def __init__(self):
            self.read_calls = 0

        def evaluate(self, js, arg=None):
            if "__aura_mutations = []" in js:
                return True
            self.read_calls += 1
            # First read: a real mutation. This simulates the human's
            # click landing between the arm() call and this first poll.
            return {"count": 2, "urlBefore": "http://x", "urlAfter": "http://x", "sample": [{"type": "childList", "tag": "DIV"}]}

    fake_page = FakePage()
    monkeypatch.setattr("runtime.hooks.browser.has_active_page", lambda: True)
    monkeypatch.setattr("runtime.hooks.browser.get_page", lambda: fake_page)

    engine = _engine(tmp_dir, [same])  # identical screenshot every call -- hash-diff alone would never detect a change
    spec = TestSpec(
        test_id="TC-INTERACTIVE-004", requirement_ref="REQ-INTERACTIVE",
        steps=[
            TestStep(
                step_id=1,
                action=ActionType.WAIT_FOR_HUMAN_ACTION,
                target_description="click the submit button",
            )
        ],
    )

    result = engine.run_spec(spec, run_id="human_test_4")

    assert fake_page.read_calls >= 1
    assert result.report.status == RunStatus.PASSED
    assert result.report.escalated_steps == 0


def test_wait_for_human_action_with_no_expected_state_does_not_crash_on_verification_source(tmp_dir: Path):
    """
    Regression test for a real, previously-latent bug found while
    writing the Phase 4 test above: orchestrator/run_engine.py's
    WAIT_FOR_HUMAN_ACTION branch sets
    verification_source="keyword_heuristic" when a screen change is
    detected with no expected_state given (D-067.7's keyword-heuristic
    fix), but orchestrator/schemas.py's VisionActionResult.verification_source
    Literal never included that value -- every such run crashed with a
    pydantic ValidationError instead of completing. No prior test
    exercised "a real screen change with no expected_state" via the
    plain hash-diff path (only via mutation-observer, in the test
    above, or via expected_state-driven passes/timeouts elsewhere in
    this file) -- this is that missing case, on its own, independent of
    Phase 4's mutation-observer wiring.
    """
    before = render_login_screen("initial", tmp_dir / "before2.png")
    after = render_login_screen("dashboard", tmp_dir / "after2.png")

    engine = _engine(tmp_dir, [before, after])
    spec = TestSpec(
        test_id="TC-INTERACTIVE-005", requirement_ref="REQ-INTERACTIVE",
        steps=[
            TestStep(
                step_id=1,
                action=ActionType.WAIT_FOR_HUMAN_ACTION,
                target_description="click the submit button",
                # deliberately no expected_state -- this is the exact
                # branch that crashed
            )
        ],
    )

    result = engine.run_spec(spec, run_id="human_test_5")  # must not raise

    assert result.report.status in (RunStatus.PASSED, RunStatus.ESCALATED)
