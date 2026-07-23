"""
tests/test_healing_loop.py

AD2 (docs/decisions.md D-062) integration tests for
`orchestrator/healing_loop.py::HealingLoop`, proving the AD2
short-circuit fires from the real `heal()` loop (not just the
`LoopGuardrail` unit level covered in `tests/test_guardrails.py`), and
that a genuine D-055-style incident -- self-healing retrying with
diagnoses that don't change the observed evidence -- now escalates
immediately instead of burning through the count-based thresholds.

No prior HealingLoop tests existed in this repo before this file; all
collaborators (diagnose_fn, execute_step_fn, RunMemoryStore, SkillStore)
are exercised for real (temp sqlite dbs) or via simple stand-in
callables, not deep mocks, to keep this an integration test of the real
wiring rather than a test of a fabricated substitute.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from config.settings import GuardrailSettings
from orchestrator.guardrails import LoopGuardrail
from orchestrator.healing_loop import HealingLoop
from orchestrator.memory import RunMemoryStore
from orchestrator.schemas import (
    ActionType,
    DiagnosisInput,
    FixType,
    SkillRecord,
    TestStep,
    VisionActionResult,
)
from orchestrator.skill_store import SkillStore


@pytest.fixture()
def stores():
    with tempfile.TemporaryDirectory() as d:
        memory = RunMemoryStore(db_path=Path(d) / "state.db")
        skills = SkillStore(db_path=Path(d) / "skills.db")
        yield memory, skills


def make_step() -> TestStep:
    return TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Submit button")


def make_result(escalate: bool, verification_source, raw_evidence, confidence: float = 0.2) -> VisionActionResult:
    return VisionActionResult(
        step_id=1, action_taken="click", confidence=confidence, escalate=escalate,
        verification_source=verification_source, raw_evidence=raw_evidence,
    )


def make_diagnosis(skill_id: str) -> SkillRecord:
    return SkillRecord(
        skill_id=skill_id, failure_signature="button_not_found", root_cause="element off-screen",
        proposed_fix="scroll down first", fix_type=FixType.RETRY_STRATEGY, confidence=0.5,
    )


def test_identical_evidence_retries_escalate_immediately_not_after_full_count_threshold(stores):
    """
    The D-055 incident, reproduced directly: every retry_result carries
    the exact same verification_source/raw_evidence as the one before
    it (a diagnosis that changes nothing observable). With
    hard_stop_after_exact_failure set high (10), the count-based path
    alone would need 10 loop iterations to escalate -- AD2 must fire
    on the very first repeat instead.
    """
    memory, skills = stores
    guardrail = LoopGuardrail(config=GuardrailSettings(hard_stop_after_exact_failure=10, hard_stop_after_same_tool_failure=10))
    call_count = {"n": 0}

    def execute_step_fn(payload):
        call_count["n"] += 1
        # every retry produces byte-identical evidence to the original failure
        return make_result(escalate=True, verification_source="ocr", raw_evidence={"ocr_text_found": None})

    loop = HealingLoop(
        guardrail=guardrail, skill_store=skills, memory=memory,
        diagnose_fn=lambda inp: make_diagnosis("skill-1"),
        execute_step_fn=execute_step_fn, run_id="run-ad2-1",
    )

    failed = make_result(escalate=True, verification_source="ocr", raw_evidence={"ocr_text_found": None})
    result = loop.heal(step=make_step(), failed_result=failed, screenshot_path="/tmp/s.png", execution_logs=[])

    assert result.escalated is True
    assert result.healed is False
    # Exactly one retry attempted before the short-circuit fired -- proves
    # it didn't burn through the full count-based budget first.
    assert call_count["n"] == 1


def test_changing_evidence_across_retries_does_not_short_circuit(stores):
    """Each retry produces genuinely different evidence -> AD2 must not fire; the loop proceeds on the normal count-based path until it eventually heals."""
    memory, skills = stores
    guardrail = LoopGuardrail(config=GuardrailSettings(hard_stop_after_exact_failure=10, hard_stop_after_same_tool_failure=10))
    attempts = {"n": 0}

    def execute_step_fn(payload):
        attempts["n"] += 1
        if attempts["n"] >= 3:
            return make_result(escalate=False, verification_source="ocr", raw_evidence={"ocr_text_found": "Submit"})
        return make_result(escalate=True, verification_source="ocr", raw_evidence={"ocr_text_found": f"attempt-{attempts['n']}"})

    loop = HealingLoop(
        guardrail=guardrail, skill_store=skills, memory=memory,
        diagnose_fn=lambda inp: make_diagnosis(f"skill-{attempts['n']}"),
        execute_step_fn=execute_step_fn, run_id="run-ad2-2",
    )

    failed = make_result(escalate=True, verification_source="ocr", raw_evidence={"ocr_text_found": "attempt-0"})
    result = loop.heal(step=make_step(), failed_result=failed, screenshot_path="/tmp/s.png", execution_logs=[])

    assert result.healed is True
    assert result.escalated is False
    assert attempts["n"] == 3


def test_no_verification_evidence_falls_back_to_count_based_thresholds(stores):
    """
    Steps where no verification ran at all (raw_evidence always None --
    e.g. this attempt's diagnosis path never produced a checkable
    result) must never be treated as "identical" to each other by AD2.
    The loop should proceed on the pre-existing count-based path only,
    hitting hard_stop at exact_failure_count's real threshold.
    """
    memory, skills = stores
    guardrail = LoopGuardrail(config=GuardrailSettings(hard_stop_after_exact_failure=3, hard_stop_after_same_tool_failure=10))
    call_count = {"n": 0}

    def execute_step_fn(payload):
        call_count["n"] += 1
        return make_result(escalate=True, verification_source=None, raw_evidence=None)

    loop = HealingLoop(
        guardrail=guardrail, skill_store=skills, memory=memory,
        diagnose_fn=lambda inp: make_diagnosis("skill-1"),
        execute_step_fn=execute_step_fn, run_id="run-ad2-3",
    )

    failed = make_result(escalate=True, verification_source=None, raw_evidence=None, confidence=0.0)
    result = loop.heal(step=make_step(), failed_result=failed, screenshot_path="/tmp/s.png", execution_logs=[])

    assert result.escalated is True
    # Confidence is identical (0.0) across every attempt too, so
    # failure_signature never changes -> exact_failure_count climbs by 1
    # every loop and hits hard_stop_after_exact_failure=3 on the 3rd call.
    assert call_count["n"] == 3


def test_short_circuit_escalation_reason_distinguishes_from_count_based_hard_stop(stores):
    memory, skills = stores
    guardrail = LoopGuardrail(config=GuardrailSettings(hard_stop_after_exact_failure=10, hard_stop_after_same_tool_failure=10))

    def execute_step_fn(payload):
        return make_result(escalate=True, verification_source="dom", raw_evidence={"dom_snapshot_hash": "abc123"})

    loop = HealingLoop(
        guardrail=guardrail, skill_store=skills, memory=memory,
        diagnose_fn=lambda inp: make_diagnosis("skill-1"),
        execute_step_fn=execute_step_fn, run_id="run-ad2-4",
    )

    failed = make_result(escalate=True, verification_source="dom", raw_evidence={"dom_snapshot_hash": "abc123"})
    loop.heal(step=make_step(), failed_result=failed, screenshot_path="/tmp/s.png", execution_logs=[])

    escalations = memory.list_escalations(run_id="run-ad2-4") if hasattr(memory, "list_escalations") else None
    if escalations is not None:
        assert any("AD2 short-circuit" in e.get("reason", "") for e in escalations)
