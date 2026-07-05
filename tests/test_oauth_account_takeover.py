from __future__ import annotations

import os

import pytest

from api.user_store import UserStore


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("AURA_ADMIN_PASSWORD", "seed-password-not-used-here")
    return UserStore(path=tmp_path / "users.json")


def test_oauth_login_cannot_take_over_existing_local_account(store):
    # A local admin account named "yash" exists.
    store.create_user(username="yash", password="SuperSecret123!", tenant_id="default", role="admin")

    # An attacker controls a GitHub account whose username is *also* "yash"
    # (GitHub usernames are attacker-choosable) and completes the OAuth
    # flow. This must NOT return the local admin's tenant/role.
    result = store.find_or_create_oauth_user(username="yash", provider="github")

    assert result["role"] != "admin"
    assert result["user_id"] != "yash"  # namespaced key, not the bare local username
    assert result["user_id"] == "github:yash"

    # And the local "yash" password account must be completely unaffected.
    local = store.verify("yash", "SuperSecret123!")
    assert local is not None
    assert local["role"] == "admin"


def test_oauth_users_from_different_providers_with_same_username_are_distinct(store):
    gh = store.find_or_create_oauth_user(username="alex", provider="github")
    gg = store.find_or_create_oauth_user(username="alex", provider="google")
    assert gh["user_id"] != gg["user_id"]


def test_repeat_oauth_login_returns_the_same_identity(store):
    first = store.find_or_create_oauth_user(username="alex", provider="github")
    second = store.find_or_create_oauth_user(username="alex", provider="github")
    assert first == second


def test_local_signup_cannot_squat_an_oauth_namespaced_key(monkeypatch, tmp_path):
    # Reverse-direction attack: registering a local account literally named
    # like a future OAuth key (e.g. "github:victim") must be rejected by
    # the signup endpoint. Without this, an attacker could pre-create
    # "github:victim" locally and be handed control of whatever account
    # the real GitHub user "victim" logs into later (find_or_create_oauth_user
    # would find that pre-existing record and treat it as already-linked).
    os.environ.setdefault("AURA_ADMIN_PASSWORD", "test-admin-password-123")
    from fastapi.testclient import TestClient

    from api.main import app
    from api.user_store import UserStore

    users_path = tmp_path / "users.json"
    monkeypatch.setattr("api.user_store.user_store", UserStore(path=users_path))
    monkeypatch.setattr("api.routers.auth.user_store", UserStore(path=users_path))
    client = TestClient(app)

    resp = client.post(
        "/api/v1/auth/signup",
        json={"username": "github:victim", "password": "SomePassword123!"},
    )
    assert resp.status_code == 422
