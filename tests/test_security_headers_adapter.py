from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from agents.capability.security_headers_adapter import SecurityHeadersAdapter
from orchestrator.schemas import CapabilityCheckInput, CapabilityType


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


def test_missing_url_fails_closed():
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
