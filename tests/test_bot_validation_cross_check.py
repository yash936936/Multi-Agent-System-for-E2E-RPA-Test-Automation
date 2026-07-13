"""
Tests for RunEngine's bot-trigger / validation-leg cross-check enforcement
(docs/TRD.md §11.6, docs/Roadmap.md Phase 21c): "no blind trust of
bot-reported success." A CapabilityType.AUTOMATION_ANYWHERE trigger step's
own terminal status is never sufficient alone -- if the spec links it to
one or more WEB_VALIDATION/DATABASE/FILE_SYSTEM validation-leg steps via
`bot_validation_group`, RunEngine only marks the trigger step passed when
the bot succeeded AND at least one grouped validation leg independently
confirmed the expected end state.

Uses RunEngine.run_spec() directly (bypassing Planner), with the real
adapter classes monkeypatched at the class level so no actual network/CLI
calls happen -- this exercises the real dispatch path
(RunEngine -> OrchestratorKernel -> capability_router -> registry ->
adapter.run()), not a stub of it.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agents.capability.automation_anywhere_adapter import AutomationAnywhereAdapter
from agents.capability.db_adapter import DbAdapter
from agents.capability.playwright_validator import PlaywrightValidator
from orchestrator.memory import RunMemoryStore
from orchestrator.run_engine import RunEngine
from orchestrator.schemas import (
    ActionType,
    CapabilityCheckInput,
    CapabilityCheckResult,
    CapabilityType,
    RunStatus,
    TestSpec,
    TestStep,
)
from orchestrator.skill_store import SkillStore


@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def _engine(tmp_dir: Path) -> RunEngine:
    def provider(run_id: str, step_id: int) -> str:  # not used by capability_check steps
        raise AssertionError("screenshot_provider should not be called for capability_check-only specs")

    return RunEngine(
        screenshot_provider=provider,
        skill_store=SkillStore(db_path=tmp_dir / "skills.db"),
        memory=RunMemoryStore(db_path=tmp_dir / "memory.db"),
    )


def _patch_aa_adapter(monkeypatch, passed: bool):
    def fake_run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        return CapabilityCheckResult(
            capability=CapabilityType.AUTOMATION_ANYWHERE,
            passed=passed,
            confidence=1.0,
            evidence={"terminal_status": "COMPLETED" if passed else "FAILED"},
            escalate=not passed,
        )

    monkeypatch.setattr(AutomationAnywhereAdapter, "run", fake_run)


def _patch_web_validator(monkeypatch, passed: bool):
    def fake_run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        return CapabilityCheckResult(
            capability=CapabilityType.WEB_VALIDATION,
            passed=passed,
            confidence=1.0,
            evidence={"contains_text_check": {"found": passed}},
            escalate=not passed,
        )

    monkeypatch.setattr(PlaywrightValidator, "run", fake_run)


def _patch_db_adapter(monkeypatch, passed: bool):
    def fake_run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        return CapabilityCheckResult(
            capability=CapabilityType.DATABASE,
            passed=passed,
            confidence=1.0,
            evidence={"row_count": 1 if passed else 0},
            escalate=not passed,
        )

    monkeypatch.setattr(DbAdapter, "run", fake_run)


def _trigger_step(step_id: int, group: str) -> TestStep:
    return TestStep(
        step_id=step_id,
        action=ActionType.CAPABILITY_CHECK,
        capability_type=CapabilityType.AUTOMATION_ANYWHERE,
        capability_params={"mode": "rest", "control_room_url": "https://x", "bot_id": "1"},
        target="bot-1",
        expected={"terminal_status": "COMPLETED"},
        bot_validation_group=group,
    )


def _web_validation_step(step_id: int, group: str) -> TestStep:
    return TestStep(
        step_id=step_id,
        action=ActionType.CAPABILITY_CHECK,
        capability_type=CapabilityType.WEB_VALIDATION,
        capability_params={"url": "https://example.com/order/1"},
        target="https://example.com/order/1",
        expected={"contains_text": "Order Complete"},
        bot_validation_group=group,
    )


def _db_validation_step(step_id: int, group: str) -> TestStep:
    return TestStep(
        step_id=step_id,
        action=ActionType.CAPABILITY_CHECK,
        capability_type=CapabilityType.DATABASE,
        capability_params={"connection_string": "sqlite://", "query": "SELECT 1"},
        target="orders",
        expected={"row_count": 1},
        bot_validation_group=group,
    )


def test_bot_success_with_confirming_validation_leg_passes(tmp_dir, monkeypatch):
    """Bot COMPLETED + web validation confirms -> trigger step genuinely passes."""
    _patch_aa_adapter(monkeypatch, passed=True)
    _patch_web_validator(monkeypatch, passed=True)

    engine = _engine(tmp_dir)
    spec = TestSpec(
        test_id="TC-AA-001", requirement_ref="REQ-AA",
        steps=[
            _trigger_step(1, "grp1"),
            _web_validation_step(2, "grp1"),
        ],
    )
    result = engine.run_spec(spec, run_id="aa_pass_run")

    assert result.report.status == RunStatus.PASSED
    assert result.report.escalated_steps == 0


def test_bot_success_without_any_confirming_leg_is_escalated(tmp_dir, monkeypatch):
    """
    Bot reports COMPLETED, but the web-validation leg does NOT confirm --
    per TRD §11.6, the trigger step must be corrected to failed/escalated,
    not left passed just because the bot said so. (The validation leg's
    own failure is also independently escalated on its own merits -- that's
    correct and expected, separate from the trigger-step override.)
    """
    _patch_aa_adapter(monkeypatch, passed=True)
    _patch_web_validator(monkeypatch, passed=False)

    engine = _engine(tmp_dir)
    spec = TestSpec(
        test_id="TC-AA-002", requirement_ref="REQ-AA",
        steps=[
            _trigger_step(1, "grp1"),
            _web_validation_step(2, "grp1"),
        ],
    )
    result = engine.run_spec(spec, run_id="aa_fail_run")

    assert result.report.status == RunStatus.ESCALATED
    # Both the trigger step (cross-check override) and the validation leg
    # (its own genuine failure) end up escalated.
    assert result.report.escalated_steps == 2

    raw_path = Path(result.report.report_paths["raw_json"])
    raw = raw_path.read_text()
    assert "cross_check_failed" in raw


def test_bot_success_with_at_least_one_of_multiple_legs_confirming_passes(tmp_dir, monkeypatch):
    """
    Bot succeeds, web validation leg does NOT confirm, but the database leg
    DOES -- per TRD §11.6 ("at least one... must independently confirm"),
    the trigger step itself must NOT be overridden/downgraded in this case.
    (The web-validation leg still legitimately escalates on its own merits
    -- that's separate from whether the trigger step's cross-check passes.)
    """
    _patch_aa_adapter(monkeypatch, passed=True)
    _patch_web_validator(monkeypatch, passed=False)
    _patch_db_adapter(monkeypatch, passed=True)

    engine = _engine(tmp_dir)
    spec = TestSpec(
        test_id="TC-AA-003", requirement_ref="REQ-AA",
        steps=[
            _trigger_step(1, "grp1"),
            _web_validation_step(2, "grp1"),
            _db_validation_step(3, "grp1"),
        ],
    )
    result = engine.run_spec(spec, run_id="aa_partial_confirm_run")

    # Only the web-validation leg's own failure is escalated -- the trigger
    # step (step_id=1) must NOT have been downgraded, since the db leg
    # independently confirmed the bot's effect.
    assert result.report.escalated_steps == 1

    raw_path = Path(result.report.report_paths["raw_json"])
    raw = raw_path.read_text()
    assert "cross_check_failed" not in raw

    import json
    raw_data = json.loads(raw_path.read_text())
    trigger_result = next(r for r in raw_data["step_results"] if r["step_id"] == 1)
    assert trigger_result["assertion_passed"] is not False
    assert trigger_result["escalate"] is False


def test_bot_failure_is_unaffected_by_cross_check(tmp_dir, monkeypatch):
    """If the bot itself fails, the trigger step is already escalated -- the
    cross-check shouldn't need to (and doesn't) add anything extra."""
    _patch_aa_adapter(monkeypatch, passed=False)
    _patch_web_validator(monkeypatch, passed=True)

    engine = _engine(tmp_dir)
    spec = TestSpec(
        test_id="TC-AA-004", requirement_ref="REQ-AA",
        steps=[
            _trigger_step(1, "grp1"),
            _web_validation_step(2, "grp1"),
        ],
    )
    result = engine.run_spec(spec, run_id="aa_bot_failed_run")

    assert result.report.status == RunStatus.ESCALATED
    assert result.report.escalated_steps == 1


def test_trigger_with_no_bot_validation_group_is_unaffected(tmp_dir, monkeypatch):
    """Steps with no bot_validation_group behave exactly as before -- the
    cross-check must be opt-in, never applied implicitly."""
    _patch_aa_adapter(monkeypatch, passed=True)

    engine = _engine(tmp_dir)
    spec = TestSpec(
        test_id="TC-AA-005", requirement_ref="REQ-AA",
        steps=[
            TestStep(
                step_id=1,
                action=ActionType.CAPABILITY_CHECK,
                capability_type=CapabilityType.AUTOMATION_ANYWHERE,
                capability_params={"mode": "rest", "control_room_url": "https://x", "bot_id": "1"},
                target="bot-1",
                expected={"terminal_status": "COMPLETED"},
                # no bot_validation_group set
            ),
        ],
    )
    result = engine.run_spec(spec, run_id="aa_no_group_run")

    assert result.report.status == RunStatus.PASSED
    assert result.report.escalated_steps == 0


def test_trigger_group_with_no_validation_steps_present_is_escalated(tmp_dir, monkeypatch):
    """A group tag with only a trigger step and no validation legs anywhere
    in the spec still can't be trusted on the bot's word alone."""
    _patch_aa_adapter(monkeypatch, passed=True)

    engine = _engine(tmp_dir)
    spec = TestSpec(
        test_id="TC-AA-006", requirement_ref="REQ-AA",
        steps=[_trigger_step(1, "grp_orphan")],
    )
    result = engine.run_spec(spec, run_id="aa_orphan_group_run")

    assert result.report.status == RunStatus.ESCALATED
    assert result.report.escalated_steps == 1
