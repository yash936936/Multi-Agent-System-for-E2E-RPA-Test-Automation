"""
Regression test for a Phase 6 debug-pass find in orchestrator/run_engine.py:
the CAPABILITY_CHECK cross-modal healing branch used to construct
SkillRecord(trigger=..., fix=..., context=...) -- fields that don't exist
on the SkillRecord schema at all -- and call self.skill_store.add(...),
a method SkillStore has never had (it's save()). Both raised the instant
CrossModalDiagnoser.diagnose() actually returned a healed step (a real,
reachable path once agents/capability/api_adapter.py populates
evidence["healing_hints"] with a snake_case/camelCase drift), crashing
the whole run instead of healing it.

This test drives orchestrator.run_engine.RunEngine.run_spec() through
exactly that path with a stubbed "Capability.check" call_tool: first
call fails with healing_hints that CrossModalDiagnoser can heal, second
call (after the heal) passes.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from orchestrator.memory import RunMemoryStore
from orchestrator.run_engine import RunEngine
from orchestrator.schemas import (
    ActionType,
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


def _make_spec() -> TestSpec:
    step = TestStep(
        step_id=1,
        action=ActionType.CAPABILITY_CHECK,
        capability_type=CapabilityType.API,
        target="https://api.example.com/user",
        capability_params={"method": "GET"},
        expected={"json": {"user_id": 123, "first_name": "Yash"}},
    )
    return TestSpec(test_id="TC-CROSS-MODAL-1", requirement_ref="cross_modal_test", steps=[step])


def test_cross_modal_heal_does_not_crash_and_saves_skill(tmp_dir: Path):
    """First Capability.check call fails with a healable schema-drift hint;
    the diagnoser heals it; the second call passes. Must not crash, and
    must persist a valid SkillRecord via skill_store.save()."""
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")

    calls = {"count": 0}

    def fake_call_tool(name: str, payload):
        if name == "Capability.check":
            calls["count"] += 1
            if calls["count"] == 1:
                return CapabilityCheckResult(
                    capability=CapabilityType.API,
                    passed=False,
                    confidence=0.0,
                    evidence={
                        "json_mismatch": True,
                        "healing_hints": {
                            "expected_keys": ["user_id", "first_name"],
                            "actual_keys": ["userId", "firstName"],
                        },
                    },
                    escalate=True,
                )
            return CapabilityCheckResult(
                capability=CapabilityType.API, passed=True, confidence=1.0,
                evidence={"status_code": 200}, escalate=False,
            )
        raise AssertionError(f"Unexpected tool call: {name}")

    engine = RunEngine(screenshot_provider=lambda run_id, step_id: None, skill_store=skill_store, memory=memory)
    spec = _make_spec()

    result = engine.run_spec(spec, run_id="cross_modal_test_run", call_tool=fake_call_tool)

    assert calls["count"] == 2  # one failure, one heal-retry
    assert result.report.status == RunStatus.PASSED
    assert result.report.escalated_steps == 0

    saved_skills = skill_store.all()
    assert len(saved_skills) == 1
    saved = saved_skills[0]
    assert saved.root_cause == "cross_modal_schema_drift"
    assert saved.proposed_fix == "cross_modal_heal_1"
    assert 0.0 <= saved.confidence <= 1.0
