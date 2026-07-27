"""Merged test file: test_capability_adapters_extended.py
Consolidated from: test_composio_adapter.py, test_accessibility_adapter.py, test_security_headers_adapter.py, test_performance_adapter.py, test_defect_tracker_adapter.py, test_gap_adapters.py, test_cloud_workflow_adapters.py
All original test functions preserved 1:1. Colliding fixture/helper names
renamed with a source-file suffix to avoid silent shadowing across sections.
"""
from __future__ import annotations
import sys
import types
from unittest.mock import MagicMock
import pytest
from agents.capability.composio_adapter import ComposioAdapter
from config.settings import settings
from orchestrator.schemas import CapabilityCheckInput, CapabilityType
from agents.capability.accessibility_adapter import AccessibilityAdapter
from tests.conftest_local_server import make_server, server_url
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from agents.capability.security_headers_adapter import SecurityHeadersAdapter
from agents.capability.performance_adapter import PerformanceAdapter
import json
from agents.capability.defect_tracker_adapter import DefectTrackerAdapter, _get_nested, _set_nested
from unittest.mock import patch, MagicMock
from agents.capability.azure_adapter import AzureBlobAdapter
from agents.capability.gcp_adapter import GcpStorageAdapter
from agents.capability.sharepoint_adapter import SharePointAdapter
from agents.capability.chatops_adapter import ChatOpsAdapter
from agents.capability.cloud_adapter import CloudAdapter
from agents.capability.workflow_adapter import WorkflowAdapter
from botocore.exceptions import ClientError


# ============================================================================
# ---- from test_composio_adapter.py ----
# ============================================================================
@pytest.fixture
def composio_enabled():
    original_enabled = settings.enable_composio
    original_key = settings.composio_api_key
    original_account = settings.composio_connected_account_id
    settings.enable_composio = True
    settings.composio_api_key = "test-composio-key"
    settings.composio_connected_account_id = "ca_test_default"
    yield
    settings.enable_composio = original_enabled
    settings.composio_api_key = original_key
    settings.composio_connected_account_id = original_account


@pytest.fixture
def mock_composio_package():
    """
    Injects a fake `composio` module into sys.modules so
    ComposioAdapter's deferred `from composio import Composio` import
    (module docstring constraint 2) resolves to a controllable mock
    instead of raising ImportError. Removes it afterward so it doesn't
    leak into other tests.
    """
    fake_module = types.ModuleType("composio")
    mock_client_instance = MagicMock()
    mock_client_instance.tools.execute.return_value = {"status": "success", "data": {"updatedRange": "Sheet1!A2:C2"}}
    mock_composio_class = MagicMock(return_value=mock_client_instance)
    fake_module.Composio = mock_composio_class

    original = sys.modules.get("composio")
    sys.modules["composio"] = fake_module
    yield mock_composio_class, mock_client_instance
    if original is not None:
        sys.modules["composio"] = original
    else:
        sys.modules.pop("composio", None)


def _run(params, expected=None):
    adapter = ComposioAdapter()
    return adapter.run(
        CapabilityCheckInput(capability=CapabilityType.COMPOSIO_SHEETS, target="", params=params, expected=expected or {})
    )


def test_disabled_by_default_returns_clean_failure_not_a_crash():
    """settings.enable_composio defaults False -- confirms the actual
    default, not just that the gate exists."""
    assert settings.enable_composio is False
    result = _run({"spreadsheet_id": "sheet123", "values": [["a", "b"]]})
    assert result.passed is False
    assert "enable_composio" in result.evidence["error"]


def test_enabled_but_missing_api_key_fails_cleanly(composio_enabled):
    settings.composio_api_key = None
    result = _run({"spreadsheet_id": "sheet123", "values": [["a", "b"]]})
    assert result.passed is False
    assert "composio_api_key" in result.evidence["error"]


def test_missing_spreadsheet_id_fails(composio_enabled, mock_composio_package):
    result = _run({"values": [["a", "b"]]})
    assert result.passed is False
    assert "spreadsheet_id" in result.evidence["error"]


def test_missing_values_fails(composio_enabled, mock_composio_package):
    result = _run({"spreadsheet_id": "sheet123"})
    assert result.passed is False
    assert "values" in result.evidence["error"]


