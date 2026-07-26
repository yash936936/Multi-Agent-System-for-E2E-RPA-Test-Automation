"""
tests/test_audit_report_cmd.py

Resolves the D-072-flagged doc/code drift: `docs/STATUS.md`'s D-061
entry claimed `aura audit-report` shipped, but it never existed as a
CLI command until this pass (`aura/cli/audit_report_cmd.py`). Tests
that it actually finds the two known anomaly shapes
(`orchestrator/assertion_audit_log.py`'s D-056 shape,
`orchestrator/click_resolution_log.py`'s D-067 shape) for a given
run_id, and reports clean when there are none.
"""
from __future__ import annotations

from aura.cli.audit_report_cmd import audit_report
from orchestrator.assertion_audit_log import assertion_audit_log
from orchestrator.click_resolution_log import click_resolution_log


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
