"""
Shared data contracts for AURA.

Every agent (Planner, Vision, DataSynth) and the Orchestrator kernel import
these models rather than defining their own — this is what makes the
tool-calling protocol in TRD.md §5.1 actually type-safe end to end.

Schema shapes are taken directly from TRD.md §4 (Test Spec, Vision Action
Result, Diagnostic/Skill Record, Run Report) plus a few small input-side
models needed to make each tool call's `arguments` payload well-typed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------

class ActionType(str, Enum):
    NAVIGATE_URL = "navigate_url"
    VISUAL_CLICK = "visual_click"
    TYPE_TEXT = "type_text"
    SCROLL = "scroll"
    ASSERT = "assert"
    # Phase 13 — the universal-platform pivot's routing hook. A step with
    # this action type carries no Vision Core semantics at all; it's
    # dispatched to a CapabilityAdapter (see orchestrator/capability_adapter.py)
    # keyed on TestStep.capability_type instead.
    CAPABILITY_CHECK = "capability_check"


class AssertionType(str, Enum):
    VISUAL_STATE = "visual_state"


class RunStatus(str, Enum):
    PASSED = "passed"
    PASSED_WITH_HEALING = "passed_with_healing"
    FAILED = "failed"
    ESCALATED = "escalated"
    IN_PROGRESS = "in_progress"


class FixType(str, Enum):
    RETRY_STRATEGY = "retry_strategy"
    SPEC_CORRECTION = "spec_correction"


class CapabilityType(str, Enum):
    """
    Phase 13 foundation only — lists every adapter the roadmap (Phases
    14-16) will eventually register. No adapter beyond FAKE exists yet;
    declaring the full set now means TestStep.capability_type is
    forward-compatible and later phases don't need a schema migration to
    add API/DATABASE/EMAIL etc., only a new CapabilityAdapter registration.
    """
    FAKE = "fake"  # Phase 13 — canned-result adapter proving the routing path
    API = "api"  # Phase 14
    DATABASE = "database"  # Phase 14
    EMAIL = "email"  # Phase 14
    FILE = "file"  # Phase 15
    EXCEL = "excel"  # Phase 15
    PDF = "pdf"  # Phase 15
    CLOUD = "cloud"  # Phase 16


# --------------------------------------------------------------------------
# 4.1 Test Spec (Planner output)
# --------------------------------------------------------------------------

class TestStep(BaseModel):
    step_id: int
    action: ActionType
    target_description: Optional[str] = None
    field_description: Optional[str] = None
    expected_state: Optional[str] = None
    value_ref: Optional[str] = None
    # Populated for ActionType.NAVIGATE_URL steps -- the URL to open before
    # the rest of the spec's steps run. Kept as its own field (rather than
    # overloading target_description) so downstream consumers (executor,
    # report rendering) can tell "this step's target is a URL" without
    # string-sniffing.
    url: Optional[str] = None
    # Phase 13 — populated for ActionType.CAPABILITY_CHECK steps only.
    # capability_type selects which CapabilityAdapter the run engine routes
    # to; capability_params is the adapter-specific payload (e.g. a SQL
    # query for the future db_adapter, an endpoint+method for api_adapter).
    # Kept as a free-form dict rather than a union of per-adapter models so
    # this schema doesn't need to change every time Phase 14-16 adds an
    # adapter -- each adapter validates its own params internally.
    capability_type: Optional[CapabilityType] = None
    capability_params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("capability_type")
    @classmethod
    def capability_type_requires_matching_action(cls, v, info):
        # Belt-and-suspenders: doesn't block construction (action may not be
        # set yet depending on field order during validation), just guards
        # against the common authoring mistake of setting capability_type
        # on a non-CAPABILITY_CHECK step and having it silently ignored.
        action = info.data.get("action")
        if v is not None and action is not None and action != ActionType.CAPABILITY_CHECK:
            raise ValueError("capability_type may only be set when action == CAPABILITY_CHECK")
        return v


class Assertion(BaseModel):
    type: AssertionType
    expected: str


class TestSpec(BaseModel):
    test_id: str
    requirement_ref: str
    preconditions: list[str] = Field(default_factory=list)
    steps: list[TestStep]
    assertions: list[Assertion] = Field(default_factory=list)
    data_requirements: list[str] = Field(default_factory=list)

    @field_validator("steps")
    @classmethod
    def must_have_at_least_one_step(cls, v: list[TestStep]) -> list[TestStep]:
        if not v:
            raise ValueError("TestSpec must contain at least one step")
        return v


# --------------------------------------------------------------------------
# Phase 13 — Capability adapter contract
# --------------------------------------------------------------------------

class CapabilityCheckInput(BaseModel):
    """Input to Capability.check (orchestrator/capability_router.py) and to
    every CapabilityAdapter.run() implementation."""
    step: TestStep
    params: dict[str, Any] = Field(default_factory=dict)


class CapabilityResult(BaseModel):
    """
    Output of a CapabilityAdapter.run() call. Deliberately shaped like a
    non-visual sibling of VisionActionResult: `success`/`details` stand in
    for Vision's coordinate/confidence-based result, since a DB row check
    or API assertion has no on-screen location to report.
    """
    step_id: int
    capability_type: CapabilityType
    success: bool
    details: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    escalate: bool = False
    error: Optional[str] = None


# --------------------------------------------------------------------------
# 4.2 Vision Action Result
# --------------------------------------------------------------------------

class VisionActionResult(BaseModel):
    step_id: int
    action_taken: Literal["navigate", "click", "type", "scroll", "assert", "capability_check", "none"]
    target_coords: Optional[tuple[int, int]] = None
    confidence: float = Field(ge=0.0, le=1.0)
    escalate: bool = False
    screenshot_ref: Optional[str] = None
    assertion_passed: Optional[bool] = None
    # Phase 13 — populated only when action_taken == "capability_check", so
    # the raw CapabilityResult (adapter type, details dict) survives into
    # ReportAggregator's raw_results.json without ReportAggregator itself
    # needing to know about adapters yet.
    capability_result: Optional[CapabilityResult] = None


# --------------------------------------------------------------------------
# 4.3 Diagnostic / Skill Record
# --------------------------------------------------------------------------

class SkillRecord(BaseModel):
    skill_id: str
    failure_signature: str
    root_cause: str
    proposed_fix: str
    fix_type: FixType = FixType.RETRY_STRATEGY
    confidence: float = Field(ge=0.0, le=1.0)
    applied_count: int = 0
    created_by: str = "planner_agent"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# --------------------------------------------------------------------------
# 4.4 Run Report
# --------------------------------------------------------------------------

class RunReport(BaseModel):
    run_id: str
    status: RunStatus
    total_steps: int
    self_healed_steps: int = 0
    escalated_steps: int = 0
    duration_seconds: float = 0.0
    report_paths: dict[str, str] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# Tool call / tool response envelope (TRD §5.1)
# --------------------------------------------------------------------------

class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]


class ToolResponse(BaseModel):
    name: str
    result: dict[str, Any]
    ok: bool = True
    error: Optional[str] = None


# --------------------------------------------------------------------------
# Tool input-side models (arguments payloads for each registered tool)
# --------------------------------------------------------------------------

class RequirementInput(BaseModel):
    """Input to Planner.generate_spec"""
    requirement_text: str
    source_path: Optional[str] = None
    skill_hints: list[SkillRecord] = Field(default_factory=list)


class DiagnosisInput(BaseModel):
    """Input to Planner.diagnose"""
    failed_step: TestStep
    before_screenshot: Optional[str] = None
    after_screenshot: Optional[str] = None
    execution_logs: list[str] = Field(default_factory=list)
    network_trace: Optional[str] = None


class VisionStepInput(BaseModel):
    """Input to Vision.execute_step"""
    step: TestStep
    screenshot_path: str
    skill_hint: Optional[SkillRecord] = None
    value: Optional[str] = None


class DataRequirements(BaseModel):
    """Input to DataSynth.generate"""
    fields: list[str]
    test_id: Optional[str] = None


class SyntheticDataRecord(BaseModel):
    """Output of DataSynth.generate"""
    test_id: Optional[str] = None
    values: dict[str, Any]