def test_missing_connected_account_id_fails_when_no_settings_default(composio_enabled, mock_composio_package):
    settings.composio_connected_account_id = None
    result = _run({"spreadsheet_id": "sheet123", "values": [["a", "b"]]})
    assert result.passed is False
    assert "connected_account_id" in result.evidence["error"]


def test_successful_append_uses_settings_default_connected_account(composio_enabled, mock_composio_package):
    mock_class, mock_client = mock_composio_package
    result = _run({"spreadsheet_id": "sheet123", "values": [["Run 42", "PASS", "2026-07-19"]], "range": "Results!A1"})

    assert result.passed is True
    assert result.evidence["spreadsheet_id"] == "sheet123"
    assert result.evidence["row_count"] == 1

    mock_class.assert_called_once_with(api_key="test-composio-key")
    mock_client.tools.execute.assert_called_once()
    call_args = mock_client.tools.execute.call_args
    assert call_args.kwargs["connected_account_id"] == "ca_test_default"
    assert call_args.kwargs["arguments"]["spreadsheet_id"] == "sheet123"
    assert call_args.kwargs["arguments"]["values"] == [["Run 42", "PASS", "2026-07-19"]]
    assert call_args.kwargs["arguments"]["range"] == "Results!A1"


def test_per_call_connected_account_id_overrides_settings_default(composio_enabled, mock_composio_package):
    mock_class, mock_client = mock_composio_package
    result = _run({"spreadsheet_id": "sheet123", "values": [["x"]], "connected_account_id": "ca_override"})

    assert result.passed is True
    call_args = mock_client.tools.execute.call_args
    assert call_args.kwargs["connected_account_id"] == "ca_override"


def test_custom_tool_slug_is_honored_not_hardcoded(composio_enabled, mock_composio_package):
    """Design constraint 3: caller can override the tool slug rather than
    the adapter guessing/hardcoding Composio's exact registry naming."""
    mock_class, mock_client = mock_composio_package
    _run({"spreadsheet_id": "sheet123", "values": [["x"]], "tool_slug": "GOOGLESHEETS_APPEND_VALUES"})

    call_args = mock_client.tools.execute.call_args
    assert call_args.args[0] == "GOOGLESHEETS_APPEND_VALUES"


def test_composio_execution_error_is_caught_and_reported(composio_enabled, mock_composio_package):
    mock_class, mock_client = mock_composio_package
    mock_client.tools.execute.side_effect = RuntimeError("connection expired")

    result = _run({"spreadsheet_id": "sheet123", "values": [["x"]]})
    assert result.passed is False
    assert "connection expired" in result.evidence["error"]


def test_missing_composio_package_reports_clean_failure_not_a_crash(composio_enabled):
    """If settings.enable_composio is True but the composio package
    genuinely isn't installed, this must fail cleanly (ImportError caught),
    not propagate a raw traceback -- confirms the deferred-import path's
    own error handling, not just that the import is deferred."""
    sys.modules.pop("composio", None)  # ensure it's genuinely absent for this one test
    result = _run({"spreadsheet_id": "sheet123", "values": [["x"]]})
    assert result.passed is False
    assert "composio" in result.evidence["error"].lower()


def test_successful_call_is_audit_logged(composio_enabled, mock_composio_package):
    from orchestrator.audit_logger import audit_logger

    with pytest.MonkeyPatch.context() as mp:
        logged = []
        mp.setattr(audit_logger, "log", lambda **kwargs: logged.append(kwargs))
        _run({"spreadsheet_id": "sheet123", "values": [["x"]]})

    assert len(logged) == 1
    assert logged[0]["action"] == "COMPOSIO_SHEETS_APPEND"
    assert logged[0]["resource"] == "sheet123"

# ============================================================================
# ---- from test_accessibility_adapter.py ----
# ============================================================================
BROKEN_PAGE = b"""
<html><body>
  <img src="x.png">
  <a href="#"></a>
</body></html>
"""

CLEAN_PAGE = b"""
<html lang="en"><head><title>Test Page</title></head>
<body><main><h1>Hello</h1><img src="x.png" alt="A test image"><a href="/about">About</a></main></body></html>
"""


