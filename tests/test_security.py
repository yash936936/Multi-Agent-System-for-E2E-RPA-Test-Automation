"""
Direct unit tests for api/security.py::user_can_access_project (Phase K,
decisions.md D-032) -- a pure function, cheap to test in isolation on top
of the full HTTP-level coverage in tests/test_project_tag_permissions.py.
"""
from __future__ import annotations

from api.security import TokenPayload, user_can_access_project


def _user(role="executor", allowed_project_tags=None) -> TokenPayload:
    return TokenPayload(tenant_id="default", user_id="u1", role=role, allowed_project_tags=allowed_project_tags)


def test_admin_bypasses_every_restriction():
    admin = _user(role="admin", allowed_project_tags=["marketing"])
    assert user_can_access_project(admin, "finance") is True
    assert user_can_access_project(admin, None) is True


def test_untagged_spec_always_accessible():
    restricted = _user(allowed_project_tags=["marketing"])
    assert user_can_access_project(restricted, None) is True


def test_unrestricted_user_can_access_any_tag():
    unrestricted = _user(allowed_project_tags=None)
    assert user_can_access_project(unrestricted, "finance") is True
    assert user_can_access_project(unrestricted, "anything-at-all") is True


def test_restricted_user_denied_tag_not_in_list():
    restricted = _user(allowed_project_tags=["marketing"])
    assert user_can_access_project(restricted, "finance") is False


def test_restricted_user_allowed_tag_in_list():
    restricted = _user(allowed_project_tags=["marketing", "finance"])
    assert user_can_access_project(restricted, "finance") is True


def test_empty_list_means_no_access_to_any_tag_at_the_function_level():
    # Deliberately distinct from the API-level normalization test in
    # tests/test_project_tag_permissions.py, which confirms the *router*
    # normalizes an incoming [] to None before this function ever sees
    # it. At the raw function level, an actual empty list correctly means
    # "no tags allowed," not "unrestricted" -- the normalization is the
    # router's job (a deliberate API-usability choice), not this
    # function's, and this test guards against someone "fixing" that
    # distinction away by mistake.
    restricted = _user(allowed_project_tags=[])
    assert user_can_access_project(restricted, "finance") is False
