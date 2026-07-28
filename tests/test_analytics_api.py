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
