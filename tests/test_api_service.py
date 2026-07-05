"""
Phase 15 — API service layer tests.

Covers the pieces that were previously stubbed/hardcoded per STATUS.md:
- /auth/login issuing a real JWT against api/user_store.py
- POST /api/v1/test-runs/ actually executing via RunEngine.run_spec
  (a CAPABILITY_CHECK-only spec against FakeAdapter, so no display/
  network is required) instead of the old always-"passed" stub
- Persistence surviving a fresh ApiRunStore instance pointed at the
  same db file (simulating a process restart)
- /api/v1/adapters/status reflecting the real registry instead of a
  hardcoded dict

No existing test file covered api/ at all before this -- most of these
are the first tests for that surface.
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
    # Fresh, isolated user + run stores per test so seeding/order doesn't
    # depend on whatever's already on disk in this repo checkout.
    users_path = tmp_path / "users.json"
    monkeypatch.setattr("api.user_store.user_store", UserStore(path=users_path))
    monkeypatch.setattr("api.routers.auth.user_store", UserStore(path=users_path))

    run_db = tmp_path / "api_runs.db"
    fresh_store = ApiRunStore(db_path=run_db)
    monkeypatch.setattr("api.run_store.run_store", fresh_store)
    monkeypatch.setattr("api.routers.runs.run_store", fresh_store)

    return TestClient(app)


def _login(client) -> str:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "test-admin-password-123"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_login_rejects_bad_password(client):
    resp = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "wrong"}
    )
    assert resp.status_code == 401


def test_login_issues_working_token(client):
    token = _login(client)
    resp = client.get(
        "/api/v1/test-runs/", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_run_executes_via_run_engine_not_a_stub(client):
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    spec = {
        "test_name": "Fake capability smoke test",
        "steps": [
            {
                "action": "capability_check",
                "capability_type": "fake",
                "target": "smoke",
                "capability_params": {},
                "expected": {},
            }
        ],
    }
    resp = client.post("/api/v1/test-runs/", json=spec, headers=headers)
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]

    # BackgroundTasks run synchronously under TestClient before the
    # response context manager exits, so the run should already be
    # terminal (not stuck on "queued" the way the old stub never
    # advanced past "passed" without ever calling RunEngine).
    get_resp = client.get(f"/api/v1/test-runs/{run_id}", headers=headers)
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["status"] in ("passed", "passed_with_healing", "failed", "escalated")
    assert body["report"] is not None
    assert body["report"]["run_id"] == run_id


def test_create_run_rejects_invalid_action(client):
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post(
        "/api/v1/test-runs/",
        json={"test_name": "bad spec", "steps": [{"action": "not_a_real_action"}]},
        headers=headers,
    )
    assert resp.status_code == 422


def test_run_persists_across_store_instances(tmp_path):
    db_path = tmp_path / "persist.db"
    store_a = ApiRunStore(db_path=db_path)
    store_a.create("run-1", "tenant-a", "user-1", {"test_name": "x", "steps": []})
    store_a.update("run-1", status="passed", report={"run_id": "run-1"})

    # Simulates a process restart: new instance, same file on disk.
    store_b = ApiRunStore(db_path=db_path)
    record = store_b.get("tenant-a", "run-1")
    assert record is not None
    assert record["status"] == "passed"
    assert record["report"] == {"run_id": "run-1"}


def test_adapter_status_reflects_real_registry(client):
    token = _login(client)
    resp = client.get(
        "/api/v1/adapters/status", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    types = {a["capability_type"] for a in resp.json()["adapters"]}
    # These are the adapters registered in orchestrator/capability_adapter.py
    # as of Phase 15 -- if this drifts, the endpoint (not a hardcoded
    # dict) should be the thing that changes, and this test should be
    # updated to match reality rather than loosened to always pass.
    assert {"fake", "api", "database", "email", "file_system", "excel", "pdf_ocr", "cloud", "workflow"} <= types


def test_create_run_autonomous_mode_no_longer_crashes_on_spec_generation(client):
    # End-to-end regression test for the reported bug: an autonomous run
    # with a free-text prompt and no click/type/navigate phrasing used to
    # fail immediately at Planner.generate_spec with:
    #   "TestSpec must contain at least one step"
    # before a single action ever executed. After the fix, spec generation
    # must succeed; any later failure must come from step execution (e.g.
    # this sandbox having no real display to screenshot), never from spec
    # validation.
    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    spec = {
        "mode": "autonomous",
        "test_name": "Auto smoke",
        "target": "https://example.com",
        "prompt": "check homepage loads",
    }
    resp = client.post("/api/v1/test-runs/", json=spec, headers=headers)
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]

    get_resp = client.get(f"/api/v1/test-runs/{run_id}", headers=headers)
    assert get_resp.status_code == 200
    body = get_resp.json()
    if body["status"] == "failed":
        assert "TestSpec must contain at least one step" not in (body.get("error") or "")
        assert "Planner.generate_spec" not in (body.get("error") or "")


def test_create_run_autonomous_full_exploration_uses_ui_audit_engine(client, monkeypatch):
    # Regression test: previously `mode: "autonomous"` on the web API
    # *always* went through Planner.generate_spec, and the real
    # click-every-nav/hero/footer/body-element engine
    # (orchestrator/ui_audit_runner.run_exploration) was only reachable
    # from `aura explore` on the CLI. `full_exploration: true` should
    # route to that engine instead, and the resulting report should
    # reflect a UI-audit shape (checked element counts / broken list),
    # not a spec/step-based RunReport.
    import api.routers.runs as runs_module
    from orchestrator.ui_audit_runner import ClickCheckResult, UIAuditReport

    def fake_run_exploration(provider, run_id, max_elements=25, requirement_prompt=None):
        return UIAuditReport(
            has_nav=True,
            has_hero=False,
            has_footer=True,
            checked=[
                ClickCheckResult(label="Home", band="nav", clicked=True, state_changed=True),
                ClickCheckResult(label="Contact", band="footer", clicked=True, state_changed=False),
            ],
            page_issues=[],
        )

    monkeypatch.setattr(runs_module, "execute_full_exploration_run", runs_module.execute_full_exploration_run)
    monkeypatch.setattr("orchestrator.ui_audit_runner.run_exploration", fake_run_exploration)
    monkeypatch.setattr("runtime.hooks.browser.open_url", lambda *a, **k: None)
    monkeypatch.setattr("runtime.hooks.capture.capture_screenshot", lambda rid, idx: "unused.png")

    token = _login(client)
    headers = {"Authorization": f"Bearer {token}"}

    spec = {
        "mode": "autonomous",
        "test_name": "Full explore",
        "target": "https://example.com",
        "full_exploration": True,
    }
    resp = client.post("/api/v1/test-runs/", json=spec, headers=headers)
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]

    get_resp = client.get(f"/api/v1/test-runs/{run_id}", headers=headers)
    body = get_resp.json()
    assert body["status"] == "failed"  # one element had no visible change after click
    report = body["report"]
    assert report["mode"] == "full_exploration"
    assert report["total_elements_checked"] == 2
    assert len(report["possibly_broken"]) == 1
    assert report["possibly_broken"][0]["label"] == "Contact"
