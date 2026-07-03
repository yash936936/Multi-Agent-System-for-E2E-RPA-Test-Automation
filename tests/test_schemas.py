"""
Round-trip validation tests for orchestrator/schemas.py.

These lock down the shapes given in TRD.md §4 so later phases can't
silently drift from the documented contract.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from orchestrator.schemas import (
    ActionType,
    AssertionType,
    DataRequirements,
    DiagnosisInput,
    FixType,
    RequirementInput,
    RunReport,
    RunStatus,
    SkillRecord,
    SyntheticDataRecord,
    TestSpec,
    TestStep,
    ToolCall,
    ToolResponse,
    VisionActionResult,
    VisionStepInput,
)


def test_test_spec_matches_trd_example():
    """Shape lifted directly from TRD.md §4.1."""
    raw = {
        "test_id": "TC-LOGIN-001",
        "requirement_ref": "REQ-4.2",
        "preconditions": ["app_launched", "user_logged_out"],
        "steps": [
            {
                "step_id": 1,
                "action": "visual_click",
                "target_description": "Login button, top-right",
                "expected_state": "login_modal_visible",
            },
            {
                "step_id": 2,
                "action": "type_text",
                "field_description": "Username field",
                "value_ref": "synthetic.username",
            },
        ],
        "assertions": [{"type": "visual_state", "expected": "dashboard_visible"}],
        "data_requirements": ["username", "password", "edge_case_unicode_name"],
    }
    spec = TestSpec.model_validate(raw)
    assert spec.test_id == "TC-LOGIN-001"
    assert spec.steps[0].action == ActionType.VISUAL_CLICK
    assert spec.assertions[0].type == AssertionType.VISUAL_STATE

    # round trip through JSON
    reloaded = TestSpec.model_validate(json.loads(spec.model_dump_json()))
    assert reloaded == spec


def test_test_spec_requires_at_least_one_step():
    with pytest.raises(ValidationError):
        TestSpec(test_id="TC-EMPTY", requirement_ref="REQ-0", steps=[])


def test_vision_action_result_matches_trd_example():
    """Shape lifted directly from TRD.md §4.2."""
    raw = {
        "step_id": 1,
        "action_taken": "click",
        "target_coords": [1423, 87],
        "confidence": 0.94,
        "escalate": False,
        "screenshot_ref": "run_042/step_001.png",
    }
    result = VisionActionResult.model_validate(raw)
    assert result.confidence == 0.94
    assert result.target_coords == (1423, 87)

    reloaded = VisionActionResult.model_validate(json.loads(result.model_dump_json()))
    assert reloaded == result


def test_vision_action_result_confidence_bounds():
    with pytest.raises(ValidationError):
        VisionActionResult(step_id=1, action_taken="click", confidence=1.5)
    with pytest.raises(ValidationError):
        VisionActionResult(step_id=1, action_taken="click", confidence=-0.1)


def test_skill_record_matches_trd_example():
    """Shape lifted directly from TRD.md §4.3."""
    raw = {
        "skill_id": "SKILL-2026-0417",
        "failure_signature": "login_button_not_found_after_css_update",
        "root_cause": "Button relocated from top-right to top-center; label text unchanged",
        "proposed_fix": "Broaden visual search region to full header bar before failing",
        "confidence": 0.87,
        "applied_count": 0,
        "created_by": "planner_agent",
        "timestamp": "2026-06-15T10:22:00Z",
    }
    skill = SkillRecord.model_validate(raw)
    assert skill.fix_type == FixType.RETRY_STRATEGY  # default
    reloaded = SkillRecord.model_validate(json.loads(skill.model_dump_json()))
    assert reloaded.skill_id == skill.skill_id


def test_run_report_matches_trd_example():
    """Shape lifted directly from TRD.md §4.4."""
    raw = {
        "run_id": "run_042",
        "status": "passed_with_healing",
        "total_steps": 20,
        "self_healed_steps": 3,
        "escalated_steps": 1,
        "duration_seconds": 412,
        "report_paths": {"html": "reports/run_042.html", "pdf": "reports/run_042.pdf"},
    }
    report = RunReport.model_validate(raw)
    assert report.status == RunStatus.PASSED_WITH_HEALING
    reloaded = RunReport.model_validate(json.loads(report.model_dump_json()))
    assert reloaded == report


def test_tool_call_and_response_envelope():
    """Shape lifted directly from TRD.md §5.1."""
    call = ToolCall(name="Vision.execute_step", arguments={"step_id": 1, "screenshot": "..."})
    response = ToolResponse(name=call.name, result={"target_coords": [1423, 87], "confidence": 0.94})
    assert response.ok is True
    assert response.result["confidence"] == 0.94


def test_requirement_input_and_diagnosis_input_roundtrip():
    step = TestStep(step_id=7, action=ActionType.ASSERT, expected_state="dashboard_visible")

    req_input = RequirementInput(requirement_text="User can log in with valid credentials.")
    assert req_input.skill_hints == []

    diag_input = DiagnosisInput(
        failed_step=step,
        before_screenshot="run_042/step_007_before.png",
        after_screenshot="run_042/step_007_after.png",
        execution_logs=["click dispatched", "assertion failed"],
    )
    reloaded = DiagnosisInput.model_validate(json.loads(diag_input.model_dump_json()))
    assert reloaded.failed_step.step_id == 7


def test_vision_step_input_and_data_requirements_roundtrip():
    step = TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login button")
    vsi = VisionStepInput(step=step, screenshot_path="runtime/screenshots/run_001/step_001.png")
    assert vsi.skill_hint is None

    dr = DataRequirements(fields=["username", "password"], test_id="TC-LOGIN-001")
    record = SyntheticDataRecord(test_id=dr.test_id, values={"username": "jane.doe@example.com"})
    assert record.values["username"].endswith("@example.com")
