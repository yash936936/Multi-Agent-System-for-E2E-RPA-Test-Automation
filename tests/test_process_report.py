"""
tests/test_process_report.py

Regression coverage for a real bug found via a live run: the ASSERT
action correctly reports action_taken="none" from execute_step (there's
nothing to *do* for an assert -- the actual check runs afterward in
run_engine, which attaches assertion_passed to that same result). But
process_report.py's _decision_basis() dispatches its detailed reasoning
purely on the `action` string, and its catch-all "else" branch (hit
whenever action isn't one of the explicitly-handled values) only ever
looked at `escalate`, silently ignoring a real assertion_passed value.

That meant a step whose real check_assertion() genuinely failed
(assertion_passed=False) was still displayed as "fulfilled" in the
process report, because escalate happened to be False -- directly
contradicting the run's overall status, which report_aggregator's
_determine_status() correctly derives from assertion_passed. A real
run showed exactly this: every step's decision_basis said "fulfilled",
while outcome.status was "failed" with 0/1 passed_steps.
"""
from __future__ import annotations

from reports.process_report import _decision_basis


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
