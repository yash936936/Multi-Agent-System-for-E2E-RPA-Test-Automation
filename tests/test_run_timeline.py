"""
tests/test_run_timeline.py

Re-architecture Phase 1 (docs/decisions.md D-072): orchestrator/run_timeline.py's
merge across click_resolution_log + assertion_audit_log, plus `aura explain`'s
CLI wiring (aura/cli/explain_cmd.py).
"""
from __future__ import annotations

from orchestrator.assertion_audit_log import assertion_audit_log
from orchestrator.click_resolution_log import click_resolution_log
from orchestrator.run_timeline import build_timeline


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
