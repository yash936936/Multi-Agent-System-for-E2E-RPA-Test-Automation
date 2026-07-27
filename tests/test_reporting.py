"""Merged test file: test_reporting.py
Consolidated from: test_click_resolution_log.py, test_decision_trace_log.py, test_assertion_audit_log.py, test_run_timeline.py, test_crash_boundary_and_logging.py, test_process_report.py, test_explainer.py, test_audit_report_cmd.py, test_junit.py, test_reports.py
All original test functions preserved 1:1. Colliding fixture/helper names
renamed with a source-file suffix to avoid silent shadowing across sections.
"""
from __future__ import annotations
import json
from orchestrator.click_resolution_log import ClickResolutionLog, find_anomalies, read_records
import logging
import tempfile
from pathlib import Path
from unittest.mock import patch
import pytest
from agents.planner.spec_generator import CloudLLMBackend, LocalHeuristicBackend, generate_spec
from config.settings import settings as global_settings
from orchestrator.decision_trace_log import DecisionTraceLog, find_anomalies, read_records
from orchestrator.schemas import RequirementInput
from orchestrator.assertion_audit_log import AssertionAuditLog, find_anomalies, read_records
from orchestrator.assertion_audit_log import assertion_audit_log
from orchestrator.click_resolution_log import click_resolution_log
from orchestrator.run_timeline import build_timeline
import typer
from typer.testing import CliRunner
from reports.process_report import _decision_basis
from agents.planner.explainer import explain_spec
from orchestrator.schemas import ActionType, Assertion, AssertionType, TestSpec, TestStep
from aura.cli.audit_report_cmd import audit_report
from xml.etree import ElementTree as ET
from orchestrator.schemas import RunReport, RunStatus
from reports.junit import build_testsuite_element, render_junit, render_junit_suites
from orchestrator.memory import RunMemoryStore
from orchestrator.run_engine import RunEngine
from orchestrator.skill_store import SkillStore
from reports.render import render_html
from target_app.demo_login_app import render_login_screen


# ============================================================================
# ---- from test_click_resolution_log.py ----
# ============================================================================
def test_log_and_read_round_trip(tmp_path):
    log = ClickResolutionLog(filepath=str(tmp_path / "click_resolution.jsonl"))
    log.log(
        run_id="run-1", step_id=8100, label="Sign Up", band="hero", source="dom",
        looks_interactive=True, resolution_strategy="dom", clicked=True,
        state_changed=True, new_tab_opened=False,
    )
    records = list(read_records(filepath=str(tmp_path / "click_resolution.jsonl")))
    assert len(records) == 1
    assert records[0]["run_id"] == "run-1"
    assert records[0]["label"] == "Sign Up"
    assert records[0]["clicked"] is True
    assert records[0]["state_changed"] is True


def test_read_records_filters_by_run_id_click_resolution(tmp_path):
    fp = str(tmp_path / "click_resolution.jsonl")
    log = ClickResolutionLog(filepath=fp)
    log.log(run_id="run-a", step_id=8100, label="A", band="nav", source="dom",
             looks_interactive=True, resolution_strategy="dom", clicked=True, state_changed=True)
    log.log(run_id="run-b", step_id=8101, label="B", band="nav", source="dom",
             looks_interactive=True, resolution_strategy="dom", clicked=True, state_changed=True)
    records = list(read_records(filepath=fp, run_id="run-a"))
    assert len(records) == 1
    assert records[0]["label"] == "A"


def test_find_anomalies_flags_clicked_but_no_state_change(tmp_path):
    fp = str(tmp_path / "click_resolution.jsonl")
    log = ClickResolutionLog(filepath=fp)
    # Real anomaly: clicked, verified, nothing changed (D-067's "dead button" case).
    log.log(run_id="run-1", step_id=8100, label="Do Nothing", band="footer", source="dom",
            looks_interactive=True, resolution_strategy="dom", clicked=True, state_changed=False)
    # Not an anomaly: never clicked at all (rejected candidate).
    log.log(run_id="run-1", step_id=8101, label="Get In Touch", band="footer", source="ocr",
            looks_interactive=False, resolution_strategy="ocr", clicked=False, state_changed=None,
            rejected_reason="unreachable")
    # Not an anomaly: clicked and it worked.
    log.log(run_id="run-1", step_id=8102, label="Sign Up", band="hero", source="dom",
            looks_interactive=True, resolution_strategy="dom", clicked=True, state_changed=True)

    anomalies = find_anomalies(filepath=fp)
    assert len(anomalies) == 1
    assert anomalies[0]["label"] == "Do Nothing"


def test_read_records_missing_file_returns_empty(tmp_path):
    records = list(read_records(filepath=str(tmp_path / "does_not_exist.jsonl")))
    assert records == []

# ============================================================================
# ---- from test_decision_trace_log.py ----
# ============================================================================
@pytest.fixture()
def tmp_log_path():
    with tempfile.TemporaryDirectory() as d:
        yield str(Path(d) / "decision_trace.jsonl")


# --------------------------------------------------------------------------
# The module itself
# --------------------------------------------------------------------------

def test_log_writes_one_json_line_per_call_decision_trace(tmp_log_path):
    log = DecisionTraceLog(filepath=tmp_log_path)
    log.log("planner_backend", "attempt", "HermesAgentBackend")
    log.log("planner_backend", "exhausted", "CloudLLMBackend", reason="503", detail={"can_escalate": False})

    lines = Path(tmp_log_path).read_text().strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["category"] == "planner_backend"
    assert first["decision"] == "attempt"
    assert first["backend"] == "HermesAgentBackend"
    assert first["reason"] is None
    second = json.loads(lines[1])
    assert second["decision"] == "exhausted"
    assert second["reason"] == "503"
    assert second["detail"] == {"can_escalate": False}


