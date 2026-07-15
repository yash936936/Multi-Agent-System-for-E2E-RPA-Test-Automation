"""
Security headers adapter — agents/capability/security_headers_adapter.py

Phase L2 (docs/decisions.md, Roadmap.md Phase L): passive-only web security
posture checks. Deliberately narrow scope, matching the plan exactly:

  - HTTP response header presence (a configurable set of well-known
    security-relevant headers -- HSTS, X-Content-Type-Options, etc.)
  - Set-Cookie flag checks (Secure/HttpOnly/SameSite)
  - "Common exposed-path" checks -- issuing plain GET requests to a
    configurable list of paths often left accidentally exposed
    (.env, .git/config, etc.) and reporting if any comes back with a
    real (non-404/non-redirect-to-generic-error) response.

Explicitly, permanently out of scope, by design, not by omission:
  - No payload injection (no SQLi/XSS/etc. probing of any kind)
  - No active vulnerability scanning or exploitation of any finding
  - No authentication bypass attempts

This is a real HTTP client (httpx), same "no DOM automation" posture as
agents/capability/link_checker.py -- just reading response headers/status,
never rendering or executing anything from the target.

Registered under CapabilityType.SECURITY_HEADERS -- see
orchestrator/capability_adapter.py::default_registry().
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx

from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

# A sane, well-known default set -- overridable via params["required_headers"].
# Presence-only check (this adapter doesn't validate each header's *value*
# is optimally configured, only that it's set at all -- a deeper policy
# check is a reasonable future adapter, not this one's job).
_DEFAULT_REQUIRED_HEADERS = (
    "Strict-Transport-Security",
    "X-Content-Type-Options",
    "X-Frame-Options",
    "Content-Security-Policy",
    "Referrer-Policy",
)

# Deliberately small, well-known, low-risk-to-request set. This adapter
# only ever issues a plain GET and looks at the status code/response
# size -- it never tries to exploit anything even if one of these paths
# turns out to be exposed.
_DEFAULT_EXPOSED_PATHS = (
    ".env",
    ".git/config",
    ".git/HEAD",
    "wp-config.php.bak",
    "config.php.bak",
    ".DS_Store",
    "backup.zip",
)


class SecurityHeadersAdapter:
    """Phase L2: passive header/cookie/exposed-path checks. No active probing."""

    capability_type: CapabilityType = CapabilityType.SECURITY_HEADERS

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params or {}

        url = params.get("url") or payload.target
        if not url:
            return self._fail("Missing 'url' (or 'target')")

        required_headers = params.get("required_headers", list(_DEFAULT_REQUIRED_HEADERS))
        check_cookie_flags = params.get("check_cookie_flags", True)
        check_exposed_paths = params.get("check_exposed_paths", True)
        exposed_paths = params.get("exposed_paths", list(_DEFAULT_EXPOSED_PATHS))
        timeout_seconds = params.get("timeout_seconds", 15.0)

        try:
            with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
                response = client.get(url)

                missing_headers = self._check_headers(response, required_headers)
                cookie_issues = self._check_cookie_flags(response) if check_cookie_flags else []
                exposed_found = (
                    self._check_exposed_paths(client, url, exposed_paths, response)
                    if check_exposed_paths else []
                )
        except Exception as e:
            return self._fail(f"Security headers check error: {str(e)}", evidence={"url": url})

        passed = not missing_headers and not cookie_issues and not exposed_found

        return CapabilityCheckResult(
            capability=self.capability_type,
            passed=passed,
            confidence=1.0,
            evidence={
                "url": url,
                "status_code": response.status_code,
                "missing_headers": missing_headers,
                "cookie_issues": cookie_issues,
                "exposed_paths_found": exposed_found,
            },
            escalate=not passed,
        )

    def _check_headers(self, response: httpx.Response, required_headers: List[str]) -> List[str]:
        present = {h.lower() for h in response.headers.keys()}
        return [h for h in required_headers if h.lower() not in present]

    def _check_cookie_flags(self, response: httpx.Response) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        for raw_cookie in response.headers.get_list("set-cookie"):
            cookie_name = raw_cookie.split("=", 1)[0].strip()
            lowered = raw_cookie.lower()
            missing_flags = [
                flag for flag in ("secure", "httponly", "samesite")
                if flag not in lowered
            ]
            if missing_flags:
                issues.append({"cookie": cookie_name, "missing_flags": missing_flags})
        return issues

    def _check_exposed_paths(
        self, client: httpx.Client, base_url: str, exposed_paths: List[str], base_response: httpx.Response
    ) -> List[Dict[str, Any]]:
        """
        Passive only: a plain GET per path, checking for a real (2xx,
        non-empty, distinct-from-the-site's-own-generic-404) response.
        Never attempts to read, exploit, or act on the content found.
        """
        found: List[Dict[str, Any]] = []
        baseline_len = len(base_response.content) if base_response.status_code == 404 else None

        for path in exposed_paths:
            try:
                target = urljoin(base_url if base_url.endswith("/") else base_url + "/", path)
                resp = client.get(target)
            except Exception:
                continue  # a single path failing to resolve isn't itself a finding

            if resp.status_code != 200:
                continue
            if baseline_len is not None and len(resp.content) == baseline_len:
                # Looks like the site's own generic 404 page served with a
                # 200 status (common misconfiguration) rather than a real hit.
                continue

            found.append({"path": path, "status_code": resp.status_code, "content_length": len(resp.content)})

        return found

    def _fail(self, msg: str, evidence: Optional[Dict[str, Any]] = None) -> CapabilityCheckResult:
        ev = {"error": msg}
        if evidence:
            ev.update(evidence)
        return CapabilityCheckResult(
            capability=self.capability_type, passed=False, confidence=1.0,
            evidence=ev, escalate=True,
        )
