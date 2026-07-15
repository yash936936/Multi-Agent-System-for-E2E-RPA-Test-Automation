"""
Tests for Phase H1 (trend analytics) and H2 (flaky-candidate detection)
additions to api/run_store.py -- against a real on-disk SQLite file, not a
mock, so a schema/migration bug would actually surface.
"""
from __future__ import annotations

from api.run_store import ApiRunStore

TENANT = "tenant-a"


def _seed_run(store: ApiRunStore, test_id: str, status: str, user_id: str = "u1"):
    import uuid

    run_id = str(uuid.uuid4())
    store.create(run_id, TENANT, user_id, {"test_id": test_id})
    store.update(run_id, status=status)
    return run_id


def test_migration_adds_test_key_column_to_a_pre_existing_db(tmp_path):
    """Simulates a DB created before Phase H1 (no test_key column) and
    confirms opening it with the new code migrates it cleanly."""
    import sqlite3

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE api_runs (
            run_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, user_id TEXT NOT NULL,
            status TEXT NOT NULL, spec_json TEXT NOT NULL, report_json TEXT,
            error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()

    store = ApiRunStore(db_path=db_path)
    # Should not raise, and the column should now exist.
    _seed_run(store, "TC-LEGACY-001", "passed")
    history = store.test_history(TENANT, "TC-LEGACY-001")
    assert len(history) == 1


def test_test_key_extracted_from_test_id_or_test_name(tmp_path):
    store = ApiRunStore(db_path=tmp_path / "a.db")
    _seed_run(store, "TC-ALPHA-001", "passed")
    import uuid

    run_id = str(uuid.uuid4())
    store.create(run_id, TENANT, "u1", {"test_name": "Autonomous smoke run"})
    store.update(run_id, status="passed")

    tracked = store.list_tracked_tests(TENANT)
    assert "TC-ALPHA-001" in tracked
    assert "Autonomous smoke run" in tracked


def test_untracked_run_with_no_test_id_or_name_is_excluded(tmp_path):
    store = ApiRunStore(db_path=tmp_path / "a.db")
    import uuid

    run_id = str(uuid.uuid4())
    store.create(run_id, TENANT, "u1", {})  # no test_id, no test_name
    store.update(run_id, status="passed")
    assert store.list_tracked_tests(TENANT) == []


def test_history_only_includes_terminal_statuses_in_order(tmp_path):
    store = ApiRunStore(db_path=tmp_path / "a.db")
    _seed_run(store, "TC-A-001", "passed")
    _seed_run(store, "TC-A-001", "failed")
    # A still-running/queued run shouldn't show up as a pass or fail yet.
    import uuid

    run_id = str(uuid.uuid4())
    store.create(run_id, TENANT, "u1", {"test_id": "TC-A-001"})
    store.update(run_id, status="running")

    history = store.test_history(TENANT, "TC-A-001")
    assert [h["status"] for h in history] == ["passed", "failed"]


def test_pass_rate_series_computes_cumulative_rate(tmp_path):
    store = ApiRunStore(db_path=tmp_path / "a.db")
    _seed_run(store, "TC-B-001", "passed")
    _seed_run(store, "TC-B-001", "passed")
    _seed_run(store, "TC-B-001", "failed")

    result = store.pass_rate_series(TENANT, "TC-B-001")
    assert result["total_runs"] == 3
    assert result["overall_pass_rate"] == round(2 / 3, 4)
    rates = [pt["cumulative_pass_rate"] for pt in result["history"]]
    assert rates == [1.0, 1.0, round(2 / 3, 4)]


def test_pass_rate_series_empty_history_returns_none_rate(tmp_path):
    store = ApiRunStore(db_path=tmp_path / "a.db")
    result = store.pass_rate_series(TENANT, "TC-NEVER-RUN-001")
    assert result["total_runs"] == 0
    assert result["overall_pass_rate"] is None
    assert result["history"] == []


def test_flaky_candidate_detected_on_alternating_pass_fail(tmp_path):
    store = ApiRunStore(db_path=tmp_path / "a.db")
    for status in ("passed", "failed", "passed", "failed", "passed"):
        _seed_run(store, "TC-FLAKY-001", status)

    candidates = store.get_flaky_candidates(TENANT, min_runs=3, min_transitions=2)
    keys = [c["test_key"] for c in candidates]
    assert "TC-FLAKY-001" in keys
    entry = next(c for c in candidates if c["test_key"] == "TC-FLAKY-001")
    assert entry["transitions"] == 4


def test_consistently_failing_test_is_not_flaky(tmp_path):
    store = ApiRunStore(db_path=tmp_path / "a.db")
    for _ in range(5):
        _seed_run(store, "TC-BROKEN-001", "failed")

    candidates = store.get_flaky_candidates(TENANT, min_runs=3, min_transitions=2)
    assert "TC-BROKEN-001" not in [c["test_key"] for c in candidates]


def test_single_regression_is_not_flaky(tmp_path):
    store = ApiRunStore(db_path=tmp_path / "a.db")
    for status in ("passed", "passed", "passed", "failed", "failed"):
        _seed_run(store, "TC-REGRESSED-001", status)

    candidates = store.get_flaky_candidates(TENANT, min_runs=3, min_transitions=2)
    assert "TC-REGRESSED-001" not in [c["test_key"] for c in candidates]


def test_below_min_runs_threshold_is_excluded(tmp_path):
    store = ApiRunStore(db_path=tmp_path / "a.db")
    _seed_run(store, "TC-NEW-001", "passed")
    _seed_run(store, "TC-NEW-001", "failed")

    candidates = store.get_flaky_candidates(TENANT, min_runs=3, min_transitions=1)
    assert "TC-NEW-001" not in [c["test_key"] for c in candidates]


def test_tenant_isolation_in_analytics(tmp_path):
    store = ApiRunStore(db_path=tmp_path / "a.db")
    _seed_run(store, "TC-SHARED-001", "passed")
    import uuid

    run_id = str(uuid.uuid4())
    store.create(run_id, "tenant-b", "u2", {"test_id": "TC-SHARED-001"})
    store.update(run_id, status="failed")

    history_a = store.test_history(TENANT, "TC-SHARED-001")
    history_b = store.test_history("tenant-b", "TC-SHARED-001")
    assert [h["status"] for h in history_a] == ["passed"]
    assert [h["status"] for h in history_b] == ["failed"]
