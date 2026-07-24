"""
orchestrator/decision_trace_log.py

AF3 (docs/decisions.md, Phase AF) -- structured, append-only JSONL log of
every meaningful "what did AURA decide, and which backend/tool did it
actually call" moment, distinct from the other logs that already exist:
  - orchestrator/audit_logger.py    -- compliance: who/what/tenant
  - orchestrator/assertion_audit_log.py (AB2) -- assertion verdicts only:
    what was checked, which OCR method decided it
  - config/logging_setup.py (AF2)  -- persists every existing
    logging.getLogger(...) call, but as prose log lines, not a
    structured, queryable decision record

This is the one that answers "which backend did the planner actually
use, and why did it escalate" across a run history, mechanically -- not
by grepping logs/aura.log's prose for a message string that might change
wording later. Built directly on top of AF2's logging plumbing being in
place (every call here also goes through `logging.getLogger`, so the
same information lands in logs/aura.log too, in addition to this
dedicated structured file) -- this was deliberately deferred until AF2
existed rather than duplicating that plumbing.

Each line is one JSON record:
{
    "timestamp": ISO-8601 UTC,
    "category": str,   # "planner_backend" (AF3), "capability_adapter"
                        # (AF4), or "network_retry" (AF5) so far; open to
                        # more categories later (vision_dispatch, ...)
                        # without a schema change, since detail is a
                        # free-form dict
    "decision": str,    # "attempt" | "retry" | "escalate" | "fallback" |
                        # "success" | "exhausted" | "crash_caught" |
                        # "recovered_after_retry" | "gave_up_after_retries"
    "backend": str,     # e.g. "HermesAgentBackend", "CloudLLMBackend",
                        # or a capability type value e.g. "api", "fake"
    "reason": str | None,
    "detail": dict,     # free-form extra context (exception type, etc.)
}

find_anomalies() flags the two decision shapes actually worth a human
looking at: "exhausted" (every backend failed, no spec could be
produced at all) and "fallback" (the run kept going, but on a
lower-quality regex-extracted spec rather than an LLM-authored one --
not a crash, but a real quality degradation worth knowing about even
when the run technically succeeded).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

_logger = logging.getLogger(__name__)


class DecisionTraceLog:
    def __init__(self, filepath: str = "logs/decision_trace.jsonl"):
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        self.filepath = filepath
        self._lock = threading.Lock()

    def log(
        self,
        category: str,
        decision: str,
        backend: str,
        reason: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": category,
            "decision": decision,
            "backend": backend,
            "reason": reason,
            "detail": detail or {},
        }
        # Also goes through AF2's logging plumbing, at a level matching
        # how serious the decision is -- "exhausted" is the one shape
        # that means the run couldn't produce a spec at all.
        level = logging.ERROR if decision == "exhausted" else logging.INFO
        _logger.log(level, "decision_trace: %s/%s backend=%s reason=%s", category, decision, backend, reason)
        with self._lock:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")


# Global singleton, matching orchestrator/assertion_audit_log.py's and
# orchestrator/audit_logger.py's existing pattern.
decision_trace_log = DecisionTraceLog()


def read_records(filepath: str = "logs/decision_trace.jsonl", category: Optional[str] = None) -> Iterator[Dict[str, Any]]:
    """Reads back logged records, optionally filtered to one category."""
    path = Path(filepath)
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if category is not None and record.get("category") != category:
                continue
            yield record


def find_anomalies(filepath: str = "logs/decision_trace.jsonl", category: Optional[str] = None) -> list[Dict[str, Any]]:
    """
    Flags every "exhausted" (total planner failure, no spec produced --
    the crash this whole phase was written in response to, now at least
    fully logged instead of just raising), "fallback" (run survived,
    but degraded to LocalHeuristicBackend's regex-extracted spec instead
    of an LLM-authored one -- worth knowing about even on a technically
    passing run), "crash_caught" (AF4: a capability adapter raised an
    exception instead of returning a normal result -- the run survived
    because run_engine.py's CAPABILITY_CHECK handling catches this, but
    a raising adapter is itself a real bug worth finding and fixing,
    distinct from an adapter deliberately returning escalate=True), and
    "gave_up_after_retries" (AF5: a network call to CloudLLMBackend/
    HermesAgentClient exhausted its retry budget -- the caller's own
    escalation chain still applies on top of this, but this specific
    record answers "is this backend flaky lately" across a run history,
    distinct from "recovered_after_retry", which is NOT flagged here
    since a transient failure that self-resolved isn't an anomaly worth
    a human's attention the way a persistent one is) record.
    """
    return [
        r for r in read_records(filepath, category=category)
        if r.get("decision") in ("exhausted", "fallback", "crash_caught", "gave_up_after_retries")
    ]
