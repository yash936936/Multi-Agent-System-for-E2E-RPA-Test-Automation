"""
orchestrator/assertion_audit_log.py

AB2 (docs/decisions.md D-057's backlog) -- structured, append-only JSONL
log of every real assertion check (check_assertion_detailed() call),
separate from the human-readable run report. This is deliberately
distinct from orchestrator/audit_logger.py's AuditLogger (Phase 19,
tenant/user compliance actions like "who ran what") -- this log is about
verification *evidence*: what was checked, which method decided it, and
what the raw OCR result was, across every run, so a question like "did
check_assertion ever silently do the wrong thing this week" can be
answered by reading a log file instead of re-running things or reading
source code.

Each line is one JSON record:
{
    "timestamp": ISO-8601 UTC,
    "run_id": str,
    "step_id": int,
    "expected_state": str,
    "passed": bool,
    "method": str,          # "literal_ocr" | "structural_sentinel" | "structural_fallback" | ...
    "matched_text": str | None,
    "ocr_excerpt": str | None,
    "escalate": bool,       # the step's own escalate flag at the time this was recorded
}

Building block for AE2's planned `aura audit-report <run_id>` command
(not implemented yet) -- `find_anomalies()` below is the first piece of
that: it flags exactly D-056's bug shape (a step that reported
`escalate=False` while its real assertion failed) mechanically.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional


class AssertionAuditLog:
    def __init__(self, filepath: str = "logs/assertion_audit.jsonl"):
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        self.filepath = filepath
        self._lock = threading.Lock()

    def log(
        self,
        run_id: str,
        step_id: int,
        expected_state: str,
        detail: Dict[str, Any],
        escalate: bool,
    ) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "step_id": step_id,
            "expected_state": expected_state,
            "passed": detail.get("passed"),
            "method": detail.get("method"),
            "matched_text": detail.get("matched_text"),
            "ocr_excerpt": detail.get("ocr_excerpt"),
            "escalate": escalate,
        }
        with self._lock:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")


# Global singleton, matching orchestrator/audit_logger.py's pattern.
assertion_audit_log = AssertionAuditLog()


def read_records(filepath: str = "logs/assertion_audit.jsonl", run_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
    """Reads back logged records, optionally filtered to one run_id."""
    path = Path(filepath)
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if run_id is not None and record.get("run_id") != run_id:
                continue
            yield record


def find_anomalies(filepath: str = "logs/assertion_audit.jsonl", run_id: Optional[str] = None) -> list[Dict[str, Any]]:
    """
    Flags the exact bug shape D-056 documented: a record where
    `escalate` is False but `passed` is False. Before D-057's fix to
    reports/process_report.py, this combination meant the process report
    displayed "fulfilled" for a step whose real check had genuinely
    failed -- silently. Any record matching this shape is worth a human
    look, since it means a step passed through without escalating despite
    its own recorded evidence saying it shouldn't have.
    """
    return [
        r for r in read_records(filepath, run_id=run_id)
        if r.get("escalate") is False and r.get("passed") is False
    ]
