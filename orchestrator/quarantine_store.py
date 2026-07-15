"""
Quarantine store — orchestrator/quarantine_store.py (Phase H2).

Opt-in, human-decided quarantine list for flaky tests, used by
`aura execute --all` to skip known-flaky specs without deleting or
renaming their requirement docs. Deliberately NOT automatic: flakiness
detection (api/run_store.py::get_flaky_candidates, the API-surface
analytics built in the same phase) only ever *surfaces candidates* --
nothing in this codebase quarantines a test on its own. A human runs
`aura skills quarantine <test_id>` to act on that signal.

Backed by a small JSON file (not SQLite -- this is a short, rarely-
written list a person might reasonably want to open and read directly,
unlike the high-churn run-history data in api/run_store.py/orchestrator/
memory.py) under orchestrator/skills_store/, next to the skill library
it's conceptually a sibling of (both are "things AURA learned/was told
about a test/app," not per-run transient state).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from config.settings import settings


def _store_path() -> Path:
    return settings.skills_store_dir / "quarantine.json"


def _load() -> dict:
    path = _store_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def quarantine(test_id: str, reason: str | None = None) -> dict:
    """Adds (or updates) a quarantine entry for `test_id`. Idempotent."""
    data = _load()
    data[test_id] = {
        "reason": reason,
        "quarantined_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _save(data)
    return data[test_id]


def unquarantine(test_id: str) -> bool:
    """Removes a quarantine entry. Returns False if it wasn't quarantined."""
    data = _load()
    if test_id not in data:
        return False
    del data[test_id]
    _save(data)
    return True


def is_quarantined(test_id: str) -> bool:
    return test_id in _load()


def list_quarantined() -> dict:
    """Returns the full {test_id: {reason, quarantined_at}} mapping."""
    return _load()
