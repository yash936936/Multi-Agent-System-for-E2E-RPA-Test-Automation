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


class ApiRunStore:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or (settings.memory_dir / "api_runs.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
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
        }
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO api_runs
                   (run_id, tenant_id, user_id, status, spec_json, report_json, error, created_at, updated_at)
                   VALUES (:run_id, :tenant_id, :user_id, :status, :spec_json, :report_json, :error, :created_at, :updated_at)""",
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
