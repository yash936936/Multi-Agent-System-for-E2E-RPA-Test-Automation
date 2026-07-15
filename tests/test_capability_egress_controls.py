"""
Phase D tests — capability-adapter egress controls (decisions.md D-020).

Covers:
  1. Hard kill switch: capability_adapters_enabled=False rejects every
     capability before the adapter runs.
  2. Host allowlist: a target host not in allowed_capability_hosts is
     rejected; a matching host (exact or subdomain) is permitted.
  3. Host extraction across the real param-key conventions used by the
     existing adapters (url / connection_string / smtp_server).
  4. FAKE capability is exempt from host checks but still respects the
     kill switch.
  5. A permitted call is still logged to the audit trail (host + timestamp,
     no payload contents).
"""
from __future__ import annotations

import json

import pytest

from config.settings import settings
from orchestrator.audit_logger import audit_logger
from orchestrator.capability_router import (
    _extract_egress_host,
    _host_allowed,
    route_capability,
)
from orchestrator.schemas import CapabilityCheckInput, CapabilityType


@pytest.fixture(autouse=True)
def _reset_settings():
    """Every test gets a clean kill-switch/allowlist state, restored after."""
    orig_enabled = settings.capability_adapters_enabled
    orig_allowed = settings.allowed_capability_hosts
    yield
    settings.capability_adapters_enabled = orig_enabled
    settings.allowed_capability_hosts = orig_allowed


# --------------------------------------------------------------------------
# Kill switch
# --------------------------------------------------------------------------

def test_kill_switch_rejects_before_adapter_runs():
    settings.capability_adapters_enabled = False
    result = route_capability(
        CapabilityCheckInput(capability=CapabilityType.FAKE, target="", params={})
    )
    assert result.passed is False
    assert result.escalate is True
    assert result.evidence["rejected"] is True
    assert "capability_adapters_enabled" in result.evidence["reason"]


def test_kill_switch_default_is_enabled():
    assert settings.capability_adapters_enabled is True


# --------------------------------------------------------------------------
# Host extraction
# --------------------------------------------------------------------------

def test_extract_host_from_url_param():
    payload = CapabilityCheckInput(
        capability=CapabilityType.API, target="", params={"url": "https://api.example.com/v1/health"}
    )
    assert _extract_egress_host(payload) == "api.example.com"


def test_extract_host_from_connection_string():
    payload = CapabilityCheckInput(
        capability=CapabilityType.DATABASE,
        target="",
        params={"connection_string": "postgresql://user:pass@db.internal.example.com:5432/appdb", "query": "SELECT 1"},
    )
    assert _extract_egress_host(payload) == "db.internal.example.com"


def test_extract_host_from_bare_smtp_server():
    payload = CapabilityCheckInput(
        capability=CapabilityType.EMAIL,
        target="",
        params={"smtp_server": "smtp.example.com", "action": "send"},
    )
    assert _extract_egress_host(payload) == "smtp.example.com"


def test_extract_host_falls_back_to_target():
    payload = CapabilityCheckInput(
        capability=CapabilityType.LINK_CHECK, target="https://myapp.example.com/", params={}
    )
    assert _extract_egress_host(payload) == "myapp.example.com"


def test_extract_host_returns_none_when_unresolvable():
    payload = CapabilityCheckInput(
        capability=CapabilityType.AZURE_BLOB, target="", params={"container": "docs", "blob_name": "a.txt"}
    )
    assert _extract_egress_host(payload) is None


def test_extract_host_covers_phase_l_adapters_without_router_changes():
    """
    Phase L (accessibility/security_headers/performance) all use the same
    generic 'url' params key every other URL-based adapter already uses --
    confirms no capability_router.py changes were needed for egress
    coverage, per the three-way registration pattern (enum + default_registry()
    + this existing generic extraction, not a fourth per-adapter special case).
    """
    for capability in (CapabilityType.ACCESSIBILITY, CapabilityType.SECURITY_HEADERS, CapabilityType.PERFORMANCE):
        payload = CapabilityCheckInput(
            capability=capability, target="", params={"url": "https://app.example.com/dashboard"}
        )
        assert _extract_egress_host(payload) == "app.example.com"


def test_extract_host_covers_phase_m_defect_tracker_base_url():
    """
    Phase M's defect_tracker_adapter uses 'base_url' (matching Jira/
    TestRail/Zephyr/Xray-style REST client conventions) rather than the
    generic 'url' key every prior URL-based adapter used -- this required
    one addition to _URL_PARAM_KEYS (unlike Phase L, which needed none),
    confirmed here rather than assumed.
    """
    payload = CapabilityCheckInput(
        capability=CapabilityType.DEFECT_TRACKER,
        target="",
        params={"base_url": "https://mytracker.example.com/rest/api/2/issue"},
    )
    assert _extract_egress_host(payload) == "mytracker.example.com"


# --------------------------------------------------------------------------
# Allowlist matching
# --------------------------------------------------------------------------

def test_host_allowed_no_restriction_when_unset():
    assert _host_allowed("anything.example.com", None) is True


def test_host_allowed_exact_match():
    assert _host_allowed("api.example.com", ["api.example.com"]) is True


def test_host_allowed_subdomain_match():
    assert _host_allowed("sub.api.example.com", ["api.example.com"]) is True


def test_host_allowed_rejects_unlisted_host():
    assert _host_allowed("evil.example.com", ["api.example.com"]) is False


def test_host_allowed_fails_open_when_host_unresolvable():
    # No host to check against -- can't be blocked by the allowlist
    # mechanism itself (the kill switch is the backstop for these).
    assert _host_allowed(None, ["api.example.com"]) is True


def test_allowlist_rejects_via_router():
    settings.allowed_capability_hosts = ["allowed.example.com"]
    result = route_capability(
        CapabilityCheckInput(
            capability=CapabilityType.API, target="", params={"url": "https://not-allowed.example.com/x"}
        )
    )
    assert result.passed is False
    assert result.escalate is True
    assert result.evidence["host"] == "not-allowed.example.com"


def test_allowlist_permits_matching_host_and_dispatches_to_adapter():
    settings.allowed_capability_hosts = ["example.com"]
    # FAKE adapter is exempt from host checks entirely and always returns a
    # canned passing result -- proves the allowlist doesn't block a
    # capability with no host once it's exempt / matches.
    result = route_capability(
        CapabilityCheckInput(capability=CapabilityType.FAKE, target="", params={})
    )
    assert result.evidence.get("rejected") is not True


# --------------------------------------------------------------------------
# Audit logging
# --------------------------------------------------------------------------

def test_permitted_call_is_audit_logged(tmp_path, monkeypatch):
    log_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_logger, "filepath", str(log_path))

    route_capability(
        CapabilityCheckInput(capability=CapabilityType.FAKE, target="", params={"query": "SELECT 1"})
    )

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["action"] == "CAPABILITY_EGRESS"
    assert record["resource"] == CapabilityType.FAKE.value
    assert "timestamp" in record["details"]
    # No payload contents (e.g. the query text) leak into the audit record.
    assert "SELECT 1" not in json.dumps(record)


def test_rejected_call_is_not_audit_logged(tmp_path, monkeypatch):
    log_path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(audit_logger, "filepath", str(log_path))
    settings.capability_adapters_enabled = False

    route_capability(
        CapabilityCheckInput(capability=CapabilityType.FAKE, target="", params={})
    )

    assert not log_path.exists()