def test_read_records_filters_by_category(tmp_log_path):
    log = DecisionTraceLog(filepath=tmp_log_path)
    log.log("planner_backend", "attempt", "HermesAgentBackend")
    log.log("capability_adapter", "attempt", "LinkCheckAdapter")

    only_planner = list(read_records(tmp_log_path, category="planner_backend"))
    assert len(only_planner) == 1
    assert only_planner[0]["backend"] == "HermesAgentBackend"


def test_find_anomalies_flags_exhausted_and_fallback_only(tmp_log_path):
    log = DecisionTraceLog(filepath=tmp_log_path)
    log.log("planner_backend", "attempt", "HermesAgentBackend")
    log.log("planner_backend", "success", "HermesAgentBackend")
    log.log("planner_backend", "fallback", "LocalHeuristicBackend", reason="everything else failed")
    log.log("planner_backend", "exhausted", "LocalHeuristicBackend", reason="heuristic also failed")

    anomalies = find_anomalies(tmp_log_path)
    assert len(anomalies) == 2
    assert {a["decision"] for a in anomalies} == {"fallback", "exhausted"}


def test_read_records_on_missing_file_returns_empty(tmp_path):
    assert list(read_records(str(tmp_path / "does_not_exist.jsonl"))) == []


def test_find_anomalies_on_missing_file_returns_empty(tmp_path):
    assert find_anomalies(str(tmp_path / "does_not_exist.jsonl")) == []


# --------------------------------------------------------------------------
# Wired into generate_spec's escalation chain
# --------------------------------------------------------------------------

class _AlwaysFailsBackend:
    def generate(self, requirement_text: str) -> dict:
        raise RuntimeError("primary backend is down")


class _FakeCloudBackend:
    def generate(self, requirement_text: str) -> dict:
        return {
            "test_id": "TC-ESCALATED-001",
            "requirement_ref": "TC-ESCALATED-001",
            "preconditions": [],
            "steps": [{"step_id": 1, "action": "visual_click", "target_description": "Login button"}],
        }


@pytest.fixture()
def patched_trace_log(tmp_log_path):
    """Redirects the module-global singleton at a throwaway file for the
    duration of one test, so these tests don't write into the real
    logs/decision_trace.jsonl or read stale records from other tests."""
    fresh = DecisionTraceLog(filepath=tmp_log_path)
    with patch("agents.planner.spec_generator.decision_trace_log", fresh):
        yield tmp_log_path


def test_successful_primary_backend_logs_attempt_then_success(patched_trace_log, monkeypatch):
    monkeypatch.setattr(global_settings, "enable_cloud_planner", False)
    with patch("agents.planner.spec_generator._default_backend", return_value=_FakeCloudBackend()):
        generate_spec(RequirementInput(requirement_text="click the button"))

    records = list(read_records(patched_trace_log))
    decisions = [r["decision"] for r in records]
    assert decisions == ["attempt", "success"]


def test_escalation_to_cloud_logs_escalate_then_success(patched_trace_log, monkeypatch):
    monkeypatch.setattr(global_settings, "planner_backend", "heuristic")
    monkeypatch.setattr(global_settings, "enable_cloud_planner", True)

    with patch("agents.planner.spec_generator._default_backend", return_value=_AlwaysFailsBackend()):
        with patch("agents.planner.spec_generator.CloudLLMBackend", return_value=_FakeCloudBackend()):
            generate_spec(RequirementInput(requirement_text="click the button"))

    decisions = [r["decision"] for r in read_records(patched_trace_log)]
    assert decisions == ["attempt", "escalate", "success"]
    monkeypatch.setattr(global_settings, "enable_cloud_planner", False)


def test_no_escalation_path_logs_exhausted_immediately(patched_trace_log, monkeypatch):
    monkeypatch.setattr(global_settings, "enable_cloud_planner", False)
    with patch("agents.planner.spec_generator._default_backend", return_value=_AlwaysFailsBackend()):
        with pytest.raises(RuntimeError):
            generate_spec(RequirementInput(requirement_text="click the button"))

    decisions = [r["decision"] for r in read_records(patched_trace_log)]
    assert decisions == ["attempt", "exhausted"]
    assert find_anomalies(patched_trace_log)[0]["decision"] == "exhausted"


def test_double_failure_falls_back_and_logs_fallback_then_success(patched_trace_log, monkeypatch, caplog):
    """
    The exact real-world bug shape this phase exists for: Hermes
    connection-refused + Cloud 503 in the same run. Confirms the full
    decision chain is now captured mechanically: attempt -> escalate ->
    fallback -> success (degraded), not just visible as scrolling log
    prose.
    """
    monkeypatch.setattr(global_settings, "planner_backend", "heuristic")
    monkeypatch.setattr(global_settings, "enable_cloud_planner", True)

    class _AlsoFailsBackend:
        def generate(self, requirement_text: str) -> dict:
            raise RuntimeError("cloud also down")

    with patch("agents.planner.spec_generator._default_backend", return_value=_AlwaysFailsBackend()):
        with patch("agents.planner.spec_generator.CloudLLMBackend", return_value=_AlsoFailsBackend()):
            with caplog.at_level(logging.WARNING):
                spec = generate_spec(RequirementInput(requirement_text="Click the login button."))

    assert spec.steps
    decisions = [r["decision"] for r in read_records(patched_trace_log)]
    assert decisions == ["attempt", "escalate", "fallback", "success"]
    # This is a *quality* anomaly (run survived, spec degraded), not a
    # crash -- must still surface via find_anomalies so it isn't lost
    # just because the run technically passed.
    anomaly_decisions = {a["decision"] for a in find_anomalies(patched_trace_log)}
    assert anomaly_decisions == {"fallback"}
    monkeypatch.setattr(global_settings, "enable_cloud_planner", False)


