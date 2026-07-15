from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agents.capability.defect_tracker_adapter import DefectTrackerAdapter, _get_nested, _set_nested
from orchestrator.schemas import CapabilityCheckInput, CapabilityType


def _make_recording_server(response_status: int = 201, response_body: dict | None = None):
    """
    A tiny local REST server standing in for a Jira/TestRail/Zephyr/Xray-
    style API: records every request it receives (method, path, parsed
    JSON body) and replies with a configurable status + JSON body, so
    tests can assert both what the adapter sent and how it interpreted
    the response.
    """
    received: list[dict] = []
    body_to_send = json.dumps(response_body or {}).encode()

    class Handler(BaseHTTPRequestHandler):
        def _handle(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            parsed = None
            if raw:
                try:
                    parsed = json.loads(raw)
                except Exception:
                    parsed = None
            received.append({"method": self.command, "path": self.path, "body": parsed})
            self.send_response(response_status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body_to_send)

        def do_POST(self):
            self._handle()

        def do_PUT(self):
            self._handle()

        def do_GET(self):
            self._handle()

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, received


def _url(server) -> str:
    return f"http://127.0.0.1:{server.server_port}"


# --------------------------------------------------------------------------
# Nested field-mapping helpers
# --------------------------------------------------------------------------

def test_set_nested_builds_intermediate_dicts():
    body: dict = {}
    _set_nested(body, "fields.priority.name", "High")
    assert body == {"fields": {"priority": {"name": "High"}}}


def test_get_nested_returns_none_for_missing_path():
    assert _get_nested({"fields": {"summary": "x"}}, "fields.priority.name") is None


def test_get_nested_reads_existing_path():
    assert _get_nested({"a": {"b": {"c": 42}}}, "a.b.c") == 42


# --------------------------------------------------------------------------
# Create action — Jira-style nested field mapping
# --------------------------------------------------------------------------

def test_create_maps_flat_fields_to_jira_style_nested_body():
    srv, received = _make_recording_server(response_status=201, response_body={"id": "10001", "key": "QA-1"})
    try:
        adapter = DefectTrackerAdapter()
        url = _url(srv)
        result = adapter.run(
            CapabilityCheckInput(
                capability=CapabilityType.DEFECT_TRACKER,
                target=url,
                params={
                    "base_url": url,
                    "action": "create",
                    "fields": {"title": "Login button unresponsive", "priority": "High"},
                    "field_mapping": {"title": "fields.summary", "priority": "fields.priority.name"},
                    "response_field_mapping": {"issue_key": "key"},
                },
            )
        )
        assert result.passed is True
        assert received[0]["method"] == "POST"
        assert received[0]["body"] == {
            "fields": {"summary": "Login button unresponsive", "priority": {"name": "High"}}
        }
        assert result.evidence["extracted_fields"]["issue_key"] == "QA-1"
    finally:
        srv.shutdown()


# --------------------------------------------------------------------------
# Create action — TestRail-style flat field mapping (different tool, same adapter)
# --------------------------------------------------------------------------

def test_create_maps_flat_fields_to_testrail_style_flat_body():
    srv, received = _make_recording_server(response_status=200, response_body={"id": 42, "status_id": 5})
    try:
        adapter = DefectTrackerAdapter()
        url = _url(srv)
        result = adapter.run(
            CapabilityCheckInput(
                capability=CapabilityType.DEFECT_TRACKER,
                target=url,
                params={
                    "base_url": url,
                    "action": "create",
                    "fields": {"title": "Checkout flow", "status": 5},
                    "field_mapping": {"title": "title", "status": "status_id"},
                },
            )
        )
        assert result.passed is True
        assert received[0]["body"] == {"title": "Checkout flow", "status_id": 5}
    finally:
        srv.shutdown()


# --------------------------------------------------------------------------
# Update action
# --------------------------------------------------------------------------

def test_update_issues_put_to_record_id_url():
    srv, received = _make_recording_server(response_status=204)
    try:
        adapter = DefectTrackerAdapter()
        url = _url(srv)
        result = adapter.run(
            CapabilityCheckInput(
                capability=CapabilityType.DEFECT_TRACKER,
                target=url,
                params={
                    "base_url": url,
                    "action": "update",
                    "record_id": "QA-1",
                    "fields": {"status": "Done"},
                    "field_mapping": {"status": "fields.status.name"},
                },
            )
        )
        assert result.passed is True
        assert received[0]["method"] == "PUT"
        assert received[0]["path"] == "/QA-1"
        assert received[0]["body"] == {"fields": {"status": {"name": "Done"}}}
    finally:
        srv.shutdown()


# --------------------------------------------------------------------------
# Get action + expected-field verification
# --------------------------------------------------------------------------

def test_get_action_extracts_and_verifies_expected_fields():
    srv, _ = _make_recording_server(
        response_status=200, response_body={"fields": {"status": {"name": "Done"}}}
    )
    try:
        adapter = DefectTrackerAdapter()
        url = _url(srv)
        result = adapter.run(
            CapabilityCheckInput(
                capability=CapabilityType.DEFECT_TRACKER,
                target=url,
                params={
                    "base_url": url,
                    "action": "get",
                    "record_id": "QA-1",
                    "response_field_mapping": {"status": "fields.status.name"},
                    "expected_fields": {"status": "Done"},
                },
            )
        )
        assert result.passed is True
        assert result.evidence["extracted_fields"]["status"] == "Done"
        assert result.evidence["field_mismatches"] == []
    finally:
        srv.shutdown()


def test_get_action_reports_field_mismatch_as_failure():
    srv, _ = _make_recording_server(
        response_status=200, response_body={"fields": {"status": {"name": "In Progress"}}}
    )
    try:
        adapter = DefectTrackerAdapter()
        url = _url(srv)
        result = adapter.run(
            CapabilityCheckInput(
                capability=CapabilityType.DEFECT_TRACKER,
                target=url,
                params={
                    "base_url": url,
                    "action": "get",
                    "record_id": "QA-1",
                    "response_field_mapping": {"status": "fields.status.name"},
                    "expected_fields": {"status": "Done"},
                },
            )
        )
        assert result.passed is False
        assert result.escalate is True
        mismatch = result.evidence["field_mismatches"][0]
        assert mismatch == {"field": "status", "expected": "Done", "actual": "In Progress"}
    finally:
        srv.shutdown()


# --------------------------------------------------------------------------
# Error paths
# --------------------------------------------------------------------------

def test_missing_base_url_fails_closed():
    adapter = DefectTrackerAdapter()
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.DEFECT_TRACKER, target="", params={})
    )
    assert result.passed is False
    assert "base_url" in result.evidence["error"]


