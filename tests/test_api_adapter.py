"""
Tests for agents/capability/api_adapter.py.

No test file existed for this adapter before this pass (Phase 5 of the
phased debug pass). Uses the same httpx.MockTransport patching pattern
as tests/test_link_checker.py.
"""
from __future__ import annotations

import httpx

from agents.capability.api_adapter import ApiAdapter
from orchestrator.schemas import CapabilityCheckInput, CapabilityType


def _patch_client(monkeypatch, handler):
    real_client_cls = httpx.Client
    transport = httpx.MockTransport(handler)

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr("agents.capability.api_adapter.httpx.Client", fake_client)


def test_status_match_passes(monkeypatch):
    _patch_client(monkeypatch, lambda request: httpx.Response(200, json={"ok": True}))

    adapter = ApiAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.API,
            target="",
            params={"url": "https://example.com/api", "method": "GET"},
            expected={"status": 200},
        )
    )
    assert result.passed is True
    assert result.evidence["status_code"] == 200


def test_status_mismatch_fails(monkeypatch):
    _patch_client(monkeypatch, lambda request: httpx.Response(500, text="oops"))

    adapter = ApiAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.API,
            target="",
            params={"url": "https://example.com/api", "method": "GET"},
            expected={"status": 200},
        )
    )
    assert result.passed is False
    assert result.evidence["status_code"] == 500


def test_response_timing_unavailable_under_mock_transport_does_not_crash(monkeypatch):
    """
    Regression test: response.elapsed raises RuntimeError unless the
    transport fires httpx's real timing hooks -- true for a real network
    connection, but not for httpx.MockTransport, the exact pattern this
    codebase's own tests use elsewhere (e.g. test_link_checker.py).
    Accessing it unconditionally used to crash the whole check with a
    misleading "HTTP execution error" instead of reporting the real
    pass/fail. This confirms it now degrades to response_time_ms=None.
    """
    _patch_client(monkeypatch, lambda request: httpx.Response(200, json={"ok": True}))

    adapter = ApiAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.API,
            target="",
            params={"url": "https://example.com/api", "method": "GET"},
            expected={"status": 200},
        )
    )
    assert result.passed is True
    assert "error" not in result.evidence
    assert result.evidence["response_time_ms"] is None


def test_expected_json_match_passes(monkeypatch):
    _patch_client(monkeypatch, lambda request: httpx.Response(200, json={"user_id": 1, "name": "Bob"}))

    adapter = ApiAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.API,
            target="",
            params={"url": "https://example.com/api", "method": "GET"},
            expected={"status": 200, "json": {"user_id": 1}},
        )
    )
    assert result.passed is True


def test_expected_json_mismatch_fails_with_healing_hints(monkeypatch):
    _patch_client(monkeypatch, lambda request: httpx.Response(200, json={"userId": 1, "name": "Bob"}))

    adapter = ApiAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.API,
            target="",
            params={"url": "https://example.com/api", "method": "GET"},
            expected={"status": 200, "json": {"user_id": 1}},
        )
    )
    assert result.passed is False
    assert result.evidence["json_mismatch"] is True
    assert result.evidence["healing_hints"]["expected_keys"] == ["user_id"]
    assert "userId" in result.evidence["healing_hints"]["actual_keys"]


def test_expected_json_non_dict_response_fails_cleanly(monkeypatch):
    _patch_client(monkeypatch, lambda request: httpx.Response(200, json=["not", "a", "dict"]))

    adapter = ApiAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.API,
            target="",
            params={"url": "https://example.com/api", "method": "GET"},
            expected={"status": 200, "json": {"user_id": 1}},
        )
    )
    assert result.passed is False
    assert "list" in result.evidence["error"]


def test_expected_json_invalid_json_fails_cleanly(monkeypatch):
    _patch_client(monkeypatch, lambda request: httpx.Response(200, text="not json at all"))

    adapter = ApiAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.API,
            target="",
            params={"url": "https://example.com/api", "method": "GET"},
            expected={"status": 200, "json": {"user_id": 1}},
        )
    )
    assert result.passed is False
    assert result.evidence["json_parse_error"] == "Response is not valid JSON"


def test_missing_url_fails_with_clear_error():
    adapter = ApiAdapter()
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.API, target="", params={})
    )
    assert result.passed is False
    assert "url" in result.evidence["error"].lower()


def test_request_error_fails_cleanly(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    _patch_client(monkeypatch, handler)

    adapter = ApiAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.API,
            target="",
            params={"url": "https://example.com/api", "method": "GET"},
        )
    )
    assert result.passed is False
    assert "error" in result.evidence
