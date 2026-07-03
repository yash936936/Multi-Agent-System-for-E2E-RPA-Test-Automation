"""
Run-state memory — orchestrator/memory/state.db

Two responsibilities (TRD.md §7 "Recoverability" + WORKFLOW.md §Step 5.4
escalation path):

1. RunStateStore: persists the last-completed step_id for an in-flight
   run, so an interrupted run (crash, kill, power loss) can resume from
   the next step instead of restarting from scratch.

2. EscalationQueue: rows for steps that hit a guardrail HARD_STOP during
   self-healing and need a human to look at them (APPFLOW.md §2.7
   "Needs Review" queue).
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from config.settings import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_state (
    run_id TEXT PRIMARY KEY,
    test_id TEXT NOT NULL,
    last_completed_step INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'in_progress',
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS escalation_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    step_id INTEGER NOT NULL,
    reason TEXT NOT NULL,
    guardrail_snapshot TEXT,
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
"""


class RunMemoryStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (settings.memory_dir / "state.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- run state / resumability --------------------------------------------

    def start_run(self, run_id: str, test_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO run_state (run_id, test_id, last_completed_step, status, updated_at)
                VALUES (?, ?, 0, 'in_progress', ?)
                ON CONFLICT(run_id) DO NOTHING
                """,
                (run_id, test_id, time.time()),
            )

    def mark_step_complete(self, run_id: str, step_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE run_state SET last_completed_step = ?, updated_at = ? WHERE run_id = ?",
                (step_id, time.time(), run_id),
            )

    def finish_run(self, run_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE run_state SET status = ?, updated_at = ? WHERE run_id = ?",
                (status, time.time(), run_id),
            )

    def get_resume_point(self, run_id: str) -> int | None:
        """Returns the last-completed step_id, or None if the run is unknown."""
        with self._connect() as conn:
            row = conn.execute("SELECT last_completed_step FROM run_state WHERE run_id = ?", (run_id,)).fetchone()
        return row["last_completed_step"] if row else None

    def incomplete_runs(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM run_state WHERE status = 'in_progress'").fetchall()
        return [dict(r) for r in rows]

    # -- escalation queue -----------------------------------------------------

    def escalate(self, run_id: str, step_id: int, reason: str, guardrail_snapshot: dict) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO escalation_queue (run_id, step_id, reason, guardrail_snapshot, resolved, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (run_id, step_id, reason, json.dumps(guardrail_snapshot), time.time()),
            )
            return cur.lastrowid

    def pending_escalations(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM escalation_queue WHERE resolved = 0").fetchall()
        return [dict(r) for r in rows]

    def resolve_escalation(self, escalation_id: int) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE escalation_queue SET resolved = 1 WHERE id = ?", (escalation_id,))