@pytest.fixture
def broken_server():
    srv = make_server(BROKEN_PAGE)
    yield srv
    srv.shutdown()


@pytest.fixture
def clean_server():
    srv = make_server(CLEAN_PAGE)
    yield srv
    srv.shutdown()


def test_deliberately_broken_page_fails_with_real_axe_violations(broken_server):
    """Verified against a deliberately-broken local HTML fixture, per the Phase L1 plan."""
    adapter = AccessibilityAdapter()
    url = server_url(broken_server)
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.ACCESSIBILITY, target=url, params={"url": url})
    )

    assert result.passed is False
    assert result.escalate is True
    assert result.evidence["total_violations"] > 0
    violation_ids = {v["id"] for v in result.evidence["violations"]}
    assert "image-alt" in violation_ids  # img with no alt text -- reliably flagged as "critical"


def test_clean_page_passes(clean_server):
    adapter = AccessibilityAdapter()
    url = server_url(clean_server)
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.ACCESSIBILITY, target=url, params={"url": url})
    )

    assert result.passed is True
    assert result.evidence["total_violations"] == 0


def test_severity_threshold_filters_lower_impact_violations(broken_server):
    """
    With severity_threshold='critical', only the image-alt violation
    (impact=critical) should cause a failure -- the moderate/serious ones
    present on the same broken page shouldn't count against this threshold.
    """
    adapter = AccessibilityAdapter()
    url = server_url(broken_server)
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.ACCESSIBILITY, target=url,
            params={"url": url, "severity_threshold": "critical"},
        )
    )

    assert result.passed is False  # image-alt (critical) still qualifies
    assert result.evidence["qualifying_violation_count"] >= 1
    assert result.evidence["total_violations"] > result.evidence["qualifying_violation_count"]


def test_invalid_severity_threshold_fails_closed():
    adapter = AccessibilityAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.ACCESSIBILITY, target="https://example.com",
            params={"url": "https://example.com", "severity_threshold": "not_a_real_level"},
        )
    )
    assert result.passed is False
    assert "severity_threshold" in result.evidence["error"]


def test_missing_url_fails_closed():
    adapter = AccessibilityAdapter()
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.ACCESSIBILITY, target="", params={})
    )
    assert result.passed is False
    assert "url" in result.evidence["error"]


def test_vendored_axe_core_actually_exists_on_disk():
    """Sanity check that the vendored file this adapter depends on is really there."""
    from agents.capability.accessibility_adapter import _AXE_CORE_PATH

    assert _AXE_CORE_PATH.exists()
    assert _AXE_CORE_PATH.stat().st_size > 100_000  # the real minified bundle, not a stub

