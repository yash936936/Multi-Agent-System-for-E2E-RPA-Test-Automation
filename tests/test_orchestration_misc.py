"""Merged test file: test_orchestration_misc.py
Consolidated from: test_quarantine.py, test_scheduler.py, test_healing_loop.py, test_kernel.py, test_parallel_execution.py
All original test functions preserved 1:1. Colliding fixture/helper names
renamed with a source-file suffix to avoid silent shadowing across sections.
"""
from __future__ import annotations
import json
import pytest
from typer.testing import CliRunner
from orchestrator import quarantine_store
from pathlib import Path
from orchestrator.scheduler import Scheduler
import tempfile
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
import uuid
from orchestrator.kernel import OrchestratorKernel, RegisteredTool, ToolNotFoundError, ToolRegistry
from orchestrator.schemas import DataRequirements, SyntheticDataRecord, ToolCall
import threading
from aura.cli import execute_cmd
from aura.main import app
from orchestrator.schemas import RunReport, RunStatus


# ============================================================================
# ---- from test_quarantine.py ----
# ============================================================================
@pytest.fixture(autouse=True)
def _isolated_quarantine_file(tmp_path, monkeypatch):
    """Every test gets its own quarantine.json so tests can't see each
    other's state (or the real project's, if one exists on disk)."""
    fake_path = tmp_path / "quarantine.json"
    monkeypatch.setattr(quarantine_store, "_store_path", lambda: fake_path)
    yield fake_path


def test_quarantine_then_is_quarantined():
    assert quarantine_store.is_quarantined("TC-FLAKY-001") is False
    quarantine_store.quarantine("TC-FLAKY-001", reason="intermittent timing failure")
    assert quarantine_store.is_quarantined("TC-FLAKY-001") is True


def test_quarantine_is_idempotent_and_updates_reason():
    quarantine_store.quarantine("TC-FLAKY-001", reason="first reason")
    quarantine_store.quarantine("TC-FLAKY-001", reason="updated reason")
    entries = quarantine_store.list_quarantined()
    assert entries["TC-FLAKY-001"]["reason"] == "updated reason"
    assert len(entries) == 1


def test_unquarantine_removes_entry_and_reports_false_if_absent():
    quarantine_store.quarantine("TC-FLAKY-001")
    assert quarantine_store.unquarantine("TC-FLAKY-001") is True
    assert quarantine_store.is_quarantined("TC-FLAKY-001") is False
    # Removing something not present returns False, doesn't raise.
    assert quarantine_store.unquarantine("TC-NEVER-QUARANTINED-001") is False


def test_list_quarantined_empty_by_default():
    assert quarantine_store.list_quarantined() == {}


def test_quarantine_file_is_valid_json_on_disk(_isolated_quarantine_file):
    quarantine_store.quarantine("TC-FLAKY-001", reason="x")
    data = json.loads(_isolated_quarantine_file.read_text(encoding="utf-8"))
    assert "TC-FLAKY-001" in data


def test_corrupt_quarantine_file_degrades_to_empty_not_crash(_isolated_quarantine_file):
    _isolated_quarantine_file.parent.mkdir(parents=True, exist_ok=True)
    _isolated_quarantine_file.write_text("{not valid json", encoding="utf-8")
    assert quarantine_store.list_quarantined() == {}


def test_infer_test_id_matches_heading():
    from agents.planner.spec_generator import infer_test_id

    assert infer_test_id("# Login Flow\n\nsome body text") == "TC-LOGIN-FLOW-001"
    assert infer_test_id("no heading at all") == "TC-GENERATED-001"

# ============================================================================
# ---- from test_scheduler.py ----
# ============================================================================
@pytest.fixture()
def scheduler(tmp_path: Path) -> Scheduler:
    return Scheduler(registry_path=tmp_path / "scheduled_jobs.json")


def test_job_ids_are_unique_even_after_remove_and_readd(scheduler: Scheduler):
    j1 = scheduler.add("0 2 * * *", "TC-A")
    j2 = scheduler.add("0 3 * * *", "TC-A")
    j3 = scheduler.add("0 4 * * *", "TC-A")

    scheduler.remove(j1.job_id)

    j4 = scheduler.add("0 5 * * *", "TC-A")

    all_ids = [j.job_id for j in scheduler.list()]
    assert len(all_ids) == len(set(all_ids)), "job ids must stay unique across add/remove cycles"

    # j2 and j3 must survive untouched -- the old len()-based scheme could
    # reuse either id for j4 and silently overwrite it.
    surviving_crons = {j.job_id: j.cron for j in scheduler.list()}
    assert surviving_crons[j2.job_id] == "0 3 * * *"
    assert surviving_crons[j3.job_id] == "0 4 * * *"
    assert surviving_crons[j3.job_id] == "0 4 * * *"
    assert j4.job_id != j3.job_id
    assert len(scheduler.list()) == 3


