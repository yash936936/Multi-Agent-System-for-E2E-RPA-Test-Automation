"""
Defect / test-case-management adapter — agents/capability/defect_tracker_adapter.py

Phase M (docs/decisions.md, Roadmap.md §9 Phase M): the fifth and last
adapter of the second remediation roadmap (Phases G-M), deliberately
lowest-confidence and last on purpose (Roadmap.md's own framing).

Scope, matching the plan exactly:
    "generic REST + field-mapping config for Jira/TestRail/Zephyr/Xray-style
    tools"

This is NOT a Jira SDK, a TestRail SDK, etc. -- there is exactly one
adapter here, and it stays tool-agnostic by never hardcoding any vendor's
JSON shape. Instead, the caller supplies:

  - `base_url` (+ optional `record_id` for update/get against a specific
    resource) and `headers` (the caller's own auth -- API token, Basic
    auth, whatever the target tool wants; this adapter never generates or
    stores credentials itself)
  - `fields`: a flat dict of generic field values to send (e.g.
    {"title": "...", "status": "Done", "priority": "High"})
  - `field_mapping`: generic field name -> dotted path in the *target
    tool's* request JSON shape (e.g. Jira wants
    {"title": "fields.summary", "priority": "fields.priority.name"};
    TestRail wants {"title": "title", "status": "status_id"}). This is
    the whole point of "field-mapping config" in the roadmap line above --
    one adapter body, a different mapping dict per tool/instance.
  - `response_field_mapping` (optional, for `action="get"` or to read back
    fields from a create/update response): generic name -> dotted path to
    extract from the JSON response body.
  - `expected_fields` (optional): generic name -> expected value, checked
    against the extracted response fields (via `response_field_mapping`)
    to decide pass/fail, not just "did the HTTP call succeed."

Actions supported: "create", "update", "get" (`params["action"]`,
default "create"). HTTP method defaults to POST/PUT/GET respectively but
is overridable via `params["method"]` for tools with nonstandard verbs
(e.g. Zephyr Scale's PUT-based execution updates).

Explicitly, permanently out of scope, by design:
  - No vendor-specific auth flows (OAuth dance, session cookies) -- the
    caller supplies whatever `headers` the target tool needs, same as
    `workflow_adapter.py`'s existing posture.
  - No bidirectional sync / webhooks -- this is a single request/response
    capability check, not a persistent integration.
  - No hardcoded vendor field shapes anywhere in this file -- if a vendor
    isn't representable via a flat field_mapping (Jira's nested
    `fields.*` and TestRail's flat `field_name` both are), that is a
    scope decision to flag, not to route around with vendor-specific code.

Honest confidence note (see docs/decisions.md, this phase): verified only
against a mocked local HTTP server in this sandbox (no real Jira/TestRail/
Zephyr/Xray account available to test against) -- live-integration
correctness with any specific real vendor is unverified.

Registered under CapabilityType.DEFECT_TRACKER -- see
orchestrator/capability_adapter.py::default_registry().
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

_DEFAULT_ACCEPTED_STATUS_CODES = {
    "create": [200, 201, 202],
    "update": [200, 201, 202, 204],
    "get": [200],
}


def _set_nested(target: Dict[str, Any], dotted_path: str, value: Any) -> None:
    """Sets target[a][b][c] = value for dotted_path 'a.b.c', creating
    intermediate dicts as needed. Mirrors how Jira-style nested field
    shapes (e.g. 'fields.priority.name') are built from a flat mapping."""
    parts = dotted_path.split(".")
    cursor = target
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


def _get_nested(source: Any, dotted_path: str) -> Any:
    """Best-effort read of source[a][b][c] for dotted_path 'a.b.c'.
    Returns None (not an exception) if any segment is missing or the
    response shape doesn't match -- a missing field is evidence, not a
    crash."""
    cursor = source
    for part in dotted_path.split("."):
        if isinstance(cursor, dict) and part in cursor:
            cursor = cursor[part]
        else:
            return None
    return cursor


class DefectTrackerAdapter:
    """Phase M: generic REST + field-mapping adapter for test-case-
    management / defect-tracking tools (Jira/TestRail/Zephyr/Xray-style).
    No vendor-specific code -- the field_mapping config supplied per call
    is what makes this adapter usable against any of them."""

    capability_type: CapabilityType = CapabilityType.DEFECT_TRACKER

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params or {}

        base_url = params.get("base_url") or params.get("url") or payload.target
        if not base_url:
            return self._fail("Missing 'base_url' (or 'url'/'target')")

        action = params.get("action", "create")
        if action not in ("create", "update", "get"):
            return self._fail(f"Unsupported action '{action}' (expected create/update/get)")

        record_id = params.get("record_id")
        url = base_url
        if record_id is not None and action in ("update", "get"):
            url = f"{base_url.rstrip('/')}/{record_id}"

        default_method = {"create": "POST", "update": "PUT", "get": "GET"}[action]
        method = params.get("method", default_method).upper()

        headers = params.get("headers", {})
        timeout_seconds = params.get("timeout_seconds", 15.0)
        accepted_status_codes = params.get(
            "accepted_status_codes", _DEFAULT_ACCEPTED_STATUS_CODES[action]
        )

        # Build the vendor-shaped request body from the generic `fields`
        # dict via `field_mapping`. Unmapped fields are sent as-is under
        # their own name (a sane default rather than a silent drop, but
        # anything that matters to a specific tool should be in the
        # mapping -- unmapped passthrough is a convenience, not the
        # intended path for a fully-configured integration).
        fields = params.get("fields", {})
        field_mapping = params.get("field_mapping", {})
        body: Dict[str, Any] = {}
        for generic_name, value in fields.items():
            dotted_path = field_mapping.get(generic_name, generic_name)
            _set_nested(body, dotted_path, value)

        request_kwargs: Dict[str, Any] = {"headers": headers}
        if method != "GET":
            request_kwargs["json"] = body
        elif params.get("query_params"):
            request_kwargs["params"] = params["query_params"]

        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.request(method, url, **request_kwargs)
        except Exception as e:
            return self._fail(f"Defect-tracker request error: {str(e)}", evidence={"url": url, "action": action})

        status_ok = response.status_code in accepted_status_codes

        response_body: Any = None
        try:
            response_body = response.json()
        except Exception:
            pass  # non-JSON body isn't itself a failure; extracted fields will just be empty

        response_field_mapping = params.get("response_field_mapping", {})
        extracted_fields: Dict[str, Any] = {}
        if isinstance(response_body, dict) and response_field_mapping:
            for generic_name, dotted_path in response_field_mapping.items():
                extracted_fields[generic_name] = _get_nested(response_body, dotted_path)

        expected_fields = params.get("expected_fields") or (payload.expected or {}).get("fields", {})
        field_mismatches: List[Dict[str, Any]] = []
        if expected_fields:
            for generic_name, expected_value in expected_fields.items():
                actual_value = extracted_fields.get(generic_name)
                if actual_value != expected_value:
                    field_mismatches.append(
                        {"field": generic_name, "expected": expected_value, "actual": actual_value}
                    )

        passed = status_ok and not field_mismatches

        return CapabilityCheckResult(
            capability=self.capability_type,
            passed=passed,
            confidence=1.0 if status_ok else 0.0,
            evidence={
                "url": url,
                "method": method,
                "action": action,
                "status_code": response.status_code,
                "request_body": body,
                "extracted_fields": extracted_fields,
                "field_mismatches": field_mismatches,
            },
            escalate=not passed,
        )

    def _fail(self, msg: str, evidence: Optional[Dict[str, Any]] = None) -> CapabilityCheckResult:
        ev = {"error": msg}
        if evidence:
            ev.update(evidence)
        return CapabilityCheckResult(
            capability=self.capability_type, passed=False, confidence=1.0,
            evidence=ev, escalate=True,
        )
