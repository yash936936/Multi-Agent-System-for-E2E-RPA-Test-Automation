"""
Data cache — runtime/data_cache/<test_id>.json

Generated synthetic data is cached per test_id and reused across runs
unless a refresh is explicitly requested (TRD §2.4: data synthesis is
invoked once per test, not once per run, to keep repeated runs
comparable/debuggable rather than fighting a new random dataset every time).
"""
from __future__ import annotations

import json
from pathlib import Path

from config.settings import settings


def _cache_path(test_id: str) -> Path:
    settings.data_cache_dir.mkdir(parents=True, exist_ok=True)
    safe_id = test_id.replace("/", "_")
    return settings.data_cache_dir / f"{safe_id}.json"


def load_cached(test_id: str) -> dict | None:
    path = _cache_path(test_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def save_cache(test_id: str, values: dict) -> Path:
    path = _cache_path(test_id)
    path.write_text(json.dumps(values, indent=2), encoding="utf-8")
    return path


def clear_cache(test_id: str) -> bool:
    path = _cache_path(test_id)
    if path.exists():
        path.unlink()
        return True
    return False
