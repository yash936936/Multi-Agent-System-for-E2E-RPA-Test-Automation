"""
API-level tests for Phase H1 (trend analytics) / H2 (flaky candidates)
routes in api/routers/runs.py -- confirms the routes are actually wired
in (not just present as ApiRunStore methods) and that the "/analytics/..."
paths aren't swallowed by the "/{run_id}" catch-all registered after them.
"""
from __future__ import annotations

import os

os.environ.setdefault("AURA_ADMIN_PASSWORD", "test-admin-password-123")

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.run_store import ApiRunStore
from api.user_store import UserStore


@pytest.fixture()
def client(tmp_path, monkeypatch):
    users_path = tmp_path / "users.json"
    monkeypatch.setattr("api.user_store.user_store", UserStore(path=users_path))
    monkeypatch.setattr("api.routers.auth.user_store", UserStore(path=users_path))

    run_db = tmp_path / "api_runs.db"
    fresh_store = ApiRunStore(db_path=run_db)
    monkeypatch.setattr("api.run_store.run_store", fresh_store)
    monkeypatch.setattr("api.routers.runs.run_store", fresh_store)

    return TestClient(app), fresh_store


def _login(client) -> str:
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "test-admin-password-123"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth_headers(client):
    return {"Authorization": f"Bearer {_login(client)}"}


def test_list_tracked_tests_empty_initially(client):
    c, _ = client
    resp = c.get("/api/v1/test-runs/analytics/tests", headers=_auth_headers(c))
    assert resp.status_code == 200
    assert resp.json() == {"tests": []}


def test_trend_route_not_swallowed_by_run_id_catchall(client):
    """
    Regression guard: /analytics/tests/{key} must resolve to the analytics
    handler, not get_run(run_id="analytics") -- this only works because
    the analytics routes are registered before the catch-all in
    api/routers/runs.py.
    """
    c, store = client
    store.create("run-1", "default", "admin", {"test_id": "TC-TREND-001"})
    store.update("run-1", status="passed")

    resp = c.get("/api/v1/test-runs/analytics/tests/TC-TREND-001", headers=_auth_headers(c))
    assert resp.status_code == 200
    body = resp.json()
    assert body["test_key"] == "TC-TREND-001"
    assert body["total_runs"] == 1
    assert body["overall_pass_rate"] == 1.0


def test_trend_route_404s_for_unknown_test_key(client):
    c, _ = client
    resp = c.get("/api/v1/test-runs/analytics/tests/TC-NEVER-SEEN-001", headers=_auth_headers(c))
    assert resp.status_code == 404


def test_flaky_route_surfaces_alternating_test(client):
    c, store = client
    for i, status in enumerate(("passed", "failed", "passed", "failed")):
        run_id = f"run-flaky-{i}"
        store.create(run_id, "default", "admin", {"test_id": "TC-FLAKY-001"})
        store.update(run_id, status=status)

    resp = c.get("/api/v1/test-runs/analytics/flaky?min_runs=3&min_transitions=2", headers=_auth_headers(c))
    assert resp.status_code == 200
    keys = [cand["test_key"] for cand in resp.json()["candidates"]]
    assert "TC-FLAKY-001" in keys


def test_analytics_routes_require_auth(client):
    c, _ = client
    resp = c.get("/api/v1/test-runs/analytics/tests")
    assert resp.status_code in (401, 403)


# ---- merged from test_run_store_analytics.py (store-level, real sqlite) ----
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
