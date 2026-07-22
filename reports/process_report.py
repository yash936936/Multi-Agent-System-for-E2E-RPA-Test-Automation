"""
Process-oriented report builder — reports/process_report.py

Turns the same on-disk artifacts reports/render.py already reads
(report.json, raw_results.json, trace.jsonl) into one shared structure
answering the questions a report reader actually asks, rather than just
listing per-step technical fields:

  - What was the request?
  - What steps did AURA take to fulfil it, in order?
  - On what basis did AURA decide each step -- and the run overall --
    was successful? (dual-verification agreement, assertion match,
    capability-adapter evidence, human confirmation, etc. -- never just
    "confidence >= threshold" with no further detail)
  - Which concrete on-screen/DOM elements did it interact with?
  - Where a human was in the loop, was their action sufficient to be
    accepted as fulfilling that step, and on what basis?
  - What was the final outcome?
  - What's the proof of work (screenshots, trace entries, evidence
    payloads) backing every claim above?

Both reports/render.py::render_html() and this module's own render_json()
call build_process_report() so the HTML and JSON outputs are always
describing the exact same underlying facts -- never two independently
-maintained narratives that can drift out of sync with each other.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config.settings import settings
from orchestrator.schemas import RunReport

_ACTION_LABELS = {
    "navigate": "Navigate browser",
    "click": "Click element",
    "type": "Type text into element",
    "scroll": "Scroll page",
    "assert": "Assert expected state",
    "capability_check": "Capability check (non-browser system)",
    "wait_for_human": "Wait for human action",
    "none": "No action taken",
}


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


def _step_spec_by_id(spec: dict | None) -> dict[int, dict]:
    if not spec:
        return {}
    return {s["step_id"]: s for s in spec.get("steps", [])}


def _decision_basis(r: dict, step_def: dict | None) -> dict[str, Any]:
    """
    The single most important addition this module makes: for every step,
    an explicit, structured answer to "why did AURA consider this step
    fulfilled (or not)?" -- built from whichever evidence that step type
    actually produced, never a placeholder or a guess.
    """
    action = r.get("action_taken")
    escalate = bool(r.get("escalate"))
    assertion_passed = r.get("assertion_passed")
    confidence = r.get("confidence", 0.0)
    threshold = settings.vision_confidence_threshold

    if action == "wait_for_human":
        hae = r.get("human_action_evidence") or {}
        basis_map = {
            "verified_against_expected_state": "The screen changed after the human acted, and the "
                "resulting state was independently checked against the step's stated expected_state.",
            "screen_change_accepted_no_expected_state": "The screen changed after the human acted; no "
                "specific expected_state was given for this step, so the visible change itself was "
                "accepted as evidence the requested action happened.",
            "no_screen_change_detected": "No screen change was detected within the configured wait "
                "window -- the human action (if any) could not be confirmed, so this step was not "
                "accepted as fulfilled.",
        }
        basis = {
            "decided": "fulfilled" if assertion_passed else "not_fulfilled",
            "reason": basis_map.get(hae.get("acceptance_basis"), "No human-action evidence recorded."),
            "human_action_evidence": hae,
        }
    elif escalate:
        basis = {
            "decided": "escalated_not_fulfilled",
            "reason": "Confidence/evidence did not clear the bar for autonomous "
                      "completion -- handed to escalation rather than guessed at.",
        }
    elif action in ("click", "type"):
        ev = r.get("verification_evidence") or {}
        method = r.get("verification_method")
        if method == "dual-method-confirmed" and ev.get("agreement"):
            basis = {
                "decided": "fulfilled",
                "reason": "OCR and DOM locators independently found the same element "
                          "and agreed on its location -- accepted without needing a tie-break.",
            }
        elif method == "dual-method-confirmed" and ev.get("agreement") is False:
            basis = {
                "decided": "fulfilled",
                "reason": (
                    f"OCR and DOM locators disagreed on location; resolved via "
                    f"'{ev.get('tie_break_applied', 'n/a')}' tie-break rule, "
                    f"which selected the {ev.get('winner', 'n/a')} candidate."
                ),
            }
        elif method == "single-method":
            basis = {
                "decided": "fulfilled",
                "reason": "Only one locator method (OCR or DOM) found a matching "
                          "element; accepted since it independently cleared the "
                          f"confidence threshold ({confidence:.2f} >= {threshold:.2f}).",
            }
        else:
            basis = {
                "decided": "fulfilled",
                "reason": f"Element located with confidence {confidence:.2f} "
                          f"(threshold {threshold:.2f}).",
            }
    elif action == "capability_check":
        cap = r.get("capability_result") or {}
        basis = {
            "decided": "fulfilled" if cap.get("passed") else "not_fulfilled",
            "reason": f"Non-browser capability adapter ({cap.get('capability', 'unknown')}) "
                      f"returned evidence directly from the target system (confidence "
                      f"{cap.get('confidence', 0.0):.2f}); no visual guess involved.",
            "evidence": cap.get("evidence"),
        }
    elif action == "assert":
        basis = {
            "decided": "fulfilled" if assertion_passed else "not_fulfilled",
            "reason": "Post-action screenshot checked via OCR against the step's/spec's "
                      "expected_state text.",
        }
    elif action == "navigate":
        basis = {
            "decided": "fulfilled",
            "reason": f"Browser navigation completed and page settled "
                      f"(URL: {(step_def or {}).get('url', 'n/a')}).",
        }
    else:
        if assertion_passed is not None:
            # A real assertion check ran and produced a verdict for this
            # step (this is exactly what happens for the ASSERT action:
            # execute_step itself takes no action -- action_taken stays
            # "none" -- and the actual pass/fail check runs afterward in
            # run_engine, attaching assertion_passed to this same result).
            # Ignoring that value here (falling back to escalate-only,
            # below) would show "fulfilled" for a step whose real
            # assertion genuinely failed, directly contradicting the run's
            # overall status (which report_aggregator._determine_status()
            # correctly derives from assertion_passed, not action_taken).
            basis = {
                "decided": "fulfilled" if assertion_passed else "not_fulfilled",
                "reason": "Post-action screenshot checked via OCR against the step's/spec's "
                          "expected_state text.",
            }
        else:
            basis = {"decided": "fulfilled" if not escalate else "not_fulfilled", "reason": "No action required."}

    basis["confidence"] = confidence
    return basis


def _element_interacted(r: dict, step_def: dict | None) -> dict[str, Any] | None:
    """What concrete element (if any) this step actually touched --
    collapsed from whichever of OCR/DOM/target_description produced it,
    so a report reader gets one consistent answer instead of having to
    reconcile three overlapping fields themselves."""
    action = r.get("action_taken")
    if action not in ("click", "type"):
        return None

    ev = r.get("verification_evidence") or {}
    winner = ev.get("winner")
    candidate = ev.get(winner) if winner in ("ocr", "dom") else None

    return {
        "requested_target": (step_def or {}).get("target_description")
        or (step_def or {}).get("field_description"),
        "resolved_via": winner or r.get("verification_method") or "unknown",
        "matched_text": (candidate or {}).get("matched_text") if candidate else None,
        "role": (candidate or {}).get("role") if candidate else None,
        "coordinates": r.get("target_coords"),
    }


def build_process_report(run_id: str, spec: dict | None = None) -> dict[str, Any]:
    """
    Assembles the full process-oriented structure. Both render_html() (via
    reports/render.py) and render_json() (below) build their output from
    this one function's return value.
    """
    report = _load_report(run_id)
    raw = _load_raw_results(run_id)
    trace = _load_trace(run_id)
    step_results = raw.get("step_results", [])
    skills_learned = raw.get("skills_learned", [])
    step_defs = _step_spec_by_id(spec)

    request_text = report.request_text or (spec or {}).get("requirement_ref") or ""

    process_timeline = []
    elements_interacted = []
    human_in_loop_steps = []

    for r in step_results:
        step_def = step_defs.get(r.get("step_id"))
        basis = _decision_basis(r, step_def)
        entry = {
            "step_id": r.get("step_id"),
            "action_label": _ACTION_LABELS.get(r.get("action_taken"), r.get("action_taken")),
            "action_taken": r.get("action_taken"),
            "instruction": (
                (step_def or {}).get("target_description")
                or (step_def or {}).get("field_description")
                or (step_def or {}).get("url")
                or (step_def or {}).get("expected_state")
                or (step_def or {}).get("target")
                or ""
            ),
            "decision_basis": basis,
            "escalated": bool(r.get("escalate")),
            "proof_of_work": {
                "screenshot_ref": r.get("screenshot_ref"),
                "visual_diff_image_ref": r.get("visual_diff_image_ref"),
            },
        }
        process_timeline.append(entry)

        el = _element_interacted(r, step_def)
        if el:
            elements_interacted.append({"step_id": r.get("step_id"), **el})

        if r.get("action_taken") == "wait_for_human":
            human_in_loop_steps.append({
                "step_id": r.get("step_id"),
                "instruction": entry["instruction"],
                "adequate": bool(r.get("assertion_passed")),
                "evidence": r.get("human_action_evidence") or {},
            })

    total = report.total_steps
    passed_steps = sum(
        1 for r in step_results
        if r.get("step_id", 0) <= total and not r.get("escalate") and r.get("assertion_passed") is not False
    )

    outcome = {
        "status": report.status.value,
        "total_steps": total,
        "passed_steps": passed_steps,
        "self_healed_steps": report.self_healed_steps,
        "escalated_steps": report.escalated_steps,
        "duration_seconds": report.duration_seconds,
        "human_in_the_loop": bool(human_in_loop_steps),
        "human_in_the_loop_all_adequate": (
            all(h["adequate"] for h in human_in_loop_steps) if human_in_loop_steps else None
        ),
        "summary": (
            f"{report.status.value.replace('_', ' ')} -- {passed_steps}/{total} steps confirmed fulfilled"
            + (f", {report.self_healed_steps} self-healed" if report.self_healed_steps else "")
            + (f", {report.escalated_steps} escalated for human review" if report.escalated_steps else "")
            + "."
        ),
    }

    return {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "request": {
            "text": request_text,
            "test_id": (spec or {}).get("test_id"),
            "preconditions": (spec or {}).get("preconditions", []),
            "assertions": (spec or {}).get("assertions", []),
        },
        "process_timeline": process_timeline,
        "elements_interacted": elements_interacted,
        "human_in_the_loop": human_in_loop_steps,
        "skills_learned": skills_learned,
        "outcome": outcome,
        "proof_of_work": {
            "report_paths": report.report_paths,
            "tool_call_trace_entries": len(trace),
            "raw_results_path": report.report_paths.get("raw_json"),
        },
    }


def render_json(run_id: str, spec: dict | None = None) -> Path:
    """Writes reports/run_<id>/report_detailed.json -- the same data the
    HTML report's new sections are built from, as a standalone machine
    -readable artifact for CI / downstream tooling / audit."""
    detailed = build_process_report(run_id, spec=spec)
    out_path = _run_dir(run_id) / "report_detailed.json"
    out_path.write_text(json.dumps(detailed, indent=2, default=str), encoding="utf-8")

    report_json_path = _run_dir(run_id) / "report.json"
    if report_json_path.exists():
        report_dict = json.loads(report_json_path.read_text(encoding="utf-8"))
        report_dict.setdefault("report_paths", {})["detailed_json"] = str(out_path)
        report_json_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")

    return out_path
