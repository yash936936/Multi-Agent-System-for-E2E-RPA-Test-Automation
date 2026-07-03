"""
Report rendering — reports/render.py

Turns the structured artifacts a run already produces on disk
(report.json + raw_results.json from orchestrator/report_aggregator.py,
plus trace.jsonl from orchestrator/kernel.py when the kernel dispatch path
was used) into the HTML/PDF report promised by APPFLOW.md §2.6.

Two entry points:
    render_html(run_id, spec=None) -> Path to the written .html file
    render_pdf(html_path)          -> Path to the written .pdf file
                                       (requires the optional `report` extra;
                                       degrades gracefully with a clear error
                                       if weasyprint isn't installed rather
                                       than crashing the whole CLI command)

Note: orchestrator/run_engine.py now routes every Planner/Vision/DataSynth
call through OrchestratorKernel.call_tool() (decisions.md D-008), so
trace.jsonl is populated for real runs. render_html() still handles a
missing trace file gracefully (renders an empty audit trace section
rather than failing) for older runs produced before this change, or any
run_id with no trace for another reason.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from config.settings import settings
from orchestrator.schemas import RunReport

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _run_dir(run_id: str) -> Path:
    return settings.reports_dir / f"run_{run_id}"


def _load_report(run_id: str) -> RunReport:
    path = _run_dir(run_id) / "report.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No report.json found for run '{run_id}' at {path}. "
            "Run the test suite first (aura execute ...) before rendering a report."
        )
    return RunReport.model_validate_json(path.read_text(encoding="utf-8"))


def _load_raw_results(run_id: str) -> dict:
    path = _run_dir(run_id) / "raw_results.json"
    if not path.exists():
        return {"step_results": [], "skills_learned": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_trace(run_id: str) -> list[dict]:
    path = _run_dir(run_id) / "trace.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def render_html(run_id: str, spec: dict | None = None, autoscan_report=None, ui_audit_report=None) -> Path:
    """
    Renders reports/run_<id>/report.html from the artifacts already on
    disk for that run. `spec` is optional (the TestSpec as a dict, for the
    subtitle line) since not every caller has it handy.

    `autoscan_report` (orchestrator.autoscan.AutoScanReport) and
    `ui_audit_report` (orchestrator.ui_audit_runner.UIAuditReport) are also
    optional -- passed through from `aura execute --scroll-test`/`--ui-audit`
    so those findings land in the actual report file, not just console
    output (previously a real gap: --scroll-test results were printed to
    the terminal and then discarded, never reaching report.html).
    """
    report = _load_report(run_id)
    raw = _load_raw_results(run_id)
    trace = _load_trace(run_id)

    step_results = raw.get("step_results", [])
    skills_learned = raw.get("skills_learned", [])
    # The final spec-level assertion (TRD §4.1 `assertions`, distinct from
    # per-step expected_state) is recorded as one extra pseudo-step with
    # step_id = total_steps + 1 (see orchestrator/run_engine.py) so it
    # shows up in the step-detail list, but it isn't one of the spec's
    # actual steps -- exclude it here so "Passed" never exceeds "Total steps".
    passed_steps = sum(
        1
        for r in step_results
        if r.get("step_id", 0) <= report.total_steps
        and not r.get("escalate")
        and r.get("assertion_passed") is not False
    )

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("run_report.html.j2")

    spec_explanation = None
    if spec:
        try:
            from agents.planner.explainer import explain_spec
            from orchestrator.schemas import TestSpec

            spec_explanation = explain_spec(TestSpec.model_validate(spec))
        except Exception:
            # Explanation is a presentation nicety, not a required artifact --
            # never let a malformed/partial spec dict block report rendering.
            spec_explanation = None

    html = template.render(
        report=report,
        spec=spec,
        spec_explanation=spec_explanation,
        step_results=step_results,
        skills_learned=skills_learned,
        trace_json=json.dumps(trace, indent=2, default=str) if trace else "[]  # no tool-call trace recorded for this run",
        passed_steps=passed_steps,
        confidence_threshold=settings.vision_confidence_threshold,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        autoscan_report=autoscan_report,
        ui_audit_report=ui_audit_report,
    )

    out_path = _run_dir(run_id) / "report.html"
    out_path.write_text(html, encoding="utf-8")

    # Keep report.json's report_paths in sync so later readers (CLI, other
    # tooling) can find the rendered artifact without recomputing the path.
    report_json_path = _run_dir(run_id) / "report.json"
    report_dict = json.loads(report_json_path.read_text(encoding="utf-8"))
    report_dict.setdefault("report_paths", {})["html"] = str(out_path)
    report_json_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")

    return out_path


def render_pdf(html_path: Path) -> Path:
    """
    Converts an already-rendered HTML report to PDF via weasyprint (the
    `report` optional dependency group in pyproject.toml). Raises a clear,
    actionable error instead of an import traceback if it isn't installed —
    PDF export is optional, HTML is always available.
    """
    try:
        from weasyprint import HTML  # noqa: PLC0415 - intentionally optional/deferred
    except ImportError as e:
        raise RuntimeError(
            "PDF export requires the optional 'report' dependency group. "
            "Install it with: pip install -e '.[report]'"
        ) from e

    pdf_path = html_path.with_suffix(".pdf")
    HTML(filename=str(html_path)).write_pdf(str(pdf_path))

    report_json_path = html_path.parent / "report.json"
    if report_json_path.exists():
        report_dict = json.loads(report_json_path.read_text(encoding="utf-8"))
        report_dict.setdefault("report_paths", {})["pdf"] = str(pdf_path)
        report_json_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")

    return pdf_path