# ============================================================================
# ---- from test_security_headers_adapter.py ----
# ============================================================================
def _make_configurable_server(routes: dict[str, dict]):
    """
    routes: path -> {"status": int, "headers": dict, "body": bytes}
    Any unlisted path falls back to a generic 404 with a fixed small body,
    matching a real server's own not-found page (used to prove the
    exposed-path check doesn't false-positive on a site's generic 404).
    """
    generic_404_body = b"<html><body>Not Found</body></html>"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = routes.get(self.path)
            if route is None:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(generic_404_body)
                return
            self.send_response(route.get("status", 200))
            for k, v in route.get("headers", {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(route.get("body", b"OK"))

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _url(server) -> str:
    return f"http://127.0.0.1:{server.server_port}"


def test_all_required_headers_present_and_no_issues_passes():
    good_headers = {
        "Strict-Transport-Security": "max-age=31536000",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Content-Security-Policy": "default-src 'self'",
        "Referrer-Policy": "no-referrer",
    }
    srv = _make_configurable_server({"/": {"status": 200, "headers": good_headers}})
    try:
        adapter = SecurityHeadersAdapter()
        url = _url(srv)
        result = adapter.run(
            CapabilityCheckInput(capability=CapabilityType.SECURITY_HEADERS, target=url, params={"url": url})
        )
        assert result.passed is True
        assert result.evidence["missing_headers"] == []
        assert result.evidence["exposed_paths_found"] == []
    finally:
        srv.shutdown()


def test_missing_headers_are_reported_and_fail():
    srv = _make_configurable_server({"/": {"status": 200, "headers": {}}})
    try:
        adapter = SecurityHeadersAdapter()
        url = _url(srv)
        result = adapter.run(
            CapabilityCheckInput(capability=CapabilityType.SECURITY_HEADERS, target=url, params={"url": url})
        )
        assert result.passed is False
        assert result.escalate is True
        assert "Strict-Transport-Security" in result.evidence["missing_headers"]
    finally:
        srv.shutdown()


def test_cookie_missing_secure_and_httponly_flags_is_reported():
    srv = _make_configurable_server(
        {"/": {"status": 200, "headers": {"Set-Cookie": "session=abc123; Path=/"}}}
    )
    try:
        adapter = SecurityHeadersAdapter()
        url = _url(srv)
        result = adapter.run(
            CapabilityCheckInput(capability=CapabilityType.SECURITY_HEADERS, target=url, params={"url": url})
        )
        assert result.passed is False
        issues = result.evidence["cookie_issues"]
        assert len(issues) == 1
        assert issues[0]["cookie"] == "session"
        assert "secure" in issues[0]["missing_flags"]
        assert "httponly" in issues[0]["missing_flags"]
    finally:
        srv.shutdown()


def test_cookie_with_all_flags_set_has_no_issues():
    srv = _make_configurable_server(
        {"/": {"status": 200, "headers": {"Set-Cookie": "session=abc123; Secure; HttpOnly; SameSite=Strict"}}}
    )
    try:
        adapter = SecurityHeadersAdapter()
        url = _url(srv)
        result = adapter.run(
            CapabilityCheckInput(
                capability=CapabilityType.SECURITY_HEADERS, target=url,
                params={"url": url, "check_exposed_paths": False, "required_headers": []},
            )
        )
        assert result.evidence["cookie_issues"] == []
        assert result.passed is True
    finally:
        srv.shutdown()


def test_exposed_env_file_is_detected():
    """A real .env accidentally exposed with distinct content (not the generic 404) must be flagged."""
    routes = {
        "/": {"status": 200, "headers": {}},
        "/.env": {"status": 200, "headers": {}, "body": b"DB_PASSWORD=hunter2"},
    }
    srv = _make_configurable_server(routes)
    try:
        adapter = SecurityHeadersAdapter()
        url = _url(srv)
        result = adapter.run(
            CapabilityCheckInput(
                capability=CapabilityType.SECURITY_HEADERS, target=url,
                params={"url": url, "required_headers": [], "check_cookie_flags": False},
            )
        )
        assert result.passed is False
        found_paths = {f["path"] for f in result.evidence["exposed_paths_found"]}
        assert ".env" in found_paths
    finally:
        srv.shutdown()


def test_missing_url_fails_closed_security_headers():
    adapter = SecurityHeadersAdapter()
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.SECURITY_HEADERS, target="", params={})
    )
    assert result.passed is False
    assert "url" in result.evidence["error"]


def test_no_active_probing_only_get_requests_issued(monkeypatch):
    """
    Confirms the passive-only design constraint at the code level: this
    adapter must never issue anything but GET requests -- no POST/PUT/
    payload-carrying methods of any kind.
    """
    import httpx

    calls = []
    real_get = httpx.Client.get

    def spy_get(self, url, *args, **kwargs):
        calls.append(url)
        return real_get(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "get", spy_get)
    monkeypatch.setattr(httpx.Client, "post", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("security_headers_adapter must never issue POST requests")
    ))

    srv = _make_configurable_server({"/": {"status": 200, "headers": {}}})
    try:
        adapter = SecurityHeadersAdapter()
        url = _url(srv)
        adapter.run(CapabilityCheckInput(capability=CapabilityType.SECURITY_HEADERS, target=url, params={"url": url}))
        assert len(calls) > 0
    finally:
        srv.shutdown()

# ============================================================================
# ---- from test_performance_adapter.py ----
# ============================================================================
PAGE = b"<html><body><h1>Hello Perf</h1></body></html>"


@pytest.fixture
def server():
    srv = make_server(PAGE)
    yield srv
    srv.shutdown()


def test_generous_budget_passes(server):
    adapter = PerformanceAdapter()
    url = server_url(server)
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.PERFORMANCE, target=url,
            params={"url": url, "budget": {"load_time_ms": 60000, "dom_content_loaded_ms": 60000}},
        )
    )

    assert result.passed is True
    assert result.evidence["violations"] == {}
    assert "load_time_ms" in result.evidence["metrics_ms"]