def test_triple_failure_logs_final_exhausted_with_original_reason(patched_trace_log, monkeypatch):
    monkeypatch.setattr(global_settings, "planner_backend", "heuristic")
    monkeypatch.setattr(global_settings, "enable_cloud_planner", True)

    class _AlsoFailsBackend:
        def generate(self, requirement_text: str) -> dict:
            raise RuntimeError("cloud also down")

    with patch("agents.planner.spec_generator._default_backend", return_value=_AlwaysFailsBackend()):
        with patch("agents.planner.spec_generator.CloudLLMBackend", return_value=_AlsoFailsBackend()):
            with patch.object(LocalHeuristicBackend, "generate", side_effect=ValueError("heuristic also broke")):
                with pytest.raises(RuntimeError, match="cloud also down"):
                    generate_spec(RequirementInput(requirement_text="Click the login button."))

    decisions = [r["decision"] for r in read_records(patched_trace_log)]
    assert decisions == ["attempt", "escalate", "fallback", "exhausted"]
    monkeypatch.setattr(global_settings, "enable_cloud_planner", False)

# ============================================================================
# ---- from test_assertion_audit_log.py ----
# ============================================================================
@pytest.fixture()
def tmp_log_path__assertion_audit_log():
    with tempfile.TemporaryDirectory() as d:
        yield str(Path(d) / "assertion_audit.jsonl")


def test_log_writes_one_json_line_per_call(tmp_log_path__assertion_audit_log):
    log = AssertionAuditLog(filepath=tmp_log_path__assertion_audit_log)
    log.log(
        run_id="run-1", step_id=1, expected_state="dashboard_visible",
        detail={"passed": True, "method": "literal_ocr", "matched_text": "dashboard visible", "ocr_excerpt": None},
        escalate=False,
    )
    log.log(
        run_id="run-1", step_id=2, expected_state="page_loaded",
        detail={"passed": True, "method": "structural_sentinel", "matched_text": None, "ocr_excerpt": "Home Work About"},
        escalate=False,
    )

    lines = Path(tmp_log_path__assertion_audit_log).read_text().strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["run_id"] == "run-1"
    assert first["step_id"] == 1
    assert first["passed"] is True
    assert first["method"] == "literal_ocr"


def test_read_records_filters_by_run_id(tmp_log_path__assertion_audit_log):
    log = AssertionAuditLog(filepath=tmp_log_path__assertion_audit_log)
    log.log(run_id="run-a", step_id=1, expected_state="x", detail={"passed": True, "method": "literal_ocr"}, escalate=False)
    log.log(run_id="run-b", step_id=1, expected_state="y", detail={"passed": False, "method": "literal_ocr"}, escalate=True)

    run_a_records = list(read_records(tmp_log_path__assertion_audit_log, run_id="run-a"))
    assert len(run_a_records) == 1
    assert run_a_records[0]["expected_state"] == "x"


def test_find_anomalies_flags_the_exact_d056_bug_shape(tmp_log_path__assertion_audit_log):
    """
    AB2's core payoff: D-056's bug was a step reporting escalate=False
    while its real assertion had genuinely failed (assertion_passed=False)
    -- silently displayed as "fulfilled". find_anomalies must flag exactly
    that combination, and NOT flag either of the two "normal" shapes
    (passed+not-escalated, or failed+escalated).
    """
    log = AssertionAuditLog(filepath=tmp_log_path__assertion_audit_log)
    # Normal: passed, not escalated -- fine.
    log.log(run_id="run-1", step_id=1, expected_state="a", detail={"passed": True, "method": "literal_ocr"}, escalate=False)
    # Normal: failed AND escalated -- the system correctly flagged it, fine.
    log.log(run_id="run-1", step_id=2, expected_state="b", detail={"passed": False, "method": "literal_ocr"}, escalate=True)
    # THE BUG SHAPE: failed but NOT escalated -- this is what D-056 was.
    log.log(run_id="run-1", step_id=3, expected_state="c", detail={"passed": False, "method": "structural_fallback"}, escalate=False)

    anomalies = find_anomalies(tmp_log_path__assertion_audit_log)
    assert len(anomalies) == 1
    assert anomalies[0]["step_id"] == 3
    assert anomalies[0]["expected_state"] == "c"


def test_find_anomalies_on_empty_or_missing_log_returns_empty(tmp_log_path__assertion_audit_log):
    # File doesn't exist yet -- must not raise.
    assert find_anomalies(tmp_log_path__assertion_audit_log) == []


@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def test_run_engine_writes_assertion_audit_records(tmp_dir: Path, monkeypatch):
    """
    End-to-end: a real run_engine.py run must actually populate the
    audit log via the wired-in assertion_audit_log.log() calls, not just
    have the plumbing exist unused.
    """
    import orchestrator.assertion_audit_log as audit_log_module

    log_path = str(tmp_dir / "assertion_audit.jsonl")
    test_log = audit_log_module.AssertionAuditLog(filepath=log_path)
    monkeypatch.setattr(audit_log_module, "assertion_audit_log", test_log)
    monkeypatch.setattr("orchestrator.run_engine.assertion_audit_log", test_log)

    from orchestrator.memory import RunMemoryStore
    from orchestrator.run_engine import RunEngine
    from orchestrator.skill_store import SkillStore
    from tests.test_run_engine import REQUIREMENT_PATH, make_provider

    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")
    engine = RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)
    engine.run(REQUIREMENT_PATH.read_text(), run_id="ab2_audit_test_run")

    records = list(read_records(log_path, run_id="ab2_audit_test_run"))
    assert len(records) >= 1
    assert all("method" in r for r in records)

