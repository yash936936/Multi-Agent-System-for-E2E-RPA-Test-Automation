"""
JUnit XML rendering — reports/junit.py

Phase G2 (decisions.md D-026): turns a run's already-produced artifacts
(report.json + raw_results.json, same source data reports/render.py's HTML
report reads) into a standard JUnit XML <testsuite> so AURA's output can be
consumed by any CI system that understands the format (GitHub Actions,
GitLab CI, Jenkins, etc. all render JUnit XML natively) without needing a
bespoke AURA-specific integration.

One <testcase> per step. A step counts as a JUnit failure if it was
escalated (assertion_passed is False, or escalate=True and never resolved)
-- a step that was self-healed successfully is reported as *passing*
(action_taken reflects what actually happened) since from a CI consumer's
point of view "the test passed, with one auto-recovered hiccup" is the
accurate story, not "the test failed." Self-healing is noted once at the
<testsuite> level (via RunReport.self_healed_steps, a real, correctly
populated count) rather than attributed to a specific <testcase> -- there is
no reliable per-step "was this the one that got healed" signal available
today (VisionActionResult carries no such field, and ReportAggregator
doesn't thread SkillRecord step_ids into step_results either), so this
module doesn't fabricate one.

Deliberately reads from the same on-disk artifacts render_html() already
reads, rather than requiring RunEngine's caller to thread per-step results
through another parameter -- render_junit() only needs a RunReport (for
run_id/status/duration/report_paths) exactly like render_html() only needs
a run_id.
"""
from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from config.settings import settings
from orchestrator.schemas import RunReport, RunStatus


def _load_step_results(report: RunReport) -> list[dict]:
    raw_json_path = report.report_paths.get("raw_json")
    if not raw_json_path or not Path(raw_json_path).exists():
        return []
    data = json.loads(Path(raw_json_path).read_text(encoding="utf-8"))
    return data.get("step_results", [])


def _testcase_name(step: dict) -> str:
    step_id = step.get("step_id", "?")
    action = step.get("action_taken") or "step"
    return f"step_{step_id}_{action}"


def _step_failed(step: dict) -> bool:
    # A step is a JUnit failure if its assertion explicitly failed, or it
    # was escalated and never got a corrected/passing result recorded.
    # `assertion_passed is None` (no assertion configured for this step,
    # e.g. a plain click/type with no expected_state) is not a failure on
    # its own -- only `escalate=True` with nothing to show for it is.
    if step.get("assertion_passed") is False:
        return True
    if step.get("escalate") and step.get("assertion_passed") is not True:
        return True
    return False


def build_testsuite_element(report: RunReport, suite_name: str | None = None) -> ET.Element:
    """
    Builds a single <testsuite> element for one run's RunReport. Exposed
    separately from render_junit() so `aura execute --all --junit-out` can
    build one <testsuite> per spec and combine them into one file (a
    <testsuites> root with multiple children) instead of overwriting the
    same file once per spec.
    """
    steps = _load_step_results(report)
    failures = sum(1 for s in steps if _step_failed(s))

    suite = ET.Element(
        "testsuite",
        {
            "name": suite_name or report.run_id,
            "tests": str(len(steps)) if steps else str(report.total_steps),
            "failures": str(failures),
            "errors": "0",
            "skipped": "0",
            "time": f"{report.duration_seconds:.3f}",
        },
    )

    if not steps:
        # No per-step detail on disk (e.g. raw_json missing/corrupted) --
        # still emit one testcase summarizing the run rather than an
        # empty <testsuite> a CI dashboard would render as "0 tests ran,"
        # which reads as "nothing was tested" rather than "detail
        # unavailable."
        tc = ET.SubElement(
            suite,
            "testcase",
            {"name": report.run_id, "classname": report.run_id, "time": f"{report.duration_seconds:.3f}"},
        )
        if report.status in (RunStatus.FAILED, RunStatus.ESCALATED):
            failure = ET.SubElement(tc, "failure", {"message": f"Run status: {report.status.value}"})
            failure.text = "Per-step detail unavailable (raw_results.json missing) -- see report_paths on the RunReport."
        return suite

    for step in steps:
        tc = ET.SubElement(
            suite,
            "testcase",
            {"name": _testcase_name(step), "classname": report.run_id, "time": "0"},
        )
        if _step_failed(step):
            confidence = step.get("confidence")
            message = f"escalate={step.get('escalate')}, assertion_passed={step.get('assertion_passed')}"
            if confidence is not None:
                message += f", confidence={confidence}"
            failure = ET.SubElement(tc, "failure", {"message": escape(message)})
            evidence = step.get("capability_result") or {}
            failure.text = escape(json.dumps(evidence, default=str)[:2000]) if evidence else "No further evidence recorded for this step."

    if report.self_healed_steps > 0:
        # Phase G2 fix (decisions.md D-026 addendum): this used to check
        # `step.get("healed_via", "")` per step, but VisionActionResult
        # (the actual schema every entry in step_results is built from --
        # see orchestrator/schemas.py) has no `healed_via` field, and
        # ReportAggregator doesn't tag which specific step_id a learned
        # skill corrected either (SkillRecord isn't threaded into
        # step_results at all). That branch could therefore never fire --
        # it silently read the "" default on every single step, always.
        # There's no reliable per-step attribution available today, only
        # the whole-run count RunReport.self_healed_steps already carries
        # correctly, so this reports that honestly at the suite level
        # instead of falsely attributing it to one testcase.
        suite_out = ET.SubElement(suite, "system-out")
        suite_out.text = (
            f"{report.self_healed_steps} step(s) in this run were self-healed "
            "(exact step attribution not available at the per-testcase level)."
        )

    return suite


def render_junit(report: RunReport, out_path: str | Path | None = None, suite_name: str | None = None) -> Path:
    """
    Single-spec entry point: writes one <testsuites><testsuite>...
    file for one RunReport. For `aura execute --all`, use
    build_testsuite_element() per spec and render_junit_suites() to
    combine them (see below) instead of calling this once per spec, which
    would just overwrite the same file each time.
    """
    root = ET.Element("testsuites")
    root.append(build_testsuite_element(report, suite_name=suite_name))
    return _write(root, out_path, report.run_id)


def render_junit_suites(suites: list[ET.Element], out_path: str | Path) -> Path:
    """Combines multiple pre-built <testsuite> elements (from build_testsuite_element) into one JUnit file, for `aura execute --all --junit-out`."""
    root = ET.Element("testsuites")
    for suite in suites:
        root.append(suite)
    return _write(root, out_path, "combined")


def _write(root: ET.Element, out_path: str | Path | None, default_stem: str) -> Path:
    if out_path is None:
        out_path = settings.reports_dir / f"junit_{default_stem}.xml"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(out_path, encoding="utf-8", xml_declaration=True)
    return out_path