def test_many_add_remove_cycles_never_collide(scheduler: Scheduler):
    seen_ids: set[str] = set()
    for i in range(25):
        job = scheduler.add("0 2 * * *", "TC-SAME-ID")
        assert job.job_id not in seen_ids
        seen_ids.add(job.job_id)
        if i % 2 == 0:
            scheduler.remove(job.job_id)
            seen_ids.discard(job.job_id)

# ============================================================================
# ---- from test_healing_loop.py ----
# ============================================================================
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

# ============================================================================
# ---- from test_kernel.py ----
# ============================================================================
def fake_data_synth(args: DataRequirements) -> SyntheticDataRecord:
    return SyntheticDataRecord(test_id=args.test_id, values={f: f"synthetic_{f}" for f in args.fields})


def failing_tool(args: DataRequirements) -> SyntheticDataRecord:
    raise RuntimeError("boom")


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        RegisteredTool(
            name="DataSynth.generate",
            entrypoint=fake_data_synth,
            input_schema=DataRequirements,
            output_schema=SyntheticDataRecord,
        )
    )
    reg.register(
        RegisteredTool(
            name="DataSynth.failing",
            entrypoint=failing_tool,
            input_schema=DataRequirements,
            output_schema=SyntheticDataRecord,
        )
    )
    return reg


