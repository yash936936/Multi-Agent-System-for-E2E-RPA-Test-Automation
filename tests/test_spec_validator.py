"""
Unit tests for orchestrator/spec_validator.py (Phase T: spec-level
action/target-type validation pass).
"""
from __future__ import annotations

import pytest

from orchestrator.schemas import ActionType, CapabilityType, TestSpec, TestStep
from orchestrator.spec_validator import (
    SpecValidationError,
    validate_spec,
    validate_spec_or_raise,
)


def _spec(steps: list[TestStep]) -> TestSpec:
    return TestSpec(test_id="TC-VALIDATE-001", requirement_ref="REQ-VALIDATE", steps=steps)


# --- Structural completeness (error severity) ---

def test_navigate_url_missing_url_is_an_error():
    spec = _spec([TestStep(step_id=1, action=ActionType.NAVIGATE_URL)])
    issues = validate_spec(spec)
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].code == "missing_url"


def test_navigate_url_with_url_has_no_issues():
    spec = _spec([TestStep(step_id=1, action=ActionType.NAVIGATE_URL, url="https://example.com")])
    assert validate_spec(spec) == []


def test_visual_click_missing_target_description_is_an_error():
    spec = _spec([TestStep(step_id=1, action=ActionType.VISUAL_CLICK)])
    issues = validate_spec(spec)
    assert len(issues) == 1
    assert issues[0].code == "missing_target_description"
    assert issues[0].severity == "error"


def test_type_text_missing_field_description_is_an_error():
    spec = _spec([TestStep(step_id=1, action=ActionType.TYPE_TEXT)])
    issues = validate_spec(spec)
    assert len(issues) == 1
    assert issues[0].code == "missing_field_description"


def test_capability_check_with_neither_target_nor_params_is_an_error():
    spec = _spec([
        TestStep(step_id=1, action=ActionType.CAPABILITY_CHECK, capability_type=CapabilityType.API)
    ])
    issues = validate_spec(spec)
    assert len(issues) == 1
    assert issues[0].code == "missing_capability_target"


def test_capability_check_with_target_only_has_no_issues():
    spec = _spec([
        TestStep(step_id=1, action=ActionType.CAPABILITY_CHECK, capability_type=CapabilityType.API, target="https://api.example.com")
    ])
    assert validate_spec(spec) == []


def test_capability_check_with_params_only_has_no_issues():
    spec = _spec([
        TestStep(
            step_id=1, action=ActionType.CAPABILITY_CHECK, capability_type=CapabilityType.DATABASE,
            capability_params={"query": "SELECT 1"},
        )
    ])
    assert validate_spec(spec) == []


def test_wait_for_human_action_has_no_required_fields():
    spec = _spec([TestStep(step_id=1, action=ActionType.WAIT_FOR_HUMAN_ACTION)])
    assert validate_spec(spec) == []


def test_scroll_has_no_required_fields():
    spec = _spec([TestStep(step_id=1, action=ActionType.SCROLL)])
    assert validate_spec(spec) == []


# --- validate_spec_or_raise ---

def test_validate_spec_or_raise_raises_on_error():
    spec = _spec([TestStep(step_id=1, action=ActionType.NAVIGATE_URL)])
    with pytest.raises(SpecValidationError) as exc_info:
        validate_spec_or_raise(spec)
    assert "missing_url" in str(exc_info.value)
    assert exc_info.value.issues[0].step_id == 1


def test_validate_spec_or_raise_does_not_raise_on_warning_only():
    spec = _spec([
        TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Click the REST API endpoint button")
    ])
    issues = validate_spec_or_raise(spec)  # must not raise
    assert len(issues) == 1
    assert issues[0].severity == "warning"


def test_validate_spec_or_raise_returns_full_issue_list_when_clean():
    spec = _spec([TestStep(step_id=1, action=ActionType.NAVIGATE_URL, url="https://example.com")])
    assert validate_spec_or_raise(spec) == []


# --- Action/target-type mismatch heuristic (warning severity) ---

