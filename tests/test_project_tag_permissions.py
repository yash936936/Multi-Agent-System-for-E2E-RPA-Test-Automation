"""
Phase K — project-tag permission matrix tests (decisions.md D-032).

Same client/user-store/run-store fixture pattern as test_api_service.py --
real FastAPI TestClient against a real (isolated, tmp_path-scoped) user
store and run store, not mocked-away auth.
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
    monkeypatch.setattr("api.routers.users.user_store", UserStore(path=users_path))

    run_db = tmp_path / "api_runs.db"
    fresh_store = ApiRunStore(db_path=run_db)
    monkeypatch.setattr("api.run_store.run_store", fresh_store)
    monkeypatch.setattr("api.routers.runs.run_store", fresh_store)

    return TestClient(app)


def _login(client, username="admin", password="test-admin-password-123") -> str:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _fake_check_spec(project_tag=None) -> dict:
    spec = {
        "test_name": "Fake capability smoke test",
        "steps": [{
            "action": "capability_check", "capability_type": "fake",
            "target": "smoke", "capability_params": {}, "expected": {},
        }],
    }
    if project_tag is not None:
        spec["project_tag"] = project_tag
    return spec


def test_untagged_spec_is_accessible_to_any_authenticated_user(client):
    # Confirms zero behavior change for every spec that doesn't use this
    # feature -- the entire pre-existing test suite's specs are untagged.
    token = _login(client)
    resp = client.post(
        "/api/v1/test-runs/", json=_fake_check_spec(), headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text


def test_admin_always_passes_regardless_of_tag(client):
    token = _login(client)  # admin
    resp = client.post(
        "/api/v1/test-runs/", json=_fake_check_spec(project_tag="finance"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text


def test_user_with_no_restriction_can_access_any_tag(client):
    signup = client.post("/api/v1/auth/signup", json={"username": "casey", "password": "casey-password-1"})
    assert signup.status_code == 200, signup.text
    casey_token = signup.json()["access_token"]

    resp = client.post(
        "/api/v1/test-runs/", json=_fake_check_spec(project_tag="finance"),
        headers={"Authorization": f"Bearer {casey_token}"},
    )
    assert resp.status_code == 200, resp.text


def test_restricted_user_is_denied_a_tag_not_in_their_list(client):
    admin_token = _login(client)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    signup = client.post("/api/v1/auth/signup", json={"username": "casey", "password": "casey-password-1"})
    assert signup.status_code == 200

    restrict = client.put(
        "/api/v1/users/casey/project-tags",
        json={"allowed_project_tags": ["marketing"]},
        headers=admin_headers,
    )
    assert restrict.status_code == 200, restrict.text
    assert restrict.json() == {"username": "casey", "allowed_project_tags": ["marketing"]}

    # casey's existing token was issued before the restriction -- log in
    # again to get a token that actually carries the new restriction
    # (matches how role/tenant changes already behave: this system has no
    # live token revocation, a token is a snapshot at issuance time).
    fresh_login = client.post("/api/v1/auth/login", json={"username": "casey", "password": "casey-password-1"})
    casey_token = fresh_login.json()["access_token"]

    denied = client.post(
        "/api/v1/test-runs/", json=_fake_check_spec(project_tag="finance"),
        headers={"Authorization": f"Bearer {casey_token}"},
    )
    assert denied.status_code == 403
    assert "finance" in denied.json()["detail"]

    allowed = client.post(
        "/api/v1/test-runs/", json=_fake_check_spec(project_tag="marketing"),
        headers={"Authorization": f"Bearer {casey_token}"},
    )
    assert allowed.status_code == 200, allowed.text


def test_restricted_user_can_still_access_untagged_specs(client):
    admin_token = _login(client)
    client.post("/api/v1/auth/signup", json={"username": "casey", "password": "casey-password-1"})
    client.put(
        "/api/v1/users/casey/project-tags",
        json={"allowed_project_tags": ["marketing"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    casey_token = _login(client, "casey", "casey-password-1")

    resp = client.post(
        "/api/v1/test-runs/", json=_fake_check_spec(), headers={"Authorization": f"Bearer {casey_token}"}
    )
    assert resp.status_code == 200, resp.text


def test_non_admin_cannot_set_project_tags(client):
    client.post("/api/v1/auth/signup", json={"username": "casey", "password": "casey-password-1"})
    casey_token = _login(client, "casey", "casey-password-1")

    resp = client.put(
        "/api/v1/users/someone-else/project-tags",
        json={"allowed_project_tags": ["finance"]},
        headers={"Authorization": f"Bearer {casey_token}"},
    )
    assert resp.status_code == 403


def test_setting_tags_on_nonexistent_user_returns_404(client):
    admin_token = _login(client)
    resp = client.put(
        "/api/v1/users/nobody-here/project-tags",
        json={"allowed_project_tags": ["finance"]},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 404


def test_empty_tag_list_normalizes_to_unrestricted(client):
    # An explicit [] should mean "unrestricted" (same as None), not
    # "can access nothing" -- the latter would be a confusing footgun for
    # an admin who meant to clear a restriction.
    admin_token = _login(client)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    client.post("/api/v1/auth/signup", json={"username": "casey", "password": "casey-password-1"})
    client.put("/api/v1/users/casey/project-tags", json={"allowed_project_tags": []}, headers=admin_headers)
    casey_token = _login(client, "casey", "casey-password-1")

    resp = client.post(
        "/api/v1/test-runs/", json=_fake_check_spec(project_tag="anything"),
        headers={"Authorization": f"Bearer {casey_token}"},
    )
    assert resp.status_code == 200, resp.text


def test_list_runs_omits_inaccessible_tagged_runs_but_keeps_untagged_ones(client):
    admin_token = _login(client)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    client.post("/api/v1/test-runs/", json=_fake_check_spec(project_tag="finance"), headers=admin_headers)
    client.post("/api/v1/test-runs/", json=_fake_check_spec(), headers=admin_headers)  # untagged

    client.post("/api/v1/auth/signup", json={"username": "casey", "password": "casey-password-1"})
    client.put(
        "/api/v1/users/casey/project-tags", json={"allowed_project_tags": ["marketing"]}, headers=admin_headers
    )
    casey_token = _login(client, "casey", "casey-password-1")

    listing = client.get("/api/v1/test-runs/", headers={"Authorization": f"Bearer {casey_token}"})
    assert listing.status_code == 200
    tags_seen = [(r.get("spec") or {}).get("project_tag") for r in listing.json()]
    assert "finance" not in tags_seen
    assert None in tags_seen  # the untagged run is still visible


def test_get_run_returns_not_found_not_forbidden_for_inaccessible_tag(client):
    # Deliberately 404, not 403 -- see api/routers/runs.py's comment on
    # get_run: don't confirm to an unauthorized caller that the run exists.
    admin_token = _login(client)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    created = client.post(
        "/api/v1/test-runs/", json=_fake_check_spec(project_tag="finance"), headers=admin_headers
    )
    run_id = created.json()["run_id"]

    client.post("/api/v1/auth/signup", json={"username": "casey", "password": "casey-password-1"})
    client.put(
        "/api/v1/users/casey/project-tags", json={"allowed_project_tags": ["marketing"]}, headers=admin_headers
    )
    casey_token = _login(client, "casey", "casey-password-1")

    resp = client.get(f"/api/v1/test-runs/{run_id}", headers={"Authorization": f"Bearer {casey_token}"})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Run not found or access denied"
