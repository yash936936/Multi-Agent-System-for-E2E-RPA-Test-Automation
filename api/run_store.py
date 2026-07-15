"""
Persistent run store — api/run_store.py

Replaces the in-memory `runs_store: dict` that used to live in
api/routers/runs.py (flagged in STATUS.md as losing all run history on
every process restart). Backed by SQLite under settings.memory_dir,
next to orchestrator/memory.py's state.db -- deliberately a separate
file (api_runs.db) since this store tracks API-surface run records
(tenant_id, spec, report, status) rather than RunEngine's own
step-resume/escalation bookkeeping.

Thread-safe via a single lock around each write, matching the
conservative approach already used by RunMemoryStore.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from config.settings import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS api_runs (
    run_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    report_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_api_runs_tenant ON api_runs(tenant_id);
"""

# Phase H1 (trend analytics): a run's "test identity" for history/pass-rate
# purposes -- spec.test_id if the caller supplied one (guided mode), else
# spec.test_name (autonomous mode's closest equivalent), else None (an
# untracked, one-off run with no stable identity -- excluded from
# trend/flaky queries rather than lumped together under a fake shared key).
_TEST_KEY_COLUMN = "test_key"


def _extract_test_key(spec: dict) -> Optional[str]:
    key = spec.get("test_id") or spec.get("test_name")
    return str(key) if key else None


class ApiRunStore:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or (settings.memory_dir / "api_runs.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            self._migrate_add_test_key(conn)

    @staticmethod
    def _migrate_add_test_key(conn: sqlite3.Connection) -> None:
        """
        Phase H1: adds the `test_key` column (+ index) to a pre-existing
        api_runs.db that predates this feature. SQLite's ALTER TABLE ADD
        COLUMN errors if the column already exists, so this is guarded
        rather than run unconditionally every startup.
        """
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(api_runs)").fetchall()}
        if _TEST_KEY_COLUMN not in existing_cols:
            conn.execute(f"ALTER TABLE api_runs ADD COLUMN {_TEST_KEY_COLUMN} TEXT")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_api_runs_test_key ON api_runs({_TEST_KEY_COLUMN})")

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create(self, run_id: str, tenant_id: str, user_id: str, spec: dict) -> dict:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        row = {
            "run_id": run_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "status": "queued",
            "spec_json": json.dumps(spec),
            "report_json": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
            "test_key": _extract_test_key(spec),
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO api_runs
                   (run_id, tenant_id, user_id, status, spec_json, report_json, error, created_at, updated_at, test_key)
                   VALUES (:run_id, :tenant_id, :user_id, :status, :spec_json, :report_json, :error, :created_at, :updated_at, :test_key)""",
                row,
            )
        return self._to_public(row)

    def update(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        report: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        fields = {"updated_at": now}
        if status is not None:
            fields["status"] = status
        if report is not None:
            fields["report_json"] = json.dumps(report)
        if error is not None:
            fields["error"] = error

        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        fields["run_id"] = run_id
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE api_runs SET {set_clause} WHERE run_id = :run_id", fields)

    def get(self, tenant_id: str, run_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM api_runs WHERE run_id = ? AND tenant_id = ?", (run_id, tenant_id)
            ).fetchone()
        return self._to_public(dict(row)) if row else None

    def list(self, tenant_id: str, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM api_runs WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
                (tenant_id, limit),
            ).fetchall()
        return [self._to_public(dict(r)) for r in rows]

    # -- Phase H1: trend analytics -------------------------------------------

    _TERMINAL_STATUSES = ("passed", "passed_with_healing", "failed", "escalated")

    def list_tracked_tests(self, tenant_id: str) -> list[str]:
        """Every distinct test_key with at least one completed run for this tenant."""
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT DISTINCT test_key FROM api_runs
                    WHERE tenant_id = ? AND test_key IS NOT NULL
                    AND status IN ({",".join("?" * len(self._TERMINAL_STATUSES))})""",
                (tenant_id, *self._TERMINAL_STATUSES),
            ).fetchall()
        return sorted(r["test_key"] for r in rows)

    def test_history(self, tenant_id: str, test_key: str, limit: int = 100) -> list[dict]:
        """
        Chronological (oldest-first) run history for one test_key --
        `aura`/dashboard "per-test history" (Phase G/H1 plan). Only
        terminal-status runs count (a still-`running`/`queued` row isn't a
        pass or fail yet).
        """
        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT run_id, status, created_at FROM api_runs
                    WHERE tenant_id = ? AND test_key = ?
                    AND status IN ({",".join("?" * len(self._TERMINAL_STATUSES))})
                    ORDER BY created_at ASC LIMIT ?""",
                (tenant_id, test_key, *self._TERMINAL_STATUSES, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def pass_rate_series(self, tenant_id: str, test_key: str, limit: int = 100) -> dict:
        """
        `aura`/dashboard "pass-rate over time" (Phase G/H1 plan): the full
        chronological history plus a running (cumulative) pass rate at
        each point, so a caller can plot a trend line without
        recomputing it itself. `passed` counts PASSED and
        PASSED_WITH_HEALING; FAILED/ESCALATED count against it.
        """
        history = self.test_history(tenant_id, test_key, limit=limit)
        series = []
        passed_so_far = 0
        for i, row in enumerate(history, start=1):
            if row["status"] in ("passed", "passed_with_healing"):
                passed_so_far += 1
            series.append(
                {
                    "run_id": row["run_id"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "cumulative_pass_rate": round(passed_so_far / i, 4),
                }
            )
        overall_pass_rate = round(passed_so_far / len(history), 4) if history else None
        return {"test_key": test_key, "total_runs": len(history), "overall_pass_rate": overall_pass_rate, "history": series}

    # -- Phase H2: flaky-test detection ---------------------------------------

    def get_flaky_candidates(self, tenant_id: str, min_runs: int = 3, min_transitions: int = 2) -> list[dict]:
        """
        A test is a flaky *candidate* -- never auto-quarantined, see
        orchestrator/quarantine_store.py -- when its recent history has at
        least `min_runs` completed runs AND its pass/fail outcome flips at
        least `min_transitions` times. A test that fails every single time
        isn't flaky, it's just broken (zero transitions); a test that
        passed 10 times then started failing consistently isn't flaky
        either (one transition) -- flakiness is specifically about
        instability, not a single regression.
        """
        candidates = []
        for test_key in self.list_tracked_tests(tenant_id):
            history = self.test_history(tenant_id, test_key, limit=min_runs * 20 or 100)
            if len(history) < min_runs:
                continue
            outcomes = [h["status"] in ("passed", "passed_with_healing") for h in history]
            transitions = sum(1 for a, b in zip(outcomes, outcomes[1:]) if a != b)
            if transitions >= min_transitions:
                passed = sum(outcomes)
                candidates.append(
                    {
                        "test_key": test_key,
                        "total_runs": len(history),
                        "transitions": transitions,
                        "pass_rate": round(passed / len(history), 4),
                    }
                )
        candidates.sort(key=lambda c: c["transitions"], reverse=True)
        return candidates

    @staticmethod
    def _to_public(row: dict[str, Any]) -> dict:
        return {
            "id": row["run_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "spec": json.loads(row["spec_json"]) if row.get("spec_json") else None,
            "report": json.loads(row["report_json"]) if row.get("report_json") else None,
            "error": row.get("error"),
        }


run_store = ApiRunStore()