@pytest.mark.parametrize(
    "text,expected_capability",
    [
        ("Click the button to call the REST API", CapabilityType.API),
        ("Trigger the Automation Anywhere bot for payroll", CapabilityType.AUTOMATION_ANYWHERE),
        ("Open the Control Room dashboard", CapabilityType.AUTOMATION_ANYWHERE),
        ("Check the database table for the new row", CapabilityType.DATABASE),
        ("Verify the S3 bucket contains the export", CapabilityType.CLOUD),
        ("Confirm the SFTP server received the file", CapabilityType.FILE_SYSTEM),
    ],
)
def test_backend_keywords_trigger_mismatch_warning(text, expected_capability):
    spec = _spec([TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description=text)])
    issues = validate_spec(spec)
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].code == "possible_action_target_mismatch"
    assert expected_capability.value.upper() in issues[0].message


def test_normal_ui_target_description_has_no_warning():
    spec = _spec([TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="the blue Submit button")])
    assert validate_spec(spec) == []


def test_type_text_field_description_also_checked_for_mismatch():
    spec = _spec([
        TestStep(step_id=1, action=ActionType.TYPE_TEXT, field_description="the webhook URL field", value_ref="data.username")
    ])
    issues = validate_spec(spec)
    assert len(issues) == 1
    assert issues[0].severity == "warning"


def test_capability_check_steps_are_never_flagged_by_the_heuristic():
    """The heuristic only applies to vision-driven actions -- a CAPABILITY_CHECK
    step legitimately mentioning 'API' in its target is exactly correct, not a mismatch."""
    spec = _spec([
        TestStep(
            step_id=1, action=ActionType.CAPABILITY_CHECK, capability_type=CapabilityType.API,
            target="https://api.example.com/health",
        )
    ])
    assert validate_spec(spec) == []


def test_multiple_steps_each_validated_independently():
    spec = _spec([
        TestStep(step_id=1, action=ActionType.NAVIGATE_URL, url="https://example.com"),
        TestStep(step_id=2, action=ActionType.VISUAL_CLICK),  # error
        TestStep(step_id=3, action=ActionType.VISUAL_CLICK, target_description="call the REST API"),  # warning
    ])
    issues = validate_spec(spec)
    assert len(issues) == 2
    by_step = {i.step_id: i for i in issues}
    assert by_step[2].severity == "error"
    assert by_step[3].severity == "warning"


# --- RunEngine integration: fail-fast before any step executes ---

def test_run_engine_raises_before_any_screenshot_or_memory_write(tmp_path):
    """
    The whole point of Phase T: an invalid spec must fail BEFORE burning
    through the vision pipeline -- not after a wasted OCR/DOM cycle. This
    proves it at the RunEngine level: the screenshot_provider must never
    be called, and memory.start_run() must never be reached, when the
    spec has a structural error.
    """
    from orchestrator.memory import RunMemoryStore
    from orchestrator.run_engine import RunEngine
    from orchestrator.skill_store import SkillStore

    screenshot_calls = []

    def spying_provider(run_id: str, step_id: int) -> str:
        screenshot_calls.append((run_id, step_id))
        raise AssertionError("screenshot_provider must never be called for an invalid spec")

    memory = RunMemoryStore(db_path=tmp_path / "memory.db")
    engine = RunEngine(
        screenshot_provider=spying_provider,
        skill_store=SkillStore(db_path=tmp_path / "skills.db"),
        memory=memory,
    )
    spec = _spec([TestStep(step_id=1, action=ActionType.VISUAL_CLICK)])  # missing target_description

    with pytest.raises(SpecValidationError):
        engine.run_spec(spec, run_id="should_never_start")

    assert screenshot_calls == []
    assert memory.get_resume_point("should_never_start") is None


def test_run_engine_result_carries_non_blocking_warnings(tmp_path):
    """A warning-only spec must run to completion and carry the warning
    through to RunEngineResult.validation_warnings, not silently drop it."""
    from orchestrator.memory import RunMemoryStore
    from orchestrator.run_engine import RunEngine
    from orchestrator.skill_store import SkillStore
    from PIL import Image

    def provider(run_id: str, step_id: int) -> str:
        path = tmp_path / f"{run_id}_{step_id}.png"
        Image.new("RGB", (50, 50), color="white").save(path)
        return str(path)

    engine = RunEngine(
        screenshot_provider=provider,
        skill_store=SkillStore(db_path=tmp_path / "skills2.db"),
        memory=RunMemoryStore(db_path=tmp_path / "memory2.db"),
    )
    spec = _spec([
        TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="click the REST API button")
    ])

    result = engine.run_spec(spec, run_id="warning_only_run")

    assert len(result.validation_warnings) == 1
    assert result.validation_warnings[0].severity == "warning"
