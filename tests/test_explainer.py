"""
tests/test_explainer.py

Covers agents/planner/explainer.py -- the "explain this test" plain-English
narrative generator (feature roadmap item), which turns a structured
TestSpec back into prose for non-technical report readers.
"""
from __future__ import annotations

from agents.planner.explainer import explain_spec
from orchestrator.schemas import ActionType, Assertion, AssertionType, TestSpec, TestStep


def test_explain_spec_mentions_test_id_and_requirement_ref():
    spec = TestSpec(
        test_id="TC-LOGIN-001",
        requirement_ref="TC-LOGIN-001",
        steps=[TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login button")],
    )
    text = explain_spec(spec)
    assert "TC-LOGIN-001" in text


def test_explain_spec_describes_click_step():
    spec = TestSpec(
        test_id="TC-1",
        requirement_ref="TC-1",
        steps=[TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login button")],
    )
    text = explain_spec(spec)
    assert "click Login button" in text


def test_explain_spec_describes_type_text_step():
    spec = TestSpec(
        test_id="TC-1",
        requirement_ref="TC-1",
        steps=[TestStep(step_id=1, action=ActionType.TYPE_TEXT, field_description="Username field")],
    )
    text = explain_spec(spec)
    assert "enter a value into Username field" in text


def test_explain_spec_chains_multiple_steps_with_then():
    spec = TestSpec(
        test_id="TC-1",
        requirement_ref="TC-1",
        steps=[
            TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login button"),
            TestStep(step_id=2, action=ActionType.TYPE_TEXT, field_description="Username field"),
            TestStep(step_id=3, action=ActionType.SCROLL),
        ],
    )
    text = explain_spec(spec)
    assert "then" in text
    assert "scroll the screen" in text


def test_explain_spec_includes_preconditions():
    spec = TestSpec(
        test_id="TC-1",
        requirement_ref="TC-1",
        preconditions=["user_is_logged_out"],
        steps=[TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login button")],
    )
    text = explain_spec(spec)
    assert "user is logged out" in text


def test_explain_spec_includes_assertions():
    spec = TestSpec(
        test_id="TC-1",
        requirement_ref="TC-1",
        steps=[TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login button")],
        assertions=[Assertion(type=AssertionType.VISUAL_STATE, expected="dashboard_visible")],
    )
    text = explain_spec(spec)
    assert "dashboard visible" in text


def test_explain_spec_separates_regular_and_edge_case_data_requirements():
    spec = TestSpec(
        test_id="TC-1",
        requirement_ref="TC-1",
        steps=[TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login button")],
        data_requirements=["username", "edge_case_empty_password"],
    )
    text = explain_spec(spec)
    assert "username" in text
    assert "edge-case data covering empty password" in text


def test_explain_spec_returns_non_empty_string_for_minimal_spec():
    spec = TestSpec(
        test_id="TC-MIN",
        requirement_ref="TC-MIN",
        steps=[TestStep(step_id=1, action=ActionType.ASSERT, expected_state="page_loaded")],
    )
    text = explain_spec(spec)
    assert len(text) > 0
    assert "TC-MIN" in text