def test_unsupported_action_fails_closed():
    adapter = DefectTrackerAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.DEFECT_TRACKER,
            target="http://127.0.0.1:1/",
            params={"base_url": "http://127.0.0.1:1/", "action": "delete"},
        )
    )
    assert result.passed is False
    assert "delete" in result.evidence["error"]


def test_unexpected_status_code_fails_with_escalate():
    srv, _ = _make_recording_server(response_status=500, response_body={"error": "server exploded"})
    try:
        adapter = DefectTrackerAdapter()
        url = _url(srv)
        result = adapter.run(
            CapabilityCheckInput(
                capability=CapabilityType.DEFECT_TRACKER,
                target=url,
                params={"base_url": url, "action": "create", "fields": {"title": "x"}},
            )
        )
        assert result.passed is False
        assert result.escalate is True
        assert result.evidence["status_code"] == 500
    finally:
        srv.shutdown()


def test_connection_error_fails_closed():
    adapter = DefectTrackerAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.DEFECT_TRACKER,
            target="http://127.0.0.1:1/",
            params={"base_url": "http://127.0.0.1:1/", "action": "create", "fields": {"title": "x"}},
        )
    )
    assert result.passed is False
    assert result.escalate is True


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------

def test_registered_in_default_registry():
    from orchestrator.capability_adapter import default_registry

    registry = default_registry()
    assert CapabilityType.DEFECT_TRACKER in registry.registered_types()
    adapter = registry.get(CapabilityType.DEFECT_TRACKER)
    assert isinstance(adapter, DefectTrackerAdapter)
