"""
Spec builder — api/spec_builder.py

Normalizes the loose spec dict the HTTP API accepts (test_name + a list of
steps with friendly action names) into the real orchestrator.schemas.TestSpec
that RunEngine.run_spec() actually executes. Kept separate from the router
so the normalization rules have one place to live and one place to test.

Accepted step shape (all fields optional except `action`):
    {
        "action": "visual_click" | "VISION_CLICK" | "click" | ...,
        "target": "Submit Button",             # -> target_description
        "value": "someone@example.com",         # -> value_ref-free literal, stored via field_description
        "url": "https://...",                   # NAVIGATE_URL steps
        "capability_type": "database",
        "capability_params": {...},
        "expected": {...}
    }
"""
from __future__ import annotations

import uuid
from typing import Any

from orchestrator.schemas import ActionType, CapabilityType, TestSpec, TestStep

# Friendly aliases the UI / older docs used (e.g. VISION_CLICK) mapped onto
# the real ActionType enum values.
_ACTION_ALIASES = {
    "VISION_CLICK": ActionType.VISUAL_CLICK,
    "CLICK": ActionType.VISUAL_CLICK,
    "TYPE": ActionType.TYPE_TEXT,
    "NAVIGATE": ActionType.NAVIGATE_URL,
    "GOTO": ActionType.NAVIGATE_URL,
    "WAIT_FOR_HUMAN": ActionType.WAIT_FOR_HUMAN_ACTION,
}


def _resolve_action(raw: str) -> ActionType:
    if raw is None:
        raise ValueError("Step is missing required field 'action'")
    upper = raw.strip().upper()
    if upper in _ACTION_ALIASES:
        return _ACTION_ALIASES[upper]
    try:
        return ActionType(raw.strip().lower())
    except ValueError:
        valid = ", ".join(a.value for a in ActionType)
        raise ValueError(f"Unknown action '{raw}'. Valid actions: {valid}")


def _resolve_capability_type(raw: Any) -> CapabilityType | None:
    if raw is None:
        return None
    if isinstance(raw, CapabilityType):
        return raw
    try:
        return CapabilityType(str(raw).strip().lower())
    except ValueError:
        valid = ", ".join(c.value for c in CapabilityType)
        raise ValueError(f"Unknown capability_type '{raw}'. Valid types: {valid}")


def build_test_spec(body: dict) -> TestSpec:
    """
    Raises ValueError (caller maps to HTTP 422) on anything that can't be
    turned into a valid TestSpec -- deliberately fails fast at submission
    time rather than deep inside RunEngine.
    """
    raw_steps = body.get("steps")
    if not raw_steps:
        raise ValueError("Spec must include a non-empty 'steps' list")

    steps: list[TestStep] = []
    for idx, raw_step in enumerate(raw_steps, start=1):
        action = _resolve_action(raw_step.get("action"))
        step = TestStep(
            step_id=raw_step.get("step_id", idx),
            action=action,
            target_description=raw_step.get("target") or raw_step.get("target_description"),
            field_description=raw_step.get("value") or raw_step.get("field_description"),
            expected_state=raw_step.get("expected_state"),
            value_ref=raw_step.get("value_ref"),
            url=raw_step.get("url"),
            capability_type=_resolve_capability_type(raw_step.get("capability_type")),
            capability_params=raw_step.get("capability_params") or {},
            target=raw_step.get("target") or "",
            expected=raw_step.get("expected"),
            human_action_timeout_seconds=raw_step.get("human_action_timeout_seconds"),
        )
        steps.append(step)

    test_id = body.get("test_id") or f"TC-API-{uuid.uuid4().hex[:8].upper()}"
    requirement_ref = body.get("test_name") or body.get("requirement_ref") or "api-submitted-run"

    return TestSpec(
        test_id=test_id,
        requirement_ref=requirement_ref,
        preconditions=body.get("preconditions", []),
        steps=steps,
        data_requirements=body.get("data_requirements", []),
        project_tag=body.get("project_tag"),
    )
