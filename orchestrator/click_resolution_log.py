"""
orchestrator/click_resolution_log.py

Re-architecture Phase 1 (docs/AURA_REARCHITECTURE_PLAN.md, docs/decisions.md
D-072) -- structured, append-only JSONL log of every click-audit element
decision made by `orchestrator/ui_audit_runner.py::_run_click_audit`.

This is the exact gap the re-architecture plan called out: `resolution_strategy`
already existed on `ClickCheckResult` (added in D-044), but nothing logged
*why* an element was or wasn't a click candidate in the first place, or which
change-detection method produced its `state_changed` verdict. Same JSONL
shape/pattern as the two logs that already exist:
  - orchestrator/decision_trace_log.py   -- planner backend / capability /
    network-retry decisions
  - orchestrator/assertion_audit_log.py  -- assertion verdicts

Each line is one JSON record:
{
    "timestamp": ISO-8601 UTC,
    "run_id": str,
    "step_id": int,           # 8100 + i, matching the screenshot naming
                                # _run_click_audit already uses for this loop
    "label": str,
    "band": str,
    "source": str,             # "dom" | "ocr" | "dom_extractor_direct"
    "looks_interactive": bool,
    "rejected_reason": str | None,  # e.g. "no_dom_match", "unreachable" -- None if it was clicked
    "resolution_strategy": str,     # same vocabulary as ClickCheckResult.resolution_strategy
    "clicked": bool,
    "change_detection_method": str,  # "mutation_observer" | "hash_diff" -- "hash_diff" until Phase 4 lands
    "state_changed": bool | None,
    "new_tab_opened": bool,
}

`find_anomalies()` flags the one shape this log exists to make visible
mechanically instead of by re-reading a screenshot overlay: a real, clicked
candidate whose change-detection verdict came back `state_changed=False`
(D-067's "passed but nothing happened" bug class) -- distinct from an
element that was never clicked at all (state_changed=None), which isn't an
anomaly, just an unreachable/rejected candidate.
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


class ClickResolutionLog:
    def __init__(self, filepath: str = "logs/click_resolution.jsonl"):
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        self.filepath = filepath
        self._lock = threading.Lock()

    def log(
        self,
        run_id: str,
        step_id: int,
        label: str,
        band: str,
        source: str,
        looks_interactive: bool,
        resolution_strategy: str,
        clicked: bool,
        rejected_reason: Optional[str] = None,
        change_detection_method: str = "hash_diff",
        state_changed: Optional[bool] = None,
        new_tab_opened: bool = False,
    ) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "step_id": step_id,
            "label": label,
            "band": band,
            "source": source,
            "looks_interactive": looks_interactive,
            "rejected_reason": rejected_reason,
            "resolution_strategy": resolution_strategy,
            "clicked": clicked,
            "change_detection_method": change_detection_method,
            "state_changed": state_changed,
            "new_tab_opened": new_tab_opened,
        }
        _logger.debug(
            "click_resolution: run=%s step=%s label=%r strategy=%s clicked=%s state_changed=%s",
            run_id, step_id, label, resolution_strategy, clicked, state_changed,
        )
        with self._lock:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")


# Global singleton, matching decision_trace_log's/assertion_audit_log's
# existing pattern.
click_resolution_log = ClickResolutionLog()


def read_records(filepath: str = "logs/click_resolution.jsonl", run_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
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


def find_anomalies(filepath: str = "logs/click_resolution.jsonl", run_id: Optional[str] = None) -> list[Dict[str, Any]]:
    """
    Flags every record where a real click happened (clicked=True) but the
    change-detection verdict came back state_changed=False -- D-067's
    "passed but nothing happened" bug class, now mechanically greppable
    from a run's log instead of needing a screenshot overlay to notice.
    """
    return [
        r for r in read_records(filepath, run_id=run_id)
        if r.get("clicked") is True and r.get("state_changed") is False
    ]
