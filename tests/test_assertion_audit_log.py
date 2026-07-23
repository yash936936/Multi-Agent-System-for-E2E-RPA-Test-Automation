"""
tests/test_assertion_audit_log.py

AB2 (docs/decisions.md D-057's backlog) regression tests.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from orchestrator.assertion_audit_log import AssertionAuditLog, find_anomalies, read_records


@pytest.fixture()
def tmp_log_path():
    with tempfile.TemporaryDirectory() as d:
        yield str(Path(d) / "assertion_audit.jsonl")


def test_log_writes_one_json_line_per_call(tmp_log_path):
    log = AssertionAuditLog(filepath=tmp_log_path)
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

    lines = Path(tmp_log_path).read_text().strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["run_id"] == "run-1"
    assert first["step_id"] == 1
    assert first["passed"] is True
    assert first["method"] == "literal_ocr"


def test_read_records_filters_by_run_id(tmp_log_path):
    log = AssertionAuditLog(filepath=tmp_log_path)
    log.log(run_id="run-a", step_id=1, expected_state="x", detail={"passed": True, "method": "literal_ocr"}, escalate=False)
    log.log(run_id="run-b", step_id=1, expected_state="y", detail={"passed": False, "method": "literal_ocr"}, escalate=True)

    run_a_records = list(read_records(tmp_log_path, run_id="run-a"))
    assert len(run_a_records) == 1
    assert run_a_records[0]["expected_state"] == "x"


def test_find_anomalies_flags_the_exact_d056_bug_shape(tmp_log_path):
    """
    AB2's core payoff: D-056's bug was a step reporting escalate=False
    while its real assertion had genuinely failed (assertion_passed=False)
    -- silently displayed as "fulfilled". find_anomalies must flag exactly
    that combination, and NOT flag either of the two "normal" shapes
    (passed+not-escalated, or failed+escalated).
    """
    log = AssertionAuditLog(filepath=tmp_log_path)
    # Normal: passed, not escalated -- fine.
    log.log(run_id="run-1", step_id=1, expected_state="a", detail={"passed": True, "method": "literal_ocr"}, escalate=False)
    # Normal: failed AND escalated -- the system correctly flagged it, fine.
    log.log(run_id="run-1", step_id=2, expected_state="b", detail={"passed": False, "method": "literal_ocr"}, escalate=True)
    # THE BUG SHAPE: failed but NOT escalated -- this is what D-056 was.
    log.log(run_id="run-1", step_id=3, expected_state="c", detail={"passed": False, "method": "structural_fallback"}, escalate=False)

    anomalies = find_anomalies(tmp_log_path)
    assert len(anomalies) == 1
    assert anomalies[0]["step_id"] == 3
    assert anomalies[0]["expected_state"] == "c"


def test_find_anomalies_on_empty_or_missing_log_returns_empty(tmp_log_path):
    # File doesn't exist yet -- must not raise.
    assert find_anomalies(tmp_log_path) == []


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