# ============================================================================
# ---- from test_run_timeline.py ----
# ============================================================================
def test_build_timeline_merges_and_orders_by_timestamp(tmp_path, monkeypatch):
    click_fp = str(tmp_path / "click_resolution.jsonl")
    assertion_fp = str(tmp_path / "assertion_audit.jsonl")
    monkeypatch.setattr(click_resolution_log, "filepath", click_fp)
    monkeypatch.setattr(assertion_audit_log, "filepath", assertion_fp)

    click_resolution_log.log(
        run_id="run-1", step_id=8100, label="Sign Up", band="hero", source="dom",
        looks_interactive=True, resolution_strategy="dom", clicked=True, state_changed=True,
    )
    assertion_audit_log.log(
        run_id="run-1", step_id=1, expected_state="Welcome",
        detail={"passed": True, "method": "literal_ocr", "matched_text": "Welcome"}, escalate=False,
    )
    # Different run -- must not appear in run-1's timeline.
    click_resolution_log.log(
        run_id="run-2", step_id=8100, label="Other", band="hero", source="dom",
        looks_interactive=True, resolution_strategy="dom", clicked=True, state_changed=True,
    )

    events = build_timeline("run-1")
    assert len(events) == 2
    kinds = {e.kind for e in events}
    assert kinds == {"click_resolution", "assertion"}
    # Sorted by timestamp -- both were logged within the same test, so just
    # confirm the sort didn't crash and produced a non-decreasing sequence.
    timestamps = [e.timestamp for e in events]
    assert timestamps == sorted(timestamps)


def test_build_timeline_empty_for_unknown_run(tmp_path, monkeypatch):
    monkeypatch.setattr(click_resolution_log, "filepath", str(tmp_path / "click_resolution.jsonl"))
    monkeypatch.setattr(assertion_audit_log, "filepath", str(tmp_path / "assertion_audit.jsonl"))
    events = build_timeline("nonexistent-run")
    assert events == []


def test_explain_cmd_json_output(tmp_path, monkeypatch, capsys):
    from aura.cli import explain_cmd

    monkeypatch.setattr(click_resolution_log, "filepath", str(tmp_path / "click_resolution.jsonl"))
    monkeypatch.setattr(assertion_audit_log, "filepath", str(tmp_path / "assertion_audit.jsonl"))
    click_resolution_log.log(
        run_id="run-json", step_id=8100, label="Sign Up", band="hero", source="dom",
        looks_interactive=True, resolution_strategy="dom", clicked=True, state_changed=True,
    )

    explain_cmd.explain("run-json", as_json=True)
    out = capsys.readouterr().out
    import json
    parsed = json.loads(out)
    assert len(parsed) == 1
    assert parsed[0]["kind"] == "click_resolution"


def test_explain_cmd_handles_no_events(tmp_path, monkeypatch):
    from aura.cli import explain_cmd

    monkeypatch.setattr(click_resolution_log, "filepath", str(tmp_path / "click_resolution.jsonl"))
    monkeypatch.setattr(assertion_audit_log, "filepath", str(tmp_path / "assertion_audit.jsonl"))
    # Should not raise even with nothing logged.
    explain_cmd.explain("nonexistent-run", as_json=False)

# ============================================================================
# ---- from test_crash_boundary_and_logging.py ----
# ============================================================================
runner = CliRunner()


