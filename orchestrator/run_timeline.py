"""
orchestrator/run_timeline.py

Re-architecture Phase 1 (docs/AURA_REARCHITECTURE_PLAN.md, docs/decisions.md
D-072) -- a merge layer, not a new log. Reads the existing structured JSONL
logs, filters to one run_id, and interleaves them by timestamp into one
ordered, typed timeline. Owns no state of its own; this is what
`aura explain <run_id>` renders.

Sources merged (all optional -- a run that never touched one of these
simply contributes zero events from it):
  - orchestrator/decision_trace_log.py   -- planner backend / capability /
    network-retry decisions
  - orchestrator/assertion_audit_log.py  -- assertion verdicts
  - orchestrator/click_resolution_log.py -- click-audit element decisions

`orchestrator/audit_logger.py`'s compliance log (who/what/tenant) is
deliberately NOT merged here -- that's a separate concern (per that
module's own docstring), not part of "what did AURA decide during this
run."
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class TimelineEvent:
    timestamp: str
    kind: str  # "decision_trace" | "assertion" | "click_resolution"
    summary: str
    detail: Dict[str, Any]


def _decision_trace_events(run_id: str) -> List[TimelineEvent]:
    from orchestrator.decision_trace_log import read_records

    events = []
    for r in read_records():
        # decision_trace_log records don't carry run_id today (it's a
        # cross-run planner/capability/network log) -- included
        # unfiltered would be misleading, so only records that happen to
        # carry a matching run_id in their free-form `detail` are kept.
        if r.get("detail", {}).get("run_id") == run_id:
            events.append(TimelineEvent(
                timestamp=r["timestamp"],
                kind="decision_trace",
                summary=f"[{r['category']}] {r['decision']} (backend={r['backend']})" + (f" -- {r['reason']}" if r.get("reason") else ""),
                detail=r,
            ))
    return events


def _assertion_events(run_id: str) -> List[TimelineEvent]:
    from orchestrator.assertion_audit_log import assertion_audit_log, read_records

    events = []
    for r in read_records(filepath=assertion_audit_log.filepath, run_id=run_id):
        verdict = "PASS" if r.get("passed") else "FAIL"
        events.append(TimelineEvent(
            timestamp=r["timestamp"],
            kind="assertion",
            summary=f"[assertion step {r.get('step_id')}] {verdict} via {r.get('method')} -- expected: {r.get('expected_state')!r}",
            detail=r,
        ))
    return events


def _click_resolution_events(run_id: str) -> List[TimelineEvent]:
    from orchestrator.click_resolution_log import click_resolution_log, read_records

    events = []
    for r in read_records(filepath=click_resolution_log.filepath, run_id=run_id):
        outcome = "clicked" if r.get("clicked") else f"rejected ({r.get('rejected_reason')})"
        state = "" if r.get("state_changed") is None else f", state_changed={r['state_changed']}"
        events.append(TimelineEvent(
            timestamp=r["timestamp"],
            kind="click_resolution",
            summary=f"[click step {r.get('step_id')}] {r.get('label')!r} ({r.get('band')}) via {r.get('resolution_strategy')} -- {outcome}{state}",
            detail=r,
        ))
    return events


def build_timeline(run_id: str) -> List[TimelineEvent]:
    """Merges every source above, filtered to `run_id`, ordered by timestamp."""
    events: List[TimelineEvent] = []
    events.extend(_decision_trace_events(run_id))
    events.extend(_assertion_events(run_id))
    events.extend(_click_resolution_events(run_id))
    events.sort(key=lambda e: e.timestamp)
    return events