def test_impossibly_tight_budget_fails(server):
    adapter = PerformanceAdapter()
    url = server_url(server)
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.PERFORMANCE, target=url,
            params={"url": url, "budget": {"load_time_ms": 0}},
        )
    )

    assert result.passed is False
    assert result.escalate is True
    assert "load_time_ms" in result.evidence["violations"]
    violation = result.evidence["violations"]["load_time_ms"]
    assert violation["budget_ms"] == 0
    assert violation["actual_ms"] >= 0


def test_metrics_collected_are_real_navigation_timing_values(server):
    """Not fabricated numbers -- must reflect the real page load via performance API."""
    adapter = PerformanceAdapter()
    url = server_url(server)
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.PERFORMANCE, target=url, params={"url": url, "budget": {}})
    )

    assert result.passed is True  # empty budget -> nothing to violate
    metrics = result.evidence["metrics_ms"]
    assert "dom_content_loaded_ms" in metrics or "load_time_ms" in metrics
    for value in metrics.values():
        assert value >= 0


def test_missing_url_fails_closed_performance():
    adapter = PerformanceAdapter()
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.PERFORMANCE, target="", params={})
    )
    assert result.passed is False
    assert "url" in result.evidence["error"]


def test_default_budget_used_when_none_specified(server):
    """Confirms _DEFAULT_BUDGET_MS is actually applied, not just documented."""
    adapter = PerformanceAdapter()
    url = server_url(server)
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.PERFORMANCE, target=url, params={"url": url})
    )
    # A local single-page test server should comfortably pass generous defaults.
    assert result.passed is True
    assert set(result.evidence["budget_ms"].keys()) >= {"load_time_ms", "dom_content_loaded_ms"}


def test_registry_includes_all_phase_l_adapters():
    """Phase L: three-way registration check (CapabilityType enum + default_registry())
    for all three new adapters -- accessibility, security_headers, performance."""
    from agents.capability.accessibility_adapter import AccessibilityAdapter
    from agents.capability.security_headers_adapter import SecurityHeadersAdapter
    from orchestrator.capability_adapter import default_registry

    registry = default_registry()
    assert CapabilityType.ACCESSIBILITY in registry.registered_types()
    assert CapabilityType.SECURITY_HEADERS in registry.registered_types()
    assert CapabilityType.PERFORMANCE in registry.registered_types()
    assert isinstance(registry.get(CapabilityType.ACCESSIBILITY), AccessibilityAdapter)
    assert isinstance(registry.get(CapabilityType.SECURITY_HEADERS), SecurityHeadersAdapter)
    assert isinstance(registry.get(CapabilityType.PERFORMANCE), PerformanceAdapter)

# ============================================================================
# ---- from test_defect_tracker_adapter.py ----
# ============================================================================
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


def _url__defect_tracker_adapter(server) -> str:
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
        url = _url__defect_tracker_adapter(srv)
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
        url = _url__defect_tracker_adapter(srv)
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
        url = _url__defect_tracker_adapter(srv)
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
        url = _url__defect_tracker_adapter(srv)
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
        url = _url__defect_tracker_adapter(srv)
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
        url = _url__defect_tracker_adapter(srv)
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

# ============================================================================
# ---- from test_gap_adapters.py ----
# ============================================================================
# --- Azure Blob Adapter ---

def test_azure_adapter_blob_exists_success():
    adapter = AzureBlobAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AZURE_BLOB, target="report.pdf",
        params={"connection_string": "fake", "container": "docs", "blob_name": "report.pdf"},
        expected={"exists": True, "min_size_bytes": 100},
    )
    with patch("agents.capability.azure_adapter.BlobServiceClient.from_connection_string") as mock_from_conn:
        mock_blob_client = MagicMock()
        mock_props = MagicMock(size=500, last_modified="2024-01-01")
        mock_blob_client.get_blob_properties.return_value = mock_props
        mock_service = MagicMock()
        mock_service.get_blob_client.return_value = mock_blob_client
        mock_from_conn.return_value = mock_service

        result = adapter.run(payload)
        assert result.passed is True
        assert result.evidence["size_bytes"] == 500