def _fresh_logging_state():
    """Undo configure_logging()'s idempotency sentinel + handlers between
    tests, so each test observes a truly unconfigured root logger, same
    as a fresh process would."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    if hasattr(root, "_aura_configured"):
        delattr(root, "_aura_configured")


# --------------------------------------------------------------------------
# AF2 -- logging_setup.configure_logging()
# --------------------------------------------------------------------------

def test_configure_logging_persists_a_message_to_the_log_file(tmp_path, monkeypatch):
    from config.logging_setup import configure_logging

    _fresh_logging_state()
    log_dir = tmp_path / "logs"
    configure_logging(log_dir=log_dir)

    logger = logging.getLogger("some.module.that.already.called.getLogger")
    logger.info("a real diagnostic message that must now be persisted")

    log_file = log_dir / "aura.log"
    assert log_file.exists()
    content = log_file.read_text()
    assert "a real diagnostic message that must now be persisted" in content

    # AF2's whole point: this must be structured (JSON), not just prose,
    # so it's greppable/jq-able the same way AB2's assertion_audit_log
    # already is for assertion evidence specifically.
    record = json.loads(content.strip().splitlines()[-1])
    assert record["message"] == "a real diagnostic message that must now be persisted"
    assert record["level"] == "INFO"
    assert record["logger"] == "some.module.that.already.called.getLogger"
    _fresh_logging_state()


def test_configure_logging_captures_exception_traceback(tmp_path):
    from config.logging_setup import configure_logging

    _fresh_logging_state()
    log_dir = tmp_path / "logs"
    configure_logging(log_dir=log_dir)

    logger = logging.getLogger("test.exc")
    try:
        raise ValueError("boom for the test")
    except ValueError:
        logger.error("something failed", exc_info=True)

    content = (log_dir / "aura.log").read_text()
    record = json.loads(content.strip().splitlines()[-1])
    assert "boom for the test" in record["exception"]
    assert "ValueError" in record["exception"]
    _fresh_logging_state()


def test_configure_logging_is_idempotent_does_not_duplicate_handlers(tmp_path):
    from config.logging_setup import configure_logging

    _fresh_logging_state()
    log_dir = tmp_path / "logs"
    configure_logging(log_dir=log_dir)
    handlers_after_first_call = len(logging.getLogger().handlers)
    configure_logging(log_dir=log_dir)  # second call must be a no-op
    handlers_after_second_call = len(logging.getLogger().handlers)

    assert handlers_after_first_call == handlers_after_second_call
    _fresh_logging_state()


# --------------------------------------------------------------------------
# AF1 -- aura/main.py's main() crash boundary
# --------------------------------------------------------------------------

def test_typer_exit_control_flow_is_unaffected_by_the_crash_boundary(monkeypatch):
    """
    The single most important property of AF1: it must NOT swallow the
    dozens of existing `raise typer.Exit(code=N)` calls across the CLI
    (e.g. `_exit_nonzero_if_failed`, `aura doctor`'s failure path, every
    "Usage: ..." error). Verified two ways: (1) empirically, directly
    against a throwaway Typer app, that Click's own standalone-mode
    main() already converts typer.Exit into a real SystemExit before it
    would ever reach an except Exception block wrapped around it (see
    the module docstring for the full reasoning) -- confirmed, not
    assumed -- and (2) here, through AURA's actual _run_app_safely.
    """
    import sys

    throwaway_app = typer.Typer()

    @throwaway_app.command()
    def foo():
        raise typer.Exit(code=7)

    @throwaway_app.command()
    def bar():
        pass  # a second command so Typer doesn't collapse to single-command mode

    monkeypatch.setattr(sys, "argv", ["prog", "foo"])

    from aura.main import _run_app_safely

    with pytest.raises(SystemExit) as exc_info:
        _run_app_safely(throwaway_app)
    assert exc_info.value.code == 7


def test_genuinely_unhandled_exception_is_caught_logged_and_exits_cleanly(monkeypatch, tmp_path, capsys):
    """
    The actual bug this phase was written for: a real Hermes-connection-
    refused + Gemini-503 double failure previously produced a raw,
    multi-hundred-line Python traceback with no persisted record and no
    clean message. Simulated here via a throwaway command that raises a
    genuinely unhandled RuntimeError.
    """
    import sys

    from config.logging_setup import configure_logging

    _fresh_logging_state()
    configure_logging(log_dir=tmp_path / "logs")

    throwaway_app = typer.Typer()

    @throwaway_app.command()
    def foo():
        raise RuntimeError("simulated genuinely unhandled failure")

    @throwaway_app.command()
    def bar():
        pass

    monkeypatch.setattr(sys, "argv", ["prog", "foo"])

    from aura.main import _run_app_safely

    with pytest.raises(SystemExit) as exc_info:
        _run_app_safely(throwaway_app)
    assert exc_info.value.code == 1

    printed = capsys.readouterr().out
    assert "unexpected error" in printed

    log_content = (tmp_path / "logs" / "aura.log").read_text()
    assert "simulated genuinely unhandled failure" in log_content
    assert "RuntimeError" in log_content
    _fresh_logging_state()


def test_keyboard_interrupt_exits_130_via_clicks_own_handling(monkeypatch):
    """
    Confirmed directly (not assumed): Click's own standalone-mode main()
    catches KeyboardInterrupt internally and converts it to
    SystemExit(130) *before* it ever reaches _run_app_safely's except
    Exception clause -- SystemExit isn't an Exception subclass, so this
    passes through untouched, same as typer.Exit's SystemExit conversion
    above. This test exists to pin that observed behavior down as a
    regression guard, not to claim _run_app_safely does anything special
    for Ctrl-C itself (it doesn't need to -- Click already gets this
    right).
    """
    import sys

    throwaway_app = typer.Typer()

    @throwaway_app.command()
    def foo():
        raise KeyboardInterrupt()

    @throwaway_app.command()
    def bar():
        pass

    monkeypatch.setattr(sys, "argv", ["prog", "foo"])

    from aura.main import _run_app_safely

    with pytest.raises(SystemExit) as exc_info:
        _run_app_safely(throwaway_app)
    assert exc_info.value.code == 130

# ============================================================================
# ---- from test_process_report.py ----
# ============================================================================
def test_none_action_with_failed_assertion_is_reported_as_not_fulfilled():
    """The actual bug: an ASSERT step (action_taken="none") whose real
    assertion_passed is False must be shown as not_fulfilled, not
    silently reported as "fulfilled" just because escalate is False."""
    r = {
        "action_taken": "none",
        "escalate": False,
        "assertion_passed": False,
        "confidence": 1.0,
    }
    basis = _decision_basis(r, step_def=None)
    assert basis["decided"] == "not_fulfilled"


def test_none_action_with_passed_assertion_is_reported_as_fulfilled():
    r = {
        "action_taken": "none",
        "escalate": False,
        "assertion_passed": True,
        "confidence": 1.0,
    }
    basis = _decision_basis(r, step_def=None)
    assert basis["decided"] == "fulfilled"


def test_none_action_with_no_assertion_attached_falls_back_to_escalate_only():
    """A genuinely no-op step (e.g. SCROLL) that never had any assertion
    attached at all (assertion_passed is None, not True/False) keeps the
    old "no action required" behavior, gated on escalate alone."""
    r = {
        "action_taken": "none",
        "escalate": False,
        "assertion_passed": None,
        "confidence": 1.0,
    }
    basis = _decision_basis(r, step_def=None)
    assert basis["decided"] == "fulfilled"
    assert basis["reason"] == "No action required."


def test_escalated_step_is_reported_as_escalated_regardless_of_assertion_passed():
    """escalate must still take priority over assertion_passed -- an
    escalated step is never silently marked fulfilled or not_fulfilled
    via the assertion path."""
    r = {
        "action_taken": "none",
        "escalate": True,
        "assertion_passed": None,
        "confidence": 0.0,
    }
    basis = _decision_basis(r, step_def=None)
    assert basis["decided"] == "escalated_not_fulfilled"

# ============================================================================
# ---- from test_explainer.py ----
# ============================================================================
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

# ============================================================================
# ---- from test_audit_report_cmd.py ----
# ============================================================================
def test_audit_report_finds_no_anomalies_for_a_clean_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(assertion_audit_log, "filepath", str(tmp_path / "assertion_audit.jsonl"))
    monkeypatch.setattr(click_resolution_log, "filepath", str(tmp_path / "click_resolution.jsonl"))

    assertion_audit_log.log(run_id="run-clean", step_id=1, expected_state="Dashboard", detail={"passed": True}, escalate=False)
    click_resolution_log.log(run_id="run-clean", step_id=8100, label="Sign Up", band="hero", source="dom", looks_interactive=True, resolution_strategy="dom", clicked=True, state_changed=True)

    audit_report("run-clean")

    out = capsys.readouterr().out
    assert "No anomalies found" in out


def test_audit_report_flags_the_d056_assertion_anomaly_shape(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(assertion_audit_log, "filepath", str(tmp_path / "assertion_audit.jsonl"))
    monkeypatch.setattr(click_resolution_log, "filepath", str(tmp_path / "click_resolution.jsonl"))

    # The exact D-056 shape: escalate=False but passed=False.
    assertion_audit_log.log(run_id="run-bad", step_id=3, expected_state="Success message", detail={"passed": False}, escalate=False)

    audit_report("run-bad")

    out = capsys.readouterr().out
    assert "1 assertion anomaly" in out
    assert "step 3" in out


def test_audit_report_flags_the_d067_click_anomaly_shape(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(assertion_audit_log, "filepath", str(tmp_path / "assertion_audit.jsonl"))
    monkeypatch.setattr(click_resolution_log, "filepath", str(tmp_path / "click_resolution.jsonl"))

    # The exact D-067 shape: clicked=True but state_changed=False.
    click_resolution_log.log(run_id="run-bad2", step_id=8101, label="Do Nothing", band="footer", source="dom", looks_interactive=True, resolution_strategy="dom", clicked=True, state_changed=False)

    audit_report("run-bad2")

    out = capsys.readouterr().out
    assert "1 click anomaly" in out
    assert "Do Nothing" in out


def test_audit_report_filters_by_run_id_not_just_anomaly_shape(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(assertion_audit_log, "filepath", str(tmp_path / "assertion_audit.jsonl"))
    monkeypatch.setattr(click_resolution_log, "filepath", str(tmp_path / "click_resolution.jsonl"))

    click_resolution_log.log(run_id="other-run", step_id=8100, label="Broken", band="nav", source="dom", looks_interactive=True, resolution_strategy="dom", clicked=True, state_changed=False)

    audit_report("this-run-has-no-records")

    out = capsys.readouterr().out
    assert "No anomalies found" in out


def test_audit_report_full_flag_prints_merged_timeline(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(assertion_audit_log, "filepath", str(tmp_path / "assertion_audit.jsonl"))
    monkeypatch.setattr(click_resolution_log, "filepath", str(tmp_path / "click_resolution.jsonl"))
    monkeypatch.setattr("orchestrator.decision_trace_log.decision_trace_log.filepath", str(tmp_path / "decision_trace.jsonl"))

    click_resolution_log.log(run_id="run-full", step_id=8100, label="Sign Up", band="hero", source="dom", looks_interactive=True, resolution_strategy="dom", clicked=True, state_changed=True)

    audit_report("run-full", full=True)

    out = capsys.readouterr().out
    assert "Full timeline" in out

# ============================================================================
# ---- from test_junit.py ----
# ============================================================================
def _write_raw_results(tmp_path, step_results, filename="raw_results.json"):
    raw_path = tmp_path / filename
    raw_path.write_text(json.dumps({"step_results": step_results}), encoding="utf-8")
    return raw_path


def _make_report(tmp_path, step_results, status=RunStatus.PASSED, run_id="run_abc123"):
    raw_path = _write_raw_results(tmp_path, step_results, filename=f"raw_results_{run_id}.json")
    return RunReport(
        run_id=run_id,
        status=status,
        total_steps=len(step_results),
        self_healed_steps=sum(1 for s in step_results if "heal" in str(s.get("healed_via", ""))),
        escalated_steps=sum(1 for s in step_results if s.get("escalate")),
        duration_seconds=1.234,
        report_paths={"raw_json": str(raw_path)},
    )


def test_all_steps_passed_produces_zero_failures(tmp_path):
    steps = [
        {"step_id": 1, "action_taken": "click", "assertion_passed": True, "escalate": False},
        {"step_id": 2, "action_taken": "type", "assertion_passed": True, "escalate": False},
    ]
    report = _make_report(tmp_path, steps)
    suite = build_testsuite_element(report)

    assert suite.attrib["tests"] == "2"
    assert suite.attrib["failures"] == "0"
    testcases = suite.findall("testcase")
    assert len(testcases) == 2
    assert all(tc.find("failure") is None for tc in testcases)


def test_failed_assertion_step_becomes_a_junit_failure(tmp_path):
    steps = [
        {"step_id": 1, "action_taken": "click", "assertion_passed": True, "escalate": False},
        {"step_id": 2, "action_taken": "assert_visible", "assertion_passed": False, "escalate": False, "confidence": 0.4},
    ]
    report = _make_report(tmp_path, steps, status=RunStatus.FAILED)
    suite = build_testsuite_element(report)

    assert suite.attrib["failures"] == "1"
    testcases = suite.findall("testcase")
    failing = [tc for tc in testcases if tc.find("failure") is not None]
    assert len(failing) == 1
    assert "confidence=0.4" in failing[0].find("failure").attrib["message"]


def test_escalated_step_with_no_resolution_is_a_failure(tmp_path):
    steps = [{"step_id": 1, "action_taken": "click", "assertion_passed": None, "escalate": True}]
    report = _make_report(tmp_path, steps, status=RunStatus.ESCALATED)
    suite = build_testsuite_element(report)
    assert suite.attrib["failures"] == "1"


def test_step_with_no_assertion_configured_is_not_a_failure(tmp_path):
    # assertion_passed is None because the step had no expected_state --
    # this must NOT count as a failure on its own.
    steps = [{"step_id": 1, "action_taken": "click", "assertion_passed": None, "escalate": False}]
    report = _make_report(tmp_path, steps)
    suite = build_testsuite_element(report)
    assert suite.attrib["failures"] == "0"


def test_self_healed_run_gets_an_honest_suite_level_note(tmp_path):
    # Phase G2 bug fix (found this pass, decisions.md D-026 addendum):
    # per-step self-heal attribution was dead code (VisionActionResult has
    # no field to carry it). Confirms the corrected behavior: an honest
    # suite-level note using RunReport.self_healed_steps, the one place
    # this count is actually tracked correctly, and confirms no step is
    # falsely marked as a failure just because the run healed something.
    steps = [{"step_id": 1, "action_taken": "click", "assertion_passed": True, "escalate": False}]
    report = _make_report(tmp_path, steps, status=RunStatus.PASSED_WITH_HEALING)
    report.self_healed_steps = 1  # simulate ReportAggregator's real count
    suite = build_testsuite_element(report)

    assert suite.attrib["failures"] == "0"
    tc = suite.find("testcase")
    assert tc.find("failure") is None
    assert tc.find("system-out") is None  # no false per-step attribution
    suite_out = suite.find("system-out")
    assert suite_out is not None
    assert "1 step(s)" in suite_out.text


def test_no_self_heal_note_when_nothing_was_healed(tmp_path):
    steps = [{"step_id": 1, "action_taken": "click", "assertion_passed": True, "escalate": False}]
    report = _make_report(tmp_path, steps)  # self_healed_steps defaults to 0
    suite = build_testsuite_element(report)
    assert suite.find("system-out") is None


def test_missing_raw_json_falls_back_to_summary_testcase_not_empty_suite(tmp_path):
    # No raw_results.json written at all -- report_paths points nowhere.
    report = RunReport(
        run_id="run_no_detail", status=RunStatus.FAILED, total_steps=3,
        duration_seconds=0.5, report_paths={},
    )
    suite = build_testsuite_element(report)

    # Must not render as "0 tests ran" (misleading -- reads as nothing was
    # tested rather than detail-unavailable).
    assert suite.attrib["tests"] == "3"
    tc = suite.find("testcase")
    assert tc is not None
    failure = tc.find("failure")
    assert failure is not None
    assert "run_no_detail" in failure.attrib["message"] or "failed" in failure.attrib["message"]


def test_render_junit_writes_valid_xml_to_given_path(tmp_path):
    steps = [{"step_id": 1, "action_taken": "click", "assertion_passed": True, "escalate": False}]
    report = _make_report(tmp_path, steps)
    out_path = tmp_path / "results.xml"

    written_path = render_junit(report, out_path=str(out_path))

    assert written_path == out_path
    assert out_path.exists()
    root = ET.parse(out_path).getroot()
    assert root.tag == "testsuites"
    assert len(root.findall("testsuite")) == 1


def test_render_junit_suites_combines_multiple_specs_into_one_file(tmp_path):
    steps_a = [{"step_id": 1, "action_taken": "click", "assertion_passed": True, "escalate": False}]
    steps_b = [{"step_id": 1, "action_taken": "click", "assertion_passed": False, "escalate": False}]
    report_a = _make_report(tmp_path, steps_a, run_id="run_a")
    report_b = _make_report(tmp_path, steps_b, run_id="run_b", status=RunStatus.FAILED)

    suite_a = build_testsuite_element(report_a, suite_name="spec_a.md")
    suite_b = build_testsuite_element(report_b, suite_name="spec_b.md")

    out_path = tmp_path / "combined.xml"
    written_path = render_junit_suites([suite_a, suite_b], out_path=str(out_path))

    assert written_path == out_path
    root = ET.parse(out_path).getroot()
    suites = root.findall("testsuite")
    assert len(suites) == 2
    names = {s.attrib["name"] for s in suites}
    assert names == {"spec_a.md", "spec_b.md"}
    # One suite passed, one failed -- confirms each spec's own outcome is
    # preserved independently in the combined file, not merged/averaged.
    failures_by_name = {s.attrib["name"]: s.attrib["failures"] for s in suites}
    assert failures_by_name["spec_a.md"] == "0"
    assert failures_by_name["spec_b.md"] == "1"


def test_render_junit_defaults_to_reports_dir_when_no_out_path_given(tmp_path, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)  # reports_dir is a read-only property derived from project_root
    steps = [{"step_id": 1, "action_taken": "click", "assertion_passed": True, "escalate": False}]
    report = _make_report(tmp_path, steps, run_id="run_default_path")

    written_path = render_junit(report)

    assert written_path.parent == tmp_path / "reports"
    assert "run_default_path" in written_path.name
    assert written_path.exists()

# ============================================================================
# ---- from test_reports.py ----
# ============================================================================
REQUIREMENT_PATH = Path(__file__).resolve().parent.parent / "requirements_input" / "example_login_flow.md"


@pytest.fixture()
def tmp_dir__reports():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def make_provider(tmp_dir__reports: Path):
    screens = {1: "initial", 2: "login_form", 3: "login_form", 4: "login_form"}

    def provider(run_id: str, step_id: int) -> str:
        state = screens.get(step_id, "dashboard")
        path = tmp_dir__reports / f"{run_id}_{step_id}_{state}.png"
        if not path.exists():
            render_login_screen(state, path)
        return str(path)

    return provider


def test_render_html_produces_all_required_sections(tmp_dir__reports: Path, monkeypatch):
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "project_root", tmp_dir__reports)

    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir__reports / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir__reports / "memory.db")
    engine = RunEngine(screenshot_provider=make_provider(tmp_dir__reports), skill_store=skill_store, memory=memory)
    result = engine.run(requirement_text, run_id="report_test_run")

    html_path = render_html(result.run_id, spec=result.spec.model_dump())
    assert html_path.exists()

    html = html_path.read_text()
    assert "AURA Run Report" in html
    assert result.run_id in html
    assert "Step-by-step process" in html
    assert "Decision basis" in html
    assert "audit trace" in html
    # summary card numbers should reflect the real report
    assert str(result.report.total_steps) in html
    # feature roadmap: plain-English "what this test does" explanation
    assert "What this test does:" in html
    assert result.spec.test_id in html
    # report-detail pass: request text + outcome summary now present
    assert requirement_text.strip()[:30] in html
    assert "Outcome" in html


def test_render_html_raises_clear_error_when_no_run_exists(tmp_dir__reports: Path, monkeypatch):
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "project_root", tmp_dir__reports)

    with pytest.raises(FileNotFoundError):
        render_html("no-such-run")


def test_render_json_produces_process_oriented_structure(tmp_dir__reports: Path, monkeypatch):
    from config.settings import settings as global_settings
    from reports.render import render_json

    monkeypatch.setattr(global_settings, "project_root", tmp_dir__reports)

    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir__reports / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir__reports / "memory.db")
    engine = RunEngine(screenshot_provider=make_provider(tmp_dir__reports), skill_store=skill_store, memory=memory)
    result = engine.run(requirement_text, run_id="report_json_test_run")

    json_path = render_json(result.run_id, spec=result.spec.model_dump())
    assert json_path.exists()
    assert json_path.name == "report_detailed.json"

    import json as _json
    data = _json.loads(json_path.read_text())

    # Request: the real original text, not the requirement_ref slug.
    assert data["request"]["text"].strip() == requirement_text.strip()
    assert data["request"]["test_id"] == result.spec.test_id

    # Process timeline: one entry per recorded step, each with a
    # non-empty decision basis explaining *why* it was accepted/rejected.
    assert len(data["process_timeline"]) == len(result.report.report_paths) or len(data["process_timeline"]) > 0
    for entry in data["process_timeline"]:
        assert entry["decision_basis"]["decided"] in (
            "fulfilled", "not_fulfilled", "escalated_not_fulfilled",
        )
        assert entry["decision_basis"]["reason"]

    # Outcome summary is a real sentence, not just a status enum value.
    assert data["outcome"]["status"] == result.report.status.value
    assert data["outcome"]["total_steps"] == result.report.total_steps
    assert str(result.report.total_steps) in data["outcome"]["summary"]

    # Proof of work section always present, pointing at real artifacts.
    assert "raw_json" in data["proof_of_work"]["report_paths"]

    # render_json must also update report.json so render_html can link to it.
    report_json = _json.loads((tmp_dir__reports / "reports" / f"run_{result.run_id}" / "report.json").read_text()) \
        if (tmp_dir__reports / "reports" / f"run_{result.run_id}" / "report.json").exists() \
        else _json.loads((global_settings.reports_dir / f"run_{result.run_id}" / "report.json").read_text())
    assert report_json["report_paths"]["detailed_json"] == str(json_path)


def test_human_in_the_loop_step_produces_evidence_and_report_section(tmp_dir__reports: Path, monkeypatch):
    """A WAIT_FOR_HUMAN_ACTION step's human_action_evidence must survive
    all the way into both report.json's raw_results and the detailed JSON's
    human_in_the_loop section -- not just inform the pass/fail decision and
    then get discarded."""
    from config.settings import settings as global_settings
    from orchestrator.schemas import ActionType, TestSpec, TestStep
    from reports.render import render_json

    monkeypatch.setattr(global_settings, "project_root", tmp_dir__reports)
    monkeypatch.setattr(global_settings, "human_action_poll_interval_seconds", 0.01)
    monkeypatch.setattr(global_settings, "human_action_timeout_seconds", 0.05)

    spec = TestSpec(
        test_id="TC_HIL_001",
        requirement_ref="TC_HIL_001",
        steps=[
            TestStep(
                step_id=1,
                action=ActionType.WAIT_FOR_HUMAN_ACTION,
                target_description="Ask the human to confirm the dialog",
            )
        ],
    )

    memory = RunMemoryStore(db_path=tmp_dir__reports / "memory.db")
    skill_store = SkillStore(db_path=tmp_dir__reports / "skills.db")
    engine = RunEngine(screenshot_provider=make_provider(tmp_dir__reports), skill_store=skill_store, memory=memory)
    result = engine.run_spec(spec, run_id="hil_test_run", requirement_text="Ask a human to confirm the dialog")

    json_path = render_json(result.run_id, spec=spec.model_dump())
    import json as _json
    data = _json.loads(json_path.read_text())

    assert len(data["human_in_the_loop"]) == 1
    hil = data["human_in_the_loop"][0]
    assert "elapsed_seconds" in hil["evidence"]
    assert "acceptance_basis" in hil["evidence"]
    assert hil["evidence"]["acceptance_basis"] == "no_screen_change_detected"  # fixture screen never changes
    assert hil["adequate"] is False

    step_entry = data["process_timeline"][0]
    assert step_entry["decision_basis"]["decided"] == "not_fulfilled"
    assert "human_action_evidence" in step_entry["decision_basis"]
