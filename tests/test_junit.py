"""
Tests for reports/junit.py -- Phase G2 (decisions.md D-026).

The junit.py module existed in the codebase with no test coverage before
this pass (found during Phase G work, see decisions.md D-026's "how this
entry came to be written" note) -- these tests exercise it against real
on-disk raw_results.json fixtures, the same artifact shape
orchestrator/report_aggregator.py actually produces, not a mocked-away
version of it.
"""
from __future__ import annotations

import json
from xml.etree import ElementTree as ET

from orchestrator.schemas import RunReport, RunStatus
from reports.junit import build_testsuite_element, render_junit, render_junit_suites


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
