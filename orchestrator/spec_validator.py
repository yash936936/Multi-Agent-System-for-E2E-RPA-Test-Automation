"""
Spec-level action/target-type validation — orchestrator/spec_validator.py

Phase T (docs/Roadmap.md, docs/decisions.md): a new pre-execution
validation pass that checks the whole `TestSpec` for action/target-type
compatibility *before any step runs*, instead of discovering a
structurally-broken or semantically-mismatched step only after the vision
pipeline has already burned a full OCR/DOM cycle (and possibly a
self-heal retry loop) trying to act on it.

Two independent kinds of check, deliberately different severities:

1. **Structural completeness (severity="error", blocks the run).**
   A step's required fields for its own `action`/`capability_type` are
   simply missing -- e.g. a `NAVIGATE_URL` step with no `url`, a
   `VISUAL_CLICK` step with no `target_description`, a `CAPABILITY_CHECK`
   step with neither `target` nor `capability_params` set. These are
   unambiguous: the step cannot possibly succeed as written, so
   `RunEngine.run_spec()` raises `SpecValidationError` before touching
   memory/the aggregator/any screenshot -- nothing runs, nothing is
   half-recorded.

2. **Action/target-type mismatch heuristic (severity="warning", never
   blocks).** A vision-driven step (`VISUAL_CLICK`/`TYPE_TEXT`/`SCROLL`)
   whose `target_description`/`field_description` text strongly suggests
   it's actually describing a backend/API/bot/database target rather than
   a real UI element -- e.g. "call the payroll API" as a `VISUAL_CLICK`
   target. This is exactly the plan's own example: it should have been a
   `CapabilityType.AUTOMATION_ANYWHERE`/`API`/`DATABASE` capability check
   instead, and running it as a vision action would burn through the
   entire OCR/DOM pipeline only to fail with a confusing "couldn't find
   that on screen" miss. This check is inherently fuzzy (a UI button
   genuinely labeled "API Settings" is a legitimate, real target), so it's
   a warning, surfaced to whoever's running the spec, never a hard block.

Rules are intentionally simple and enumerable rather than a generic
"smart" validator -- easy to reason about, easy to extend one rule at a
time, and every rule here is unit-tested individually.
"""
from __future__ import annotations

import re
from typing import List, Literal

from pydantic import BaseModel

from orchestrator.schemas import ActionType, CapabilityType, TestSpec, TestStep


class SpecValidationIssue(BaseModel):
    step_id: int
    severity: Literal["error", "warning"]
    code: str
    message: str


class SpecValidationError(Exception):
    """Raised by RunEngine.run_spec() when validate_spec() finds any error-severity issue."""

    def __init__(self, issues: List[SpecValidationIssue]) -> None:
        self.issues = issues
        error_lines = [f"  - step {i.step_id} [{i.code}]: {i.message}" for i in issues if i.severity == "error"]
        super().__init__(
            "Spec failed pre-execution validation -- fix these before the run can start:\n"
            + "\n".join(error_lines)
        )


# Keywords strongly suggesting a step's target is a backend/API/bot/database
# concept, not a real on-screen UI element. Deliberately conservative (few,
# high-signal terms) -- the goal is catching an obvious spec-authoring
# mismatch, not flagging every UI element that happens to mention a
# technical word (a button genuinely labeled "API Settings" is legitimate;
# see the module docstring).
_BACKEND_TARGET_KEYWORDS = (
    "rest api", "api endpoint", " endpoint", "webhook", "sql query",
    "database table", "control room", "automation anywhere bot",
    "trigger the bot", "trigger a bot", "s3 bucket", "azure blob",
    "sharepoint site", "sftp server", "ftp server", "email inbox",
    "cron job", "database record",
)

