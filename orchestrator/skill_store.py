"""
Skill library — orchestrator/skills_store/skills.db

Persists SkillRecord objects produced by Planner.diagnose after a
successful self-heal, and lets the Vision agent look up a likely fix
*before* attempting a step, via similarity search over failure_signature
text. No embedding model / network call required — uses difflib's
SequenceMatcher, which is fine at the scale of a local skill library
(tens to low-thousands of records) and keeps the whole system offline
(decisions.md D-002).

Also implements agentskills.io-compatible JSON export/import so a skill
pack learned against one app can be shared/reused (APPFLOW.md §2.9).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from difflib import SequenceMatcher
from pathlib import Path

from config.settings import settings
from orchestrator.schemas import FixType, SkillRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    skill_id TEXT PRIMARY KEY,
    failure_signature TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    proposed_fix TEXT NOT NULL,
    fix_type TEXT NOT NULL,
    confidence REAL NOT NULL,
    applied_count INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    app_id TEXT
);
"""


class SkillStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (settings.skills_store_dir / "skills.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # -- writes ------------------------------------------------------------

    def save(self, skill: SkillRecord, app_id: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO skills (skill_id, failure_signature, root_cause, proposed_fix,
                                     fix_type, confidence, applied_count, created_by, timestamp, app_id)
                VALUES (:skill_id, :failure_signature, :root_cause, :proposed_fix,
                        :fix_type, :confidence, :applied_count, :created_by, :timestamp, :app_id)
                ON CONFLICT(skill_id) DO UPDATE SET
                    failure_signature=excluded.failure_signature,
                    root_cause=excluded.root_cause,
                    proposed_fix=excluded.proposed_fix,
                    fix_type=excluded.fix_type,
                    confidence=excluded.confidence,
                    applied_count=excluded.applied_count,
                    timestamp=excluded.timestamp,
                    app_id=excluded.app_id
                """,
                {
                    "skill_id": skill.skill_id,
                    "failure_signature": skill.failure_signature,
                    "root_cause": skill.root_cause,
                    "proposed_fix": skill.proposed_fix,
                    "fix_type": skill.fix_type.value,
                    "confidence": skill.confidence,
                    "applied_count": skill.applied_count,
                    "created_by": skill.created_by,
                    "timestamp": skill.timestamp.isoformat(),
                    "app_id": app_id,
                },
            )

    def delete(self, skill_id: str) -> bool:
        """Removes a skill (e.g. the user rejected a healed-step diff in the
        TUI — APPFLOW.md §2.5). Returns True if a row was actually deleted."""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM skills WHERE skill_id = ?", (skill_id,))
            return cur.rowcount > 0

    def increment_applied(self, skill_id: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE skills SET applied_count = applied_count + 1 WHERE skill_id = ?", (skill_id,))

    # -- reads ---------------------------------------------------------------

    def get(self, skill_id: str) -> SkillRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM skills WHERE skill_id = ?", (skill_id,)).fetchone()
        return self._row_to_record(row) if row else None

    def all(self, app_id: str | None = None) -> list[SkillRecord]:
        with self._connect() as conn:
            if app_id:
                rows = conn.execute("SELECT * FROM skills WHERE app_id = ?", (app_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM skills").fetchall()
        return [self._row_to_record(r) for r in rows]

    def find_similar(self, failure_signature: str, top_k: int = 3, min_ratio: float = 0.5) -> list[tuple[SkillRecord, float]]:
        """
        Returns up to top_k (SkillRecord, similarity_ratio) pairs, ranked
        descending by similarity, filtered to ratio >= min_ratio.
        """
        candidates = self.all()
        scored = [
            (rec, SequenceMatcher(None, failure_signature.lower(), rec.failure_signature.lower()).ratio())
            for rec in candidates
        ]
        scored = [pair for pair in scored if pair[1] >= min_ratio]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:top_k]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> SkillRecord:
        return SkillRecord(
            skill_id=row["skill_id"],
            failure_signature=row["failure_signature"],
            root_cause=row["root_cause"],
            proposed_fix=row["proposed_fix"],
            fix_type=FixType(row["fix_type"]),
            confidence=row["confidence"],
            applied_count=row["applied_count"],
            created_by=row["created_by"],
            timestamp=row["timestamp"],
        )

    # -- agentskills.io-compatible export/import ------------------------------

    def export_skills(self, app_id: str | None = None) -> str:
        records = self.all(app_id=app_id)
        payload = {
            "format": "agentskills.io/v1",
            "app_id": app_id,
            "skills": [json.loads(r.model_dump_json()) for r in records],
        }
        return json.dumps(payload, indent=2)

    def export_to_file(self, path: Path, app_id: str | None = None) -> Path:
        path.write_text(self.export_skills(app_id=app_id), encoding="utf-8")
        return path

    def import_skills(self, payload_json: str, app_id: str | None = None) -> int:
        payload = json.loads(payload_json)
        count = 0
        for raw in payload.get("skills", []):
            record = SkillRecord.model_validate(raw)
            self.save(record, app_id=app_id)
            count += 1
        return count

    def import_from_file(self, path: Path, app_id: str | None = None) -> int:
        return self.import_skills(path.read_text(encoding="utf-8"), app_id=app_id)

    # -- diff (feature roadmap: review what self-healing "learned" between two points) --

    @staticmethod
    def diff_snapshots(before_json: str, after_json: str) -> dict:
        """
        Compares two exported skill-pack JSON snapshots (see export_skills)
        and reports what changed between them: skills added, skills removed,
        and skills present in both but whose confidence/applied_count/
        proposed_fix changed. Lets a team review what the self-healer
        learned since the last checkpoint before trusting it in CI, the
        same way you'd review a migration diff.

        Pure function over two JSON strings (no DB access) so it can be
        used to compare exports pulled from different machines/points in
        time, not just two states of the same local skills.db.
        """
        before = {s["skill_id"]: s for s in json.loads(before_json).get("skills", [])}
        after = {s["skill_id"]: s for s in json.loads(after_json).get("skills", [])}

        added = [after[sid] for sid in after.keys() - before.keys()]
        removed = [before[sid] for sid in before.keys() - after.keys()]

        changed = []
        tracked_fields = ("confidence", "applied_count", "proposed_fix", "fix_type")
        for sid in before.keys() & after.keys():
            b, a = before[sid], after[sid]
            field_changes = {
                field: {"before": b.get(field), "after": a.get(field)}
                for field in tracked_fields
                if b.get(field) != a.get(field)
            }
            if field_changes:
                changed.append({"skill_id": sid, "changes": field_changes})

        return {
            "added": sorted(added, key=lambda s: s["skill_id"]),
            "removed": sorted(removed, key=lambda s: s["skill_id"]),
            "changed": sorted(changed, key=lambda c: c["skill_id"]),
            "summary": {
                "added_count": len(added),
                "removed_count": len(removed),
                "changed_count": len(changed),
                "unchanged_count": len(before.keys() & after.keys()) - len(changed),
            },
        }
