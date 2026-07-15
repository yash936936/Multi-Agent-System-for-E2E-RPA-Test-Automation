"""
Accessibility adapter — agents/capability/accessibility_adapter.py

Phase L1 (docs/decisions.md, Roadmap.md Phase L): runs a real WCAG
accessibility scan against a target page using axe-core, vendored locally
at vendor/axe-core/axe.min.js (see vendor/axe-core/README.md for
provenance -- deliberately not CDN-loaded, matching AURA's offline-first
posture, docs/decisions.md D-002/D-018).

Mechanically similar to agents/capability/playwright_validator.py: manages
its own Playwright lifecycle (sync API, one browser/context/page per
run() call), rather than sharing runtime/hooks/browser.py's persistent
session -- same disclosed, not-yet-consolidated posture noted in TRD §11.5
for playwright_validator.py. Read-only: navigates, injects axe-core,
reads back violations. No clicking, no typing, no site interaction.

Registered under CapabilityType.ACCESSIBILITY -- see
orchestrator/capability_adapter.py::default_registry().
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

_AXE_CORE_PATH = Path(__file__).resolve().parent.parent.parent / "vendor" / "axe-core" / "axe.min.js"

# axe-core's own impact levels, ordered least to most severe. A scan is
# only marked failed if at least one violation's impact meets or exceeds
# the configured severity_threshold (default "serious") -- "minor"/"moderate"
# issues are still reported in evidence either way, just don't fail the run
# on their own unless the caller explicitly lowers the threshold.
_IMPACT_ORDER = ("minor", "moderate", "serious", "critical")


class AccessibilityAdapter:
    """Phase L1: real WCAG violation scan via a locally-vendored axe-core."""

    capability_type: CapabilityType = CapabilityType.ACCESSIBILITY

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params or {}
        expected = payload.expected or {}

        url = params.get("url") or payload.target
        if not url:
            return self._fail("Missing 'url' (or 'target') to navigate to")

        if not _AXE_CORE_PATH.exists():
            return self._fail(
                f"Vendored axe-core not found at {_AXE_CORE_PATH}. "
                "See vendor/axe-core/README.md to restore it."
            )

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return self._fail(
                "playwright is not installed (it's a core dependency -- try `pip install -e .` "
                "again, or `pip install playwright && playwright install chromium`)."
            )

        timeout_ms = params.get("timeout_ms", 15000)
        tags = params.get("tags")  # e.g. ["wcag2a", "wcag2aa"] -- None means axe-core's own defaults (all rules)
        severity_threshold = expected.get("severity_threshold", params.get("severity_threshold", "serious"))
        if severity_threshold not in _IMPACT_ORDER:
            return self._fail(
                f"severity_threshold must be one of {_IMPACT_ORDER}, got '{severity_threshold}'"
            )

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(url, timeout=timeout_ms)
                    page.add_script_tag(path=str(_AXE_CORE_PATH))

                    run_options = {"runOnly": {"type": "tag", "values": tags}} if tags else {}
                    axe_results = page.evaluate(
                        "(options) => axe.run(document, options)", run_options
                    )
                    return self._evaluate(axe_results, url, severity_threshold)
                finally:
                    browser.close()
        except Exception as e:
            return self._fail(f"Accessibility scan error: {str(e)}", evidence={"url": url})

    def _evaluate(self, axe_results: Dict[str, Any], url: str, severity_threshold: str) -> CapabilityCheckResult:
        violations = axe_results.get("violations", [])
        threshold_index = _IMPACT_ORDER.index(severity_threshold)

        qualifying = [
            v for v in violations
            if v.get("impact") in _IMPACT_ORDER and _IMPACT_ORDER.index(v["impact"]) >= threshold_index
        ]

        summarized = [
            {
                "id": v.get("id"),
                "impact": v.get("impact"),
                "description": v.get("description"),
                "help_url": v.get("helpUrl"),
                "affected_node_count": len(v.get("nodes", [])),
            }
            for v in violations
        ]

        passed = len(qualifying) == 0
        return CapabilityCheckResult(
            capability=self.capability_type,
            passed=passed,
            confidence=1.0,
            evidence={
                "url": url,
                "severity_threshold": severity_threshold,
                "total_violations": len(violations),
                "qualifying_violation_count": len(qualifying),
                "violations": summarized,
                "passes_count": len(axe_results.get("passes", [])),
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