_CAPABILITY_TYPES_MENTIONED = {
    "rest api": CapabilityType.API,
    "api endpoint": CapabilityType.API,
    " endpoint": CapabilityType.API,
    "webhook": CapabilityType.API,
    "sql query": CapabilityType.DATABASE,
    "database table": CapabilityType.DATABASE,
    "database record": CapabilityType.DATABASE,
    "control room": CapabilityType.AUTOMATION_ANYWHERE,
    "automation anywhere bot": CapabilityType.AUTOMATION_ANYWHERE,
    "trigger the bot": CapabilityType.AUTOMATION_ANYWHERE,
    "trigger a bot": CapabilityType.AUTOMATION_ANYWHERE,
    "s3 bucket": CapabilityType.CLOUD,
    "azure blob": CapabilityType.AZURE_BLOB,
    "sharepoint site": CapabilityType.SHAREPOINT,
    "sftp server": CapabilityType.FILE_SYSTEM,
    "ftp server": CapabilityType.FILE_SYSTEM,
    "email inbox": CapabilityType.EMAIL,
    "cron job": CapabilityType.WORKFLOW,
}

_VISION_DRIVEN_ACTIONS = (ActionType.VISUAL_CLICK, ActionType.TYPE_TEXT, ActionType.SCROLL)


def validate_spec(spec: TestSpec) -> List[SpecValidationIssue]:
    """Returns every issue found across the whole spec -- both errors and warnings."""
    issues: List[SpecValidationIssue] = []
    for step in spec.steps:
        issues.extend(_validate_step_completeness(step))
        issues.extend(_validate_step_target_type_match(step))
    return issues


def validate_spec_or_raise(spec: TestSpec) -> List[SpecValidationIssue]:
    """
    Raises SpecValidationError if any error-severity issue is found.
    Returns the full issue list (including warnings) otherwise, so the
    caller can still surface non-blocking warnings.
    """
    issues = validate_spec(spec)
    if any(i.severity == "error" for i in issues):
        raise SpecValidationError(issues)
    return issues


def _validate_step_completeness(step: TestStep) -> List[SpecValidationIssue]:
    issues: List[SpecValidationIssue] = []

    if step.action == ActionType.NAVIGATE_URL:
        if not step.url:
            issues.append(SpecValidationIssue(
                step_id=step.step_id, severity="error", code="missing_url",
                message="NAVIGATE_URL step has no 'url' set -- there's nowhere for AURA to navigate to.",
            ))

    elif step.action == ActionType.VISUAL_CLICK:
        if not step.target_description:
            issues.append(SpecValidationIssue(
                step_id=step.step_id, severity="error", code="missing_target_description",
                message="VISUAL_CLICK step has no 'target_description' -- nothing for OCR/DOM to look for on screen.",
            ))

    elif step.action == ActionType.TYPE_TEXT:
        if not step.field_description:
            issues.append(SpecValidationIssue(
                step_id=step.step_id, severity="error", code="missing_field_description",
                message="TYPE_TEXT step has no 'field_description' -- nothing for OCR/DOM to locate to type into.",
            ))

    elif step.action == ActionType.CAPABILITY_CHECK:
        if not step.target and not step.capability_params:
            issues.append(SpecValidationIssue(
                step_id=step.step_id, severity="error", code="missing_capability_target",
                message=(
                    f"CAPABILITY_CHECK step (capability_type={step.capability_type}) has neither "
                    "'target' nor 'capability_params' set -- there's nothing for the adapter to check."
                ),
            ))

    elif step.action == ActionType.WAIT_FOR_HUMAN_ACTION:
        pass  # no required fields -- a bare "wait for any change" is valid on its own

    return issues


def _validate_step_target_type_match(step: TestStep) -> List[SpecValidationIssue]:
    """Heuristic check: does a vision-driven step's own description sound like
    it's actually describing a non-UI, backend-style target instead?"""
    if step.action not in _VISION_DRIVEN_ACTIONS:
        return []

    text = " ".join(filter(None, [step.target_description, step.field_description])).lower()
    if not text:
        return []

    for keyword in _BACKEND_TARGET_KEYWORDS:
        if keyword in text:
            suggested = _CAPABILITY_TYPES_MENTIONED.get(keyword)
            suggestion = f" Consider CapabilityType.{suggested.value.upper()} instead." if suggested else ""
            return [SpecValidationIssue(
                step_id=step.step_id, severity="warning", code="possible_action_target_mismatch",
                message=(
                    f"{step.action.value} step's description mentions '{keyword.strip()}', which usually "
                    f"describes a backend/API target, not a real on-screen UI element.{suggestion} "
                    "If this genuinely is a UI element (e.g. a button literally labeled with this text), "
                    "this warning can be ignored."
                ),
            )]

    return []
