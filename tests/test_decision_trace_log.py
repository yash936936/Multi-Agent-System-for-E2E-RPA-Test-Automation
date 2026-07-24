"""
tests/test_decision_trace_log.py

AF3 (docs/decisions.md, Phase AF) regression tests.
"""
from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.planner.spec_generator import CloudLLMBackend, LocalHeuristicBackend, generate_spec
from config.settings import settings as global_settings
from orchestrator.decision_trace_log import DecisionTraceLog, find_anomalies, read_records
from orchestrator.schemas import RequirementInput


@pytest.fixture()
def tmp_log_path():
    with tempfile.TemporaryDirectory() as d:
        yield str(Path(d) / "decision_trace.jsonl")


# --------------------------------------------------------------------------
# The module itself
# --------------------------------------------------------------------------

def test_log_writes_one_json_line_per_call(tmp_log_path):
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
