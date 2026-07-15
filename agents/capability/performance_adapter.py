"""
Performance budget adapter — agents/capability/performance_adapter.py

Phase L3 (docs/decisions.md, Roadmap.md Phase L): single-page Navigation
Timing metrics checked against a configurable budget.

Explicitly, permanently out of scope, by design, not by omission:
  - No multi-user load generation of any kind (no concurrency, no
    ramping, no sustained traffic) -- this is one page load, one browser,
    read entirely from the browser's own `performance` API.
  - Not a synthetic-monitoring replacement -- one data point, not a
    trend/percentile series (Phase H's trend analytics is the place for
    tracking a metric's history over time, not this adapter).

Mechanically similar to playwright_validator.py/accessibility_adapter.py:
manages its own Playwright lifecycle (sync API, one browser/context/page
per run() call).

Registered under CapabilityType.PERFORMANCE -- see
orchestrator/capability_adapter.py::default_registry().
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

# Default budget, generously loose (a real caller should tighten these via
# params["budget"] to match their own target's actual requirements) --
# these exist so the adapter has sane behavior even with an empty budget
# dict, not as a recommendation of what's "good" performance.
_DEFAULT_BUDGET_MS = {
    "ttfb_ms": 1000,
    "dom_content_loaded_ms": 3000,
    "load_time_ms": 5000,
    "first_paint_ms": 2500,
}


class PerformanceAdapter:
    """Phase L3: single-page Navigation Timing budget check. Not load testing."""

    capability_type: CapabilityType = CapabilityType.PERFORMANCE

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
                "playwright is not installed (it's a core dependency -- try `pip install -e .` "
                "again, or `pip install playwright && playwright install chromium`)."
            )

        timeout_ms = params.get("timeout_ms", 30000)
        budget = expected.get("budget", params.get("budget", _DEFAULT_BUDGET_MS))

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto(url, timeout=timeout_ms, wait_until="load")
                    metrics = self._collect_metrics(page)
                    return self._evaluate(metrics, url, budget)
                finally:
                    browser.close()
        except Exception as e:
            return self._fail(f"Performance check error: {str(e)}", evidence={"url": url})

    def _collect_metrics(self, page: Any) -> Dict[str, float]:
        raw = page.evaluate(
            """
            () => {
                const nav = performance.getEntriesByType('navigation')[0];
                const paints = performance.getEntriesByType('paint');
                const firstPaint = paints.find(p => p.name === 'first-paint');
                const fcp = paints.find(p => p.name === 'first-contentful-paint');
                return {
                    ttfb_ms: nav ? nav.responseStart - nav.requestStart : null,
                    dom_content_loaded_ms: nav ? nav.domContentLoadedEventEnd - nav.startTime : null,
                    load_time_ms: nav ? nav.loadEventEnd - nav.startTime : null,
                    first_paint_ms: firstPaint ? firstPaint.startTime : null,
                    first_contentful_paint_ms: fcp ? fcp.startTime : null,
                };
            }
            """
        )
        return {k: v for k, v in raw.items() if v is not None}

    def _evaluate(self, metrics: Dict[str, float], url: str, budget: Dict[str, float]) -> CapabilityCheckResult:
        violations = {}
        for metric_name, max_ms in budget.items():
            actual = metrics.get(metric_name)
            if actual is not None and actual > max_ms:
                violations[metric_name] = {"actual_ms": round(actual, 1), "budget_ms": max_ms}

        passed = len(violations) == 0

        return CapabilityCheckResult(
            capability=self.capability_type,
            passed=passed,
            confidence=1.0,
            evidence={
                "url": url,
                "metrics_ms": {k: round(v, 1) for k, v in metrics.items()},
                "budget_ms": budget,
                "violations": violations,
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