def test_azure_adapter_upload_blob_real_write():
    adapter = AzureBlobAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AZURE_BLOB, target="new.txt",
        params={
            "connection_string": "fake", "container": "docs", "blob_name": "new.txt",
            "action": "upload_blob", "content": "hello world",
        },
        expected={},
    )
    with patch("agents.capability.azure_adapter.BlobServiceClient.from_connection_string") as mock_from_conn:
        mock_blob_client = MagicMock()
        mock_blob_client.get_blob_properties.return_value = MagicMock(size=11)
        mock_service = MagicMock()
        mock_service.get_blob_client.return_value = mock_blob_client
        mock_from_conn.return_value = mock_service

        result = adapter.run(payload)
        assert result.passed is True
        mock_blob_client.upload_blob.assert_called_once()
        assert result.evidence["uploaded_bytes"] == 11


def test_azure_adapter_missing_params():
    adapter = AzureBlobAdapter()
    payload = CapabilityCheckInput(capability=CapabilityType.AZURE_BLOB, target="", params={}, expected={})
    result = adapter.run(payload)
    assert result.passed is False
    assert "error" in result.evidence


# --- GCP Storage Adapter ---

def test_gcp_adapter_blob_exists_success():
    adapter = GcpStorageAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.GCP_STORAGE, target="report.pdf",
        params={"bucket": "my-bucket", "blob_name": "report.pdf"},
        expected={"exists": True, "min_size_bytes": 100},
    )
    with patch("agents.capability.gcp_adapter.storage.Client") as mock_client_cls:
        mock_blob = MagicMock(size=500, updated="2024-01-01")
        mock_blob.exists.return_value = True
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_client_cls.return_value = mock_client

        result = adapter.run(payload)
        assert result.passed is True
        assert result.evidence["size_bytes"] == 500


def test_gcp_adapter_upload_blob_real_write():
    adapter = GcpStorageAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.GCP_STORAGE, target="new.txt",
        params={"bucket": "my-bucket", "blob_name": "new.txt", "action": "upload_blob", "content": "hi"},
        expected={},
    )
    with patch("agents.capability.gcp_adapter.storage.Client") as mock_client_cls:
        mock_blob = MagicMock(size=2)
        mock_bucket = MagicMock()
        mock_bucket.blob.return_value = mock_blob
        mock_client = MagicMock()
        mock_client.bucket.return_value = mock_bucket
        mock_client_cls.return_value = mock_client

        result = adapter.run(payload)
        assert result.passed is True
        mock_blob.upload_from_string.assert_called_once()


# --- SharePoint Adapter ---

def test_sharepoint_adapter_file_exists_success():
    adapter = SharePointAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.SHAREPOINT, target="Shared Documents/report.pdf",
        params={
            "tenant_id": "t", "client_id": "c", "client_secret": "s",
            "drive_id": "drive123", "file_path": "Shared Documents/report.pdf",
        },
        expected={"exists": True},
    )
    with patch("agents.capability.sharepoint_adapter.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__.return_value = mock_client

        token_resp = MagicMock()
        token_resp.json.return_value = {"access_token": "fake-token"}
        token_resp.raise_for_status.return_value = None

        meta_resp = MagicMock(status_code=200)
        meta_resp.json.return_value = {"size": 500, "lastModifiedDateTime": "2024-01-01"}
        meta_resp.raise_for_status.return_value = None

        mock_client.post.return_value = token_resp
        mock_client.get.return_value = meta_resp

        result = adapter.run(payload)
        assert result.passed is True
        assert result.evidence["size_bytes"] == 500


def test_sharepoint_adapter_missing_credentials():
    adapter = SharePointAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.SHAREPOINT, target="x",
        params={"drive_id": "d", "file_path": "x.txt"},
        expected={},
    )
    import os
    for var in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET"):
        os.environ.pop(var, None)
    result = adapter.run(payload)
    assert result.passed is False
    assert "auth error" in result.evidence["error"].lower()


# --- ChatOps Adapter ---

