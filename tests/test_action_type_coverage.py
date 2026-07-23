"""
tests/test_action_type_coverage.py

AA2 (docs/decisions.md D-057) -- exhaustiveness coverage over
ActionType. The real bug this guards against: `ActionType.ASSERT` had
NO branch at all in `agents/vision/executor.py::execute_step` for an
unknown amount of time, silently falling through to the generic
click/type path, which unconditionally escalated every single assert
step regardless of real page content (see docs/decisions.md D-055).
Nothing caught this until a live run against a real site surfaced it.

Two ActionType members (CAPABILITY_CHECK, WAIT_FOR_HUMAN_ACTION) are
intercepted entirely inside orchestrator/run_engine.py's own top-level
dispatch, *before* execute_step is ever called -- so they're
deliberately excluded from the execute_step behavioral checks below and
covered by their own dedicated assertion instead. If a new ActionType
is ever added and this file isn't updated to cover it, these tests fail
loudly rather than the new action type silently falling through to
whatever the generic fallback happens to do.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agents.vision.executor import execute_step
from orchestrator.schemas import ActionType, TestStep, VisionStepInput

from tests.test_vision import make_synthetic_screenshot

# ActionType members handled entirely inside run_engine.py's own
# top-level dispatch (see orchestrator/run_engine.py's
# `if step.action == ActionType.CAPABILITY_CHECK`/`WAIT_FOR_HUMAN_ACTION`
# checks) -- they never reach execute_step at all in real operation, so
# testing execute_step's behavior for them would test dead code, not the
# real dispatch path. Covered instead by test_run_engine_dispatches_every_
# non_vision_action_type below via direct source inspection.
_HANDLED_OUTSIDE_EXECUTE_STEP = {ActionType.CAPABILITY_CHECK, ActionType.WAIT_FOR_HUMAN_ACTION}


@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def test_every_action_type_is_accounted_for_somewhere():
    """
    Sanity check on the exclusion set itself: if a new ActionType is
    added to orchestrator/schemas.py, it must show up in EITHER this
    file's per-action behavioral tests below OR
    _HANDLED_OUTSIDE_EXECUTE_STEP -- there is no third option. This test
    doesn't check *correctness*, just that nothing was forgotten.
    """
    vision_dispatched = {
        ActionType.NAVIGATE_URL,
        ActionType.VISUAL_CLICK,
        ActionType.TYPE_TEXT,
        ActionType.SCROLL,
        ActionType.ASSERT,
    }
    all_covered = vision_dispatched | _HANDLED_OUTSIDE_EXECUTE_STEP
    assert all_covered == set(ActionType), (
        f"ActionType has members not covered by this test file: {set(ActionType) - all_covered}. "
        "Add a behavioral test below (or to _HANDLED_OUTSIDE_EXECUTE_STEP with a real reason) "
        "before shipping the new action type."
    )


def test_navigate_url_does_not_escalate(monkeypatch):
    step = TestStep(step_id=1, action=ActionType.NAVIGATE_URL, url="https://example.com")
    payload = VisionStepInput(step=step, screenshot_path="unused.png")

    from runtime.hooks import browser as browser_hook

    monkeypatch.setattr(browser_hook, "open_url", lambda *a, **k: None)
    result = execute_step(payload)

    assert result.action_taken == "navigate"
    assert result.escalate is False


def test_scroll_does_not_escalate(monkeypatch):
    from runtime.hooks import browser as browser_hook

    monkeypatch.setattr(browser_hook, "dom_scroll", lambda dy: True)

    step = TestStep(step_id=1, action=ActionType.SCROLL)
    payload = VisionStepInput(step=step, screenshot_path="unused.png")
    result = execute_step(payload)

    assert result.action_taken == "scroll"
    assert result.escalate is False


def test_assert_does_not_escalate_with_no_target_description(tmp_dir: Path):
    """The actual regression this whole test file exists for -- see
    D-055/D-056 in docs/decisions.md."""
    path = make_synthetic_screenshot(tmp_dir, [("Welcome", (250, 60))])
    step = TestStep(step_id=1, action=ActionType.ASSERT, expected_state="page_loaded")
    payload = VisionStepInput(step=step, screenshot_path=str(path))
    result = execute_step(payload)

    assert result.action_taken == "none"
    assert result.escalate is False


def test_visual_click_locates_a_real_target(tmp_dir: Path):
    path = make_synthetic_screenshot(tmp_dir, [("Login Button", (300, 40))])
    step = TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login Button")
    payload = VisionStepInput(step=step, screenshot_path=str(path))
    result = execute_step(payload)

    assert result.action_taken == "click"
    assert result.escalate is False


def test_type_text_locates_a_real_field(tmp_dir: Path):
    path = make_synthetic_screenshot(tmp_dir, [("Username", (300, 40))])
    step = TestStep(step_id=1, action=ActionType.TYPE_TEXT, field_description="Username", value_ref="testuser")
    payload = VisionStepInput(step=step, screenshot_path=str(path))
    result = execute_step(payload)

    assert result.action_taken == "type"
    assert result.escalate is False


def test_run_engine_dispatches_every_non_vision_action_type():
    """
    CAPABILITY_CHECK and WAIT_FOR_HUMAN_ACTION are handled entirely
    inside run_engine.py, before execute_step is ever called. This
    confirms both are still explicitly referenced there (source
    inspection, not behavioral -- a full behavioral test for these two
    lives in test_run_engine.py/test_guardrails.py, which already
    exercise them end-to-end).
    """
    import inspect

    from orchestrator import run_engine

    source = inspect.getsource(run_engine)
    for action in _HANDLED_OUTSIDE_EXECUTE_STEP:
        assert f"ActionType.{action.name}" in source, (
            f"orchestrator/run_engine.py no longer appears to dispatch {action.name} explicitly -- "
            "if it now falls through to execute_step, move it out of _HANDLED_OUTSIDE_EXECUTE_STEP "
            "and add a real behavioral test for it above instead."
        )