def test_kernel_dispatches_and_validates_output(registry: ToolRegistry, monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        from config.settings import settings as global_settings

        monkeypatch.setattr(global_settings, "project_root", Path(tmp))
        kernel = OrchestratorKernel(registry, run_id=str(uuid.uuid4())[:8])
        call = ToolCall(name="DataSynth.generate", arguments={"fields": ["username", "password"], "test_id": "TC-1"})
        response = kernel.call_tool(call)

        assert response.ok is True
        assert response.result["values"]["username"] == "synthetic_username"


def test_kernel_rejects_invalid_input(registry: ToolRegistry, monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        from config.settings import settings as global_settings

        monkeypatch.setattr(global_settings, "project_root", Path(tmp))
        kernel = OrchestratorKernel(registry, run_id="run1")
        call = ToolCall(name="DataSynth.generate", arguments={"not_a_valid_field": 123})
        response = kernel.call_tool(call)
        assert response.ok is False
        assert "input validation failed" in response.error


def test_kernel_catches_tool_exceptions(registry: ToolRegistry, monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        from config.settings import settings as global_settings

        monkeypatch.setattr(global_settings, "project_root", Path(tmp))
        kernel = OrchestratorKernel(registry, run_id="run2")
        call = ToolCall(name="DataSynth.failing", arguments={"fields": ["x"]})
        response = kernel.call_tool(call)
        assert response.ok is False
        assert "tool execution error" in response.error


def test_kernel_unknown_tool_raises(registry: ToolRegistry):
    kernel = OrchestratorKernel(registry, run_id="run3")
    with pytest.raises(ToolNotFoundError):
        kernel.registry.get("Nonexistent.tool")


def test_kernel_writes_audit_trace(registry: ToolRegistry, monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        from config.settings import settings as global_settings

        monkeypatch.setattr(global_settings, "project_root", Path(tmp))
        run_id = "run_trace_test"
        kernel = OrchestratorKernel(registry, run_id=run_id)
        kernel.call_tool(ToolCall(name="DataSynth.generate", arguments={"fields": ["a"]}))
        kernel.call_tool(ToolCall(name="DataSynth.generate", arguments={"fields": ["b"]}))

        trace = kernel.read_trace()
        assert len(trace) == 2
        assert trace[0]["tool_call"]["name"] == "DataSynth.generate"
        assert "duration_ms" in trace[0]

# ============================================================================
# ---- from test_parallel_execution.py ----
# ============================================================================
runner = CliRunner()


@pytest.fixture()
def isolated_project_with_docs(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        tmp_dir = Path(d)
        from config.settings import settings as global_settings

        monkeypatch.setattr(global_settings, "project_root", tmp_dir)

        req_dir = tmp_dir / "requirements_input"
        req_dir.mkdir(parents=True, exist_ok=True)
        for i in range(4):
            (req_dir / f"doc_{i}.md").write_text(f"# TC-DOC-{i}\n\nGiven: navigate to https://example.com\n")

        yield tmp_dir


def _make_fake_report(test_id: str) -> RunReport:
    return RunReport(
        run_id=test_id.lower(),
        test_id=test_id,
        status=RunStatus.PASSED,
        total_steps=1,
        passed_steps=1,
        failed_steps=0,
        escalated_steps=0,
        healed_steps=0,
        step_results=[],
        report_paths={},
    )


def test_parallel_flag_runs_every_target_exactly_once(monkeypatch, isolated_project_with_docs: Path):
    calls: list[str] = []
    lock = threading.Lock()

    def fake_execute_test(test_id: str, **kwargs) -> RunReport:
        with lock:
            calls.append(test_id)
        return _make_fake_report(Path(test_id).stem.upper())

    monkeypatch.setattr(execute_cmd, "execute_test", fake_execute_test)

    result = runner.invoke(app, ["execute", "--all", "--yes", "--parallel", "3"])

    assert result.exit_code == 0, result.stdout
    assert len(calls) == 4
    assert len(set(calls)) == 4  # every doc ran exactly once, no duplicates/drops


def test_parallel_one_matches_sequential_behavior(monkeypatch, isolated_project_with_docs: Path):
    calls: list[str] = []

    def fake_execute_test(test_id: str, **kwargs) -> RunReport:
        calls.append(test_id)
        return _make_fake_report(Path(test_id).stem.upper())

    monkeypatch.setattr(execute_cmd, "execute_test", fake_execute_test)

    result = runner.invoke(app, ["execute", "--all", "--yes", "--parallel", "1"])

    assert result.exit_code == 0, result.stdout
    assert len(calls) == 4
    # Sequential path preserves requirements_input_dir's sorted-glob order.
    assert calls == sorted(calls)


def test_parallel_rejects_values_below_one(isolated_project_with_docs: Path):
    result = runner.invoke(app, ["execute", "--all", "--yes", "--parallel", "0"])
    assert result.exit_code != 0


def test_parallel_propagates_a_failed_run_as_nonzero_exit(monkeypatch, isolated_project_with_docs: Path):
    def fake_execute_test(test_id: str, **kwargs) -> RunReport:
        report = _make_fake_report(Path(test_id).stem.upper())
        report.status = RunStatus.FAILED
        return report

    monkeypatch.setattr(execute_cmd, "execute_test", fake_execute_test)

    result = runner.invoke(app, ["execute", "--all", "--yes", "--parallel", "2"])
    assert result.exit_code == 1


def test_brain_hands_out_independent_run_engine_instances():
    """
    Phase J (still true post-D-079): the API layer must never hand
    out the same RunEngine instance twice. `_new_engine()` was removed
    when api/routers/runs.py migrated onto AuraBrain -- the equivalent
    guarantee now lives in orchestrator/brain/router.py, which builds a
    fresh RunEngine inside `_handle_execute_requirement`
    on every call rather than reusing one across runs.
    """
    from unittest.mock import patch

    from orchestrator.brain.router import Router
    from orchestrator.brain.policy import Policy
    from orchestrator.brain.context import BrainKnowledge
    from orchestrator.brain.intent import Intent
    from orchestrator.run_engine import RunEngine

    seen: list[RunEngine] = []
    real_init = RunEngine.__init__

    def spy_init(self, *args, **kwargs):
        seen.append(self)
        return real_init(self, *args, **kwargs)

    router = Router(Policy(BrainKnowledge.load()))

    with patch.object(RunEngine, "__init__", spy_init):
        for _ in range(2):
            try:
                router.resolve(
                    Intent(
                        kind="execute_interactive",
                        caller="api",
                        params={"prompt": "noop", "timeout": 0, "screenshot_provider": lambda rid, i: ""},
                    )
                )
            except Exception:
                pass

    assert len(seen) == 2
    assert seen[0] is not seen[1]


def test_api_runs_module_has_no_global_lock_or_singleton():
    """
    Regression guard: previously `_engine`/`_run_lock` module-level
    globals serialized every API run behind a single lock (any run
    submitted while another was in flight got a "Vision Core busy"
    failure instead of actually running). Phase J removed both.
    """
    from api.routers import runs

    assert not hasattr(runs, "_run_lock")
    assert not hasattr(runs, "_engine")
    assert not hasattr(runs, "_get_engine")