def test_chatops_adapter_slack_success():
    adapter = ChatOpsAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.CHAT_OPS, target="",
        params={"platform": "slack", "webhook_url": "https://hooks.slack.com/x", "title": "AURA", "message": "Run passed"},
        expected={},
    )
    with patch("agents.capability.chatops_adapter.httpx.Client") as mock_client_cls:
        mock_response = MagicMock(status_code=200)
        mock_response.elapsed.total_seconds.return_value = 0.2
        mock_client_cls.return_value.__enter__.return_value.post.return_value = mock_response

        result = adapter.run(payload)
        assert result.passed is True
        assert result.evidence["platform"] == "slack"


def test_chatops_adapter_teams_success():
    adapter = ChatOpsAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.CHAT_OPS, target="",
        params={
            "platform": "teams", "webhook_url": "https://outlook.office.com/x",
            "title": "AURA", "message": "Run failed", "fields": [{"title": "Run ID", "value": "abc123"}],
        },
        expected={},
    )
    with patch("agents.capability.chatops_adapter.httpx.Client") as mock_client_cls:
        mock_response = MagicMock(status_code=200)
        mock_response.elapsed.total_seconds.return_value = 0.2
        mock_post = mock_client_cls.return_value.__enter__.return_value.post
        mock_post.return_value = mock_response

        result = adapter.run(payload)
        assert result.passed is True
        sent_body = mock_post.call_args.kwargs["json"]
        assert sent_body["@type"] == "MessageCard"
        assert sent_body["sections"][0]["facts"][0]["name"] == "Run ID"


def test_chatops_adapter_missing_webhook():
    adapter = ChatOpsAdapter()
    payload = CapabilityCheckInput(capability=CapabilityType.CHAT_OPS, target="", params={}, expected={})
    result = adapter.run(payload)
    assert result.passed is False

# ============================================================================
# ---- from test_cloud_workflow_adapters.py ----
# ============================================================================
# --- Cloud Adapter Tests ---
def test_cloud_adapter_s3_exists_success():
    adapter = CloudAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.CLOUD, target="s3://my-bucket/report.pdf",
        params={
            "action": "s3_object_exists", 
            "bucket": "my-bucket", 
            "key": "report.pdf",
            "aws_access_key_id": "test", 
            "aws_secret_access_key": "test"
        },
        expected={"exists": True, "min_size_bytes": 100}
    )
    
    with patch("agents.capability.cloud_adapter.boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        mock_s3.head_object.return_value = {
            'ContentLength': 500,
            'LastModified': "2024-01-01T00:00:00Z"
        }
        
        result = adapter.run(payload)
        assert result.passed is True
        assert result.evidence["size_bytes"] == 500

def test_cloud_adapter_s3_not_found():
    adapter = CloudAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.CLOUD, target="",
        params={"bucket": "b", "key": "k", "aws_access_key_id": "t", "aws_secret_access_key": "t"},
        expected={"exists": False} # We expect it to be missing
    )
    
    with patch("agents.capability.cloud_adapter.boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        
        # Simulate boto3 404 error
        error_response = {'Error': {'Code': '404', 'Message': 'Not Found'}}
        mock_s3.head_object.side_effect = ClientError(error_response, 'HeadObject')
        
        result = adapter.run(payload)
        assert result.passed is True # Passed because we expected it to be missing
        assert result.evidence["exists"] is False

def test_cloud_adapter_list_objects_success():
    adapter = CloudAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.CLOUD, target="s3://my-bucket/exports/",
        params={
            "action": "list_objects",
            "bucket": "my-bucket",
            "prefix": "exports/",
            "aws_access_key_id": "test",
            "aws_secret_access_key": "test",
        },
        expected={"min_count": 1, "must_contain_key": "exports/report.pdf"},
    )

    with patch("agents.capability.cloud_adapter.boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        mock_s3.list_objects_v2.return_value = {
            "Contents": [{"Key": "exports/report.pdf"}, {"Key": "exports/summary.csv"}]
        }

        result = adapter.run(payload)
        assert result.passed is True
        assert result.evidence["object_count"] == 2
        assert result.evidence["required_key_found"] is True


