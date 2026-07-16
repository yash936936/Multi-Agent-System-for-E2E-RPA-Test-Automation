"""
Automation Anywhere trigger/poll adapter — agents/capability/automation_anywhere_adapter.py

Implements the "Trigger Automation Anywhere Bot" + "Automation Anywhere Bot
Runs" legs of the pattern documented in docs/TRD.md §11 and docs/Roadmap.md
Phase 21a:

    Playwright Test Suite
           |
           v
 Trigger Automation Anywhere Bot
  (REST API / Command Line)
           |
           v
  Automation Anywhere Bot Runs
           |
   +-------+--------+
   v       v        v
Web App  Database  Files
   ^       ^        ^
   |       |        |
 Playwright Validates

This adapter only covers the trigger + poll-to-terminal-status part. It is
deliberately opaque to whatever the bot does internally (per TRD §11.2 —
"Opaque to AURA by design") — it never inspects the bot's steps, only its
reported terminal status. The three validation legs (Web App / Database /
Files) are separate adapters: agents/capability/playwright_validator.py
(new, Web App leg) plus the existing db_adapter.py and file_adapter.py
(Database / Files legs, unchanged, reused as-is per TRD §11.2).

Two trigger modes, mirroring the diagram's "REST API / Command Line" label:

- REST mode: posts to the Control Room bot-deployment endpoint
  (`{control_room_url}/v4/automations/deploy`), then polls the returned
  deployment/activity id against the activity-status endpoint
  (`{control_room_url}/v3/activity/list`) until a terminal state.
- CLI mode: invokes the local AAE CLI / Bot Launcher for on-prem runners
  with no Control Room reachable, and watches the process exit code (plus
  an optional log-tail file) until the process ends.

Per TRD §11.3, a `COMPLETED` status alone is not sufficient to mark a run
passed — that cross-check is enforced by RunEngine/the spec, which is
expected to also require at least one of the web/database/file validation
legs to independently confirm the expected end state (TRD §11.6, §11 note
on "no blind trust of bot-reported success"). This adapter's `passed` field
only reflects whether the *trigger and its own execution* reached the
expected terminal status — it does not and cannot see the downstream
systems the bot touched.

Roadmap Phase N (docs/Roadmap.md §10, decisions.md D-035) added two things
to the REST path, both inside this same file per that phase's own framing
("one careful pass through automation_anywhere_adapter.py's request/poll
internals instead of two"):

N1. Control Room authentication — a real login step
    (`{control_room_url}/v1/authentication`) that exchanges a
    username/password or API key for a bearer token, caches it with its
    expiry, and transparently re-authenticates on a 401 during deploy or
    poll instead of failing the whole run. `auth_token` remains a valid,
    optional override for anyone already supplying one directly — additive,
    not a breaking change to the params contract.
N2. Multi-bot / multi-runner trigger — `bot_id` and `run_as_user_id` may
    now be a list as well as a scalar, one deploy request fans out to
    every bot/runner combination named, and the poll loop tracks every
    resulting deployment id independently (a per-target status map, not
    `records[0]`). `expected.rollup` selects `all_must_complete` (default,
    strict) or `any_must_complete` (fan-out redundancy), and evidence
    always carries the full per-target breakdown alongside the rolled-up
    verdict, so a failing target among several successes stays visible.

Roadmap Phase P (decisions.md D-037) added one more thing to this same
file, opt-in and read-only:

P1. Control Room audit log retrieval — once every target has reached a
    terminal state, `params.include_control_room_audit=True` fetches
    Control Room's own audit-log entries for each deployment id (a new
    read-only call; no new write capability). Off by default, so existing
    callers see no added latency unless they ask for it. Best-effort and
    non-fatal: a fetch failure never changes the trigger's own verdict,
    only its own `fetch_error` field.
P2. That data lands under a new `control_room_audit` evidence key (per
    target, and mirrored to the top level for the common single-target
    case) — no separate report-plumbing needed, since `evidence` already
    flows into `ReportAggregator`'s per-step `raw_results.json` via
    `VisionActionResult.capability_result`. One AURA report now contains
    both trails side by side.
"""
from __future__ import annotations

import shlex
import subprocess
import time
from typing import Any, Dict, List, Optional

import httpx

from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

_TERMINAL_STATUSES = ("COMPLETED", "FAILED", "STOPPED", "TIMED_OUT")


