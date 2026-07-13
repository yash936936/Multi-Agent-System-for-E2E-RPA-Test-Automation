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
"""
from __future__ import annotations

import shlex
import subprocess
import time
from typing import Any, Dict, Optional

import httpx

from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType


class AutomationAnywhereAdapter:
    """
    Phase 21a: Triggers an Automation Anywhere bot (REST Control Room API or
    local CLI/Bot Launcher) and polls until terminal status.
    """

    capability_type: CapabilityType = CapabilityType.AUTOMATION_ANYWHERE

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
    # REST mode — Control Room bot-deployment + activity-status polling
    # ------------------------------------------------------------------
    def _run_rest(self, params: Dict[str, Any], expected: Dict[str, Any]) -> CapabilityCheckResult:
        control_room_url = params.get("control_room_url")
        bot_id = params.get("bot_id")
        run_as_user_id = params.get("run_as_user_id")
        auth_token = params.get("auth_token")

        if not control_room_url:
            return self._fail("Missing 'control_room_url' for REST mode")
        if not bot_id:
            return self._fail("Missing 'bot_id' for REST mode")

        input_variables = params.get("input_variables", {})
        poll_interval_seconds = params.get("poll_interval_seconds", 5)
        timeout_seconds = params.get("timeout_seconds", 600)

        headers = {"X-Authorization": auth_token} if auth_token else {}
        deploy_url = f"{control_room_url.rstrip('/')}/v4/automations/deploy"
        status_url_template = f"{control_room_url.rstrip('/')}/v3/activity/list"

        with httpx.Client(timeout=30.0) as client:
            deploy_response = client.post(
                deploy_url,
                headers=headers,
                json={
                    "fileId": bot_id,
                    "runAsUserIds": [run_as_user_id] if run_as_user_id else [],
                    "botParameter": {"inputParameters": input_variables},
                },
            )
            if deploy_response.status_code not in (200, 201, 202):
                return self._fail(
                    f"Bot deployment request failed with status {deploy_response.status_code}",
                    evidence={"deploy_status_code": deploy_response.status_code,
                              "deploy_response": deploy_response.text[:2000]},
                )

            deploy_body = deploy_response.json() if deploy_response.content else {}
            deployment_id = deploy_body.get("deploymentId") or deploy_body.get("automationId")
            if not deployment_id:
                return self._fail(
                    "Deployment response did not contain a deploymentId/automationId",
                    evidence={"deploy_response": deploy_body},
                )

            terminal_status, activity_record = self._poll_rest_status(
                client, status_url_template, headers, deployment_id,
                poll_interval_seconds, timeout_seconds,
            )

        expected_status = expected.get("terminal_status", "COMPLETED")
        passed = terminal_status == expected_status

        return CapabilityCheckResult(
            capability=self.capability_type,
            passed=passed,
            confidence=1.0,
            evidence={
                "mode": "rest",
                "deployment_id": deployment_id,
                "terminal_status": terminal_status,
                "expected_status": expected_status,
                "activity_record": activity_record,
            },
            escalate=not passed,
        )

    def _poll_rest_status(
        self,
        client: httpx.Client,
        status_url: str,
        headers: Dict[str, str],
        deployment_id: str,
        poll_interval_seconds: float,
        timeout_seconds: float,
    ) -> tuple[str, Dict[str, Any]]:
        deadline = time.monotonic() + timeout_seconds
        last_record: Dict[str, Any] = {}

        while time.monotonic() < deadline:
            status_response = client.post(
                status_url,
                headers=headers,
                json={"filter": {"operator": "eq", "field": "deploymentId", "value": deployment_id}},
            )
            if status_response.status_code == 200:
                body = status_response.json()
                records = body.get("list", []) if isinstance(body, dict) else []
                if records:
                    last_record = records[0]
                    status = str(last_record.get("status", "")).upper()
                    if status in ("COMPLETED", "FAILED", "STOPPED", "TIMED_OUT"):
                        return status, last_record
            time.sleep(poll_interval_seconds)

        return "TIMED_OUT", last_record

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