def test_cloud_adapter_list_objects_missing_required_key_fails():
    adapter = CloudAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.CLOUD, target="s3://my-bucket/exports/",
        params={"action": "list_objects", "bucket": "my-bucket", "aws_access_key_id": "t", "aws_secret_access_key": "t"},
        expected={"must_contain_key": "exports/missing.pdf"},
    )

    with patch("agents.capability.cloud_adapter.boto3.client") as mock_boto:
        mock_s3 = MagicMock()
        mock_boto.return_value = mock_s3
        mock_s3.list_objects_v2.return_value = {"Contents": [{"Key": "exports/report.pdf"}]}

        result = adapter.run(payload)
        assert result.passed is False
        assert result.evidence["required_key_found"] is False


def test_cloud_adapter_rejects_mutating_actions_explicitly():
    # upload_object/delete_object were never implemented and never should
    # be -- this adapter is detect-only by design (TRD.md §9). Confirms the
    # rejection is explicit (with a clear reason), not a silent fallthrough
    # into s3_object_exists.
    adapter = CloudAdapter()
    for bad_action in ("upload_object", "delete_object", "download_object", "typo_action"):
        payload = CapabilityCheckInput(
            capability=CapabilityType.CLOUD, target="",
            params={"action": bad_action, "bucket": "b", "key": "k"},
            expected={},
        )
        result = adapter.run(payload)
        assert result.passed is False
        assert bad_action in result.evidence["error"]


# --- Workflow Adapter Tests ---
def test_workflow_adapter_trigger_success():
    adapter = WorkflowAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.WORKFLOW, target="https://jenkins/job/build",
        params={"url": "https://jenkins/job/build", "payload": {"ref": "main"}},
        expected={"accepted_status_codes": [200, 201]}
    )
    
    with patch("httpx.Client") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.elapsed.total_seconds.return_value = 0.5
        mock_client.return_value.__enter__.return_value.request.return_value = mock_response
        
        result = adapter.run(payload)
        assert result.passed is True
        assert result.evidence["status_code"] == 201

def test_workflow_adapter_trigger_rejected():
    adapter = WorkflowAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.WORKFLOW, target="",
        params={"url": "https://jenkins/job/build"},
        expected={}
    )
    
    with patch("httpx.Client") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 403 # Forbidden
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_client.return_value.__enter__.return_value.request.return_value = mock_response
        
        result = adapter.run(payload)
        assert result.passed is False


# ---- merged from tests/test_pdf_ocr.py ----
from types import SimpleNamespace

from agents.capability.pdf_adapter import PdfAdapter
from orchestrator.schemas import CapabilityCheckInput, CapabilityType


def _fake_pdf_reader(native_text: str = ""):
    page = SimpleNamespace(extract_text=lambda: native_text)
    return SimpleNamespace(pages=[page], metadata={}, is_encrypted=False)


def test_pdf_adapter_ocr_extracts_text_from_scanned_pdf(tmp_path, monkeypatch):
    pdf_path = tmp_path / "scanned.pdf"
    adapter = PdfAdapter()
    monkeypatch.setattr("agents.capability.pdf_adapter.PdfReader", lambda file_path: _fake_pdf_reader())
    monkeypatch.setattr(adapter, "_ocr_extract", lambda file_path, dpi: "AURA VERIFIED")
    payload = CapabilityCheckInput(
        capability=CapabilityType.PDF_OCR, target=str(pdf_path),
        params={"file_path": str(pdf_path)},
        expected={"text_contains": "AURA"},
    )
    result = adapter.run(payload)
    assert result.evidence.get("ocr_used") is True
    assert result.passed is True, result.evidence


def test_pdf_adapter_native_text_layer_skips_ocr(tmp_path, monkeypatch):
    pdf_path = tmp_path / "native.pdf"
    adapter = PdfAdapter()
    monkeypatch.setattr(
        "agents.capability.pdf_adapter.PdfReader",
        lambda file_path: _fake_pdf_reader("Native text layer present"),
    )
    monkeypatch.setattr(
        adapter,
        "_ocr_extract",
        lambda file_path, dpi: (_ for _ in ()).throw(AssertionError("OCR should not be called")),
    )
    payload = CapabilityCheckInput(
        capability=CapabilityType.PDF_OCR, target=str(pdf_path),
        params={"file_path": str(pdf_path)},
        expected={"text_contains": "Native text layer"},
    )
    result = adapter.run(payload)
    assert result.passed is True
    assert "ocr_used" not in result.evidence