class AutomationAnywhereAdapter:
    """
    Phase 21a: Triggers an Automation Anywhere bot (REST Control Room API or
    local CLI/Bot Launcher) and polls until terminal status.

    Phase N adds real Control Room authentication (N1) and multi-bot/
    multi-runner fan-out triggering (N2) to the REST path — see the module
    docstring above for the exact contract.
    """

    capability_type: CapabilityType = CapabilityType.AUTOMATION_ANYWHERE

    def __init__(self) -> None:
        # N1: token cache, keyed by control_room_url so one adapter instance
        # can safely serve multiple tenants across calls. Each entry is
        # {"token": str, "expires_at": float (monotonic)}.
        self._token_cache: Dict[str, Dict[str, Any]] = {}

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params or {}
        expected = payload.expected or {}
        mode = (params.get("mode") or "rest").lower()

        try:
            if mode == "rest":
                return self._run_rest(params, expected)
            elif mode == "cli":
                return self._run_cli(params, expected)
            else:
                return self._fail(f"Unknown mode '{mode}' (expected 'rest' or 'cli')")
        except Exception as e:
            return self._fail(f"Automation Anywhere trigger error: {str(e)}")

    # ------------------------------------------------------------------
    # N1 — Control Room authentication
    # ------------------------------------------------------------------
    def _get_token(self, client: httpx.Client, control_room_url: str, params: Dict[str, Any],
                    force: bool = False) -> Optional[str]:
        """
        Returns a bearer token for control_room_url, preferring (in order):
        1. An explicit `auth_token` override in params (back-compat, never
           cached/refreshed by us -- the caller owns its lifecycle).
        2. A cached, unexpired token from a prior real login on this adapter
           instance.
        3. A fresh login against Control Room's authentication endpoint,
           using `username`/`password` or `api_key` from params.
        `force=True` bypasses the cache (used to re-authenticate on a 401).
        """
        override = params.get("auth_token")
        if override:
            return override

        cache_key = control_room_url
        if not force:
            cached = self._token_cache.get(cache_key)
            if cached and cached["expires_at"] > time.monotonic():
                return cached["token"]

        username = params.get("username")
        password = params.get("password")
        api_key = params.get("api_key")
        if not (api_key or (username and password)):
            # No credentials supplied at all and no override token --
            # proceed unauthenticated (existing pre-Phase-N behavior); the
            # deploy/poll calls will simply be sent without a token and
            # Control Room will reject them if it requires one.
            return None

        auth_url = f"{control_room_url.rstrip('/')}/v1/authentication"
        body = {"apiKey": api_key} if api_key else {"username": username, "password": password}
        auth_response = client.post(auth_url, json=body)
        if auth_response.status_code != 200:
            return None
        auth_body = auth_response.json() if auth_response.content else {}
        token = auth_body.get("token")
        if not token:
            return None

        expires_in = auth_body.get("expiresIn", 3600)
        try:
            expires_in = float(expires_in)
        except (TypeError, ValueError):
            expires_in = 3600.0
        # Refresh a little early rather than racing an exact expiry.
        self._token_cache[cache_key] = {
            "token": token,
            "expires_at": time.monotonic() + max(expires_in - 30.0, 0.0),
        }
        return token

    # ------------------------------------------------------------------
    # REST mode -- Control Room bot-deployment + activity-status polling
    # ------------------------------------------------------------------
    def _run_rest(self, params: Dict[str, Any], expected: Dict[str, Any]) -> CapabilityCheckResult:
        control_room_url = params.get("control_room_url")
        bot_ids = self._as_list(params.get("bot_id"))
        run_as_user_ids = self._as_list(params.get("run_as_user_id"))

        if not control_room_url:
            return self._fail("Missing 'control_room_url' for REST mode")
        if not bot_ids:
            return self._fail("Missing 'bot_id' for REST mode")

        input_variables = params.get("input_variables", {})
        poll_interval_seconds = params.get("poll_interval_seconds", 5)
        timeout_seconds = params.get("timeout_seconds", 600)
        rollup = (expected.get("rollup") or "all_must_complete").lower()
        if rollup not in ("all_must_complete", "any_must_complete"):
            return self._fail(f"Unknown rollup '{rollup}' (expected 'all_must_complete' or 'any_must_complete')")

        deploy_url = f"{control_room_url.rstrip('/')}/v4/automations/deploy"
        status_url = f"{control_room_url.rstrip('/')}/v3/activity/list"

        with httpx.Client(timeout=30.0) as client:
            token = self._get_token(client, control_room_url, params)
            headers = {"X-Authorization": token} if token else {}

            def _deploy_body():
                return {
                    "fileId": bot_ids if len(bot_ids) > 1 else bot_ids[0],
                    "runAsUserIds": run_as_user_ids,
                    "botParameter": {"inputParameters": input_variables},
                }

            deploy_response = client.post(deploy_url, headers=headers, json=_deploy_body())
            if deploy_response.status_code == 401:
                # N1: transparent re-authentication on a 401, one retry,
                # rather than failing the whole run.
                token = self._get_token(client, control_room_url, params, force=True)
                headers = {"X-Authorization": token} if token else {}
                deploy_response = client.post(deploy_url, headers=headers, json=_deploy_body())

            if deploy_response.status_code not in (200, 201, 202):
                return self._fail(
                    f"Bot deployment request failed with status {deploy_response.status_code}",
                    evidence={"deploy_status_code": deploy_response.status_code,
                              "deploy_response": deploy_response.text[:2000]},
                )

            deploy_body = deploy_response.json() if deploy_response.content else {}
            deployment_ids = self._extract_deployment_ids(deploy_body)
            if not deployment_ids:
                return self._fail(
                    "Deployment response did not contain a deploymentId/automationId",
                    evidence={"deploy_response": deploy_body},
                )

            target_status = self._poll_rest_status_multi(
                client, status_url, headers, control_room_url, params,
                deployment_ids, poll_interval_seconds, timeout_seconds,
            )

            # P1 (Roadmap Phase P, decisions.md D-037): once every target
            # has reached a terminal state, optionally fetch Control
            # Room's own audit-log entries for each deployment id. A new
            # read-only call, no new write capability -- opt-in via
            # `include_control_room_audit` (default False) so this phase
            # doesn't add a network round trip and latency to every
            # existing caller that never asked for it.
            audit_by_target: Dict[str, Dict[str, Any]] = {}
            if params.get("include_control_room_audit"):
                for dep_id in deployment_ids:
                    audit_by_target[dep_id], headers = self._fetch_control_room_audit(
                        client, control_room_url, headers, params, dep_id,
                    )

        expected_status = expected.get("terminal_status", "COMPLETED")
        per_target = {
            dep_id: {
                "terminal_status": info["status"],
                "expected_status": expected_status,
                "passed": info["status"] == expected_status,
                "activity_record": info["record"],
                # P2 (Roadmap Phase P): merged in only when P1's fetch was
                # requested -- absent entirely otherwise, rather than a
                # always-present-but-usually-empty key, so existing
                # consumers reading this dict see no shape change unless
                # they actually asked for the audit trail.
                **({"control_room_audit": audit_by_target[dep_id]} if dep_id in audit_by_target else {}),
            }
            for dep_id, info in target_status.items()
        }
        outcomes = [t["passed"] for t in per_target.values()]
        passed = any(outcomes) if rollup == "any_must_complete" else all(outcomes)

        evidence: Dict[str, Any] = {
            "mode": "rest",
            "rollup": rollup,
            "expected_status": expected_status,
            "targets": per_target,
        }
        # Back-compat single-target fields -- unchanged shape for the
        # common (still-scalar) case so existing callers reading these keys
        # directly don't break.
        if len(deployment_ids) == 1:
            only = per_target[deployment_ids[0]]
            evidence["deployment_id"] = deployment_ids[0]
            evidence["terminal_status"] = only["terminal_status"]
            evidence["activity_record"] = only["activity_record"]
            if "control_room_audit" in only:
                evidence["control_room_audit"] = only["control_room_audit"]
        else:
            evidence["deployment_ids"] = deployment_ids

        return CapabilityCheckResult(
            capability=self.capability_type,
            passed=passed,
            confidence=1.0,
            evidence=evidence,
            escalate=not passed,
        )

    # ------------------------------------------------------------------
    # P1 -- Control Room audit log retrieval (Roadmap Phase P, D-037)
    # ------------------------------------------------------------------
    def _fetch_control_room_audit(
        self,
        client: httpx.Client,
        control_room_url: str,
        headers: Dict[str, str],
        params: Dict[str, Any],
        deployment_id: str,
    ) -> tuple[Dict[str, Any], Dict[str, str]]:
        """
        Read-only call to Control Room's own audit-log endpoint for a
        single deployment id, once the poll for that target has already
        reached a terminal state. No new write capability -- this only
        ever GETs/POSTs a filtered list query.

        Best-effort and non-fatal by design: a failure here (network
        error, non-200, unexpected shape) never changes the trigger's own
        `passed`/`escalate` verdict, which was already fully determined by
        the terminal activity status before this is even called. It is
        recorded as its own `fetch_error` instead, so a caller who asked
        for the audit trail and didn't get it can tell the difference
        between "no entries" and "couldn't fetch it."

        Returns `(result_dict, headers)` -- headers are returned back out
        because a 401 here triggers the same one-retry re-authentication
        as the deploy/poll calls, and the (possibly refreshed) headers
        need to flow back to the caller for any further per-target calls
        in the same loop.
        """
        audit_url = f"{control_room_url.rstrip('/')}/v2/auditlog/list"
        body = {"filter": {"operator": "eq", "field": "deploymentId", "value": deployment_id}}

        try:
            response = client.post(audit_url, headers=headers, json=body)
            if response.status_code == 401:
                token = self._get_token(client, control_room_url, params, force=True)
                headers = {"X-Authorization": token} if token else {}
                response = client.post(audit_url, headers=headers, json=body)

            if response.status_code != 200:
                return (
                    {"entries": [], "fetch_error": f"audit log request failed with status {response.status_code}"},
                    headers,
                )

            body_json = response.json() if response.content else {}
            entries = body_json.get("list", []) if isinstance(body_json, dict) else []
            return {"entries": entries, "fetch_error": None}, headers
        except Exception as e:
            # Deliberately broad: this is supplementary, read-only,
            # best-effort data -- any failure to fetch it is reported
            # alongside the (already-determined) real result, not raised.
            return {"entries": [], "fetch_error": f"audit log fetch error: {str(e)}"}, headers

    @staticmethod
    def _as_list(value: Any) -> List[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return [v for v in value if v is not None]
        return [value]

    @staticmethod
    def _extract_deployment_ids(deploy_body: Dict[str, Any]) -> List[str]:
        """
        N2: a fan-out deploy can come back either as a single id
        (`deploymentId`/`automationId`) or a list under `deploymentIds`
        (Control Room's documented shape for multi-target deploys).
        """
        if not isinstance(deploy_body, dict):
            return []
        multi = deploy_body.get("deploymentIds")
        if isinstance(multi, list) and multi:
            return [str(d) for d in multi if d]
        single = deploy_body.get("deploymentId") or deploy_body.get("automationId")
        return [str(single)] if single else []

    def _poll_rest_status_multi(
        self,
        client: httpx.Client,
        status_url: str,
        headers: Dict[str, str],
        control_room_url: str,
        params: Dict[str, Any],
        deployment_ids: List[str],
        poll_interval_seconds: float,
        timeout_seconds: float,
    ) -> Dict[str, Dict[str, Any]]:
        """
        N2: tracks every deployment id independently in a per-target status
        map instead of reading only records[0] and dropping the rest. Stops
        polling a target as soon as it reaches a terminal status; keeps
        polling the remaining ones until all are terminal or the shared
        deadline elapses (each still-pending target then reports TIMED_OUT).
        """
        deadline = time.monotonic() + timeout_seconds
        state: Dict[str, Dict[str, Any]] = {
            dep_id: {"status": None, "record": {}} for dep_id in deployment_ids
        }

        while time.monotonic() < deadline:
            pending = [d for d, s in state.items() if s["status"] is None]
            if not pending:
                break

            status_response = client.post(
                status_url,
                headers=headers,
                json={"filter": {"operator": "in", "field": "deploymentId", "value": pending}},
            )
            if status_response.status_code == 401:
                token = self._get_token(client, control_room_url, params, force=True)
                headers["X-Authorization"] = token or ""
                continue

            if status_response.status_code == 200:
                body = status_response.json()
                records = body.get("list", []) if isinstance(body, dict) else []
                for record in records:
                    dep_id = str(record.get("deploymentId", ""))
                    if dep_id not in state:
                        continue
                    status = str(record.get("status", "")).upper()
                    state[dep_id]["record"] = record
                    if status in _TERMINAL_STATUSES:
                        state[dep_id]["status"] = status

            if any(s["status"] is None for s in state.values()):
                time.sleep(poll_interval_seconds)

        for s in state.values():
            if s["status"] is None:
                s["status"] = "TIMED_OUT"

        return state

    # ------------------------------------------------------------------
    # CLI mode — local AAE CLI / Bot Launcher, on-prem runners
    # ------------------------------------------------------------------
    def _run_cli(self, params: Dict[str, Any], expected: Dict[str, Any]) -> CapabilityCheckResult:
        command = params.get("command")
        if not command:
            return self._fail("Missing 'command' for CLI mode")

        timeout_seconds = params.get("timeout_seconds", 600)
        log_tail_path: Optional[str] = params.get("log_tail_path")

        args = command if isinstance(command, list) else shlex.split(command)

        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as e:
            return CapabilityCheckResult(
                capability=self.capability_type,
                passed=False,
                confidence=1.0,
                evidence={"mode": "cli", "error": "timeout", "command": command},
                escalate=True,
            )

        expected_exit_code = expected.get("exit_code", 0)
        passed = completed.returncode == expected_exit_code

        log_tail = None
        if log_tail_path:
            try:
                with open(log_tail_path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
                    log_tail = "".join(lines[-50:])
            except OSError:
                log_tail = None

        return CapabilityCheckResult(
            capability=self.capability_type,
            passed=passed,
            confidence=1.0,
            evidence={
                "mode": "cli",
                "exit_code": completed.returncode,
                "expected_exit_code": expected_exit_code,
                "stdout_tail": completed.stdout[-2000:] if completed.stdout else "",
                "stderr_tail": completed.stderr[-2000:] if completed.stderr else "",
                "log_tail": log_tail,
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
