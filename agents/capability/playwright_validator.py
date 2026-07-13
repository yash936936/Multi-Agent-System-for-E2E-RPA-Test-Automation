"""
Playwright web validator — agents/capability/playwright_validator.py

Implements the "Web App" leg of the trigger/validate pattern documented in
docs/TRD.md §11.4 and docs/Roadmap.md Phase 21b:

    ...
    Automation Anywhere Bot Runs
           |
   +-------+--------+
   v       v        v
Web App  Database  Files      <-- this adapter covers "Web App"
   ^       ^        ^
   |       |        |
 Playwright Validates

This is **strictly read-only**: no clicking, no typing. It launches a
headless Playwright browser, navigates to the target page the bot was
expected to have produced/updated, and asserts against the spec's
`expected` block (text content and/or element presence) via Playwright's
accessibility-tree/DOM query primitives.

Per TRD §11.5, this is a *different* step type from the vision-driven
`visual_click`/`visual_type` actions (§10) — those drive the UI as AURA's
own action-execution path; this validator only observes state *after* an
external system (the AA bot) has already acted. Per §11.5's reconciliation
note, once TRD §10's Playwright locator-resolution work lands, this module
should be updated to reuse that shared browser-session code rather than
maintaining a second independent Playwright integration — that shared
browser-context module does not exist yet, so this module manages its own
Playwright lifecycle for now (sync API, one browser/context/page per
`run()` call, always closed via context managers).

Playwright is an optional dependency (matches the "offline-first exception,
disclosed" carve-out in TRD §11.6 / §9 — this and the AA adapter are
network/process-facing by design). If it isn't installed, this adapter
fails closed with a clear error rather than raising an ImportError up
through the capability router.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType


class PlaywrightValidator:
    """
    Phase 21b: Read-only post-run web-state check. Navigates to a target
    URL and asserts expected text/element presence — never clicks or types.
    """

    capability_type: CapabilityType = CapabilityType.WEB_VALIDATION

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params or {}
        expected = payload.expected or {}

        url = params.get("url") or payload.target
        if not url:
            return self._fail("Missing 'url' (or 'target') to navigate to")

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return self._fail(
                "playwright is not installed — add it as a dependency to use "
                "capability='web_validation' (TRD §11.4 / Roadmap Phase 21b)."
            )

        timeout_ms = params.get("timeout_ms", 15000)
        wait_for_selector = params.get("wait_for_selector")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(url, timeout=timeout_ms)
                    if wait_for_selector:
                        page.wait_for_selector(wait_for_selector, timeout=timeout_ms)

                    return self._evaluate(page, expected)
                finally:
                    browser.close()
        except Exception as e:
            return self._fail(f"Playwright validation error: {str(e)}", evidence={"url": url})

    def _evaluate(self, page: Any, expected: Dict[str, Any]) -> CapabilityCheckResult:
        checks_passed = True
        evidence: Dict[str, Any] = {"url": page.url}

        expected_text = expected.get("contains_text")
        if expected_text:
            page_text = page.content()
            found = expected_text in page_text
            evidence["contains_text_check"] = {"expected": expected_text, "found": found}
            if not found:
                checks_passed = False

        expected_selector = expected.get("selector_present")
        if expected_selector:
            count = page.locator(expected_selector).count()
            present = count > 0
            evidence["selector_present_check"] = {"selector": expected_selector, "present": present}
            if not present:
                checks_passed = False

        expected_selector_text = expected.get("selector_text")
        if expected_selector_text:
            selector = expected_selector_text.get("selector")
            expected_value = expected_selector_text.get("value")
            try:
                actual_value = page.locator(selector).first.text_content(timeout=5000)
            except Exception:
                actual_value = None
            match = actual_value is not None and expected_value in actual_value
            evidence["selector_text_check"] = {
                "selector": selector, "expected": expected_value,
                "actual": actual_value, "match": match,
            }
            if not match:
                checks_passed = False

        if not any([expected.get("contains_text"), expected.get("selector_present"),
                    expected.get("selector_text")]):
            # No assertions supplied — treat a successful navigation as the check.
            evidence["note"] = "No assertions in 'expected'; navigation success only."

        return CapabilityCheckResult(
            capability=self.capability_type,
            passed=checks_passed,
            confidence=1.0,
            evidence=evidence,
            escalate=not checks_passed,
        )

    def _fail(self, msg: str, evidence: Optional[Dict[str, Any]] = None) -> CapabilityCheckResult:
        ev = {"error": msg}
        if evidence:
            ev.update(evidence)
        return CapabilityCheckResult(
            capability=self.capability_type, passed=False, confidence=1.0,
            evidence=ev, escalate=True,
        )
