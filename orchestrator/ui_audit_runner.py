"""
Comprehensive UI audit runner — orchestrator/ui_audit_runner.py

The "check everything a professional QA tester would check by default"
mode: classifies the page into nav/hero/footer (agents/vision/ui_audit.py),
then test-clicks every interactive-looking element found in those bands
(skipping the noisy body-text band, where "interactive-looking" heuristics
produce too many false positives), checking whether the click produced any
visible change. An element that produces zero visible change after being
clicked is flagged as "possibly non-functional" -- not a hard failure
(vision-only, no DOM access, so AURA can't be certain something is truly
broken vs. just slow/animated), but exactly the kind of thing a human
tester would flag for a second look.

Same guardrail philosophy as orchestrator/autoscan.py and
orchestrator/guardrails.py: a hard cap on how many elements get clicked,
because an unattended loop needs a stop condition that isn't "trust the
page."
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable

ScreenshotProvider = Callable[[str, int], str]  # (run_id, index) -> screenshot_path


@dataclass
class ClickCheckResult:
    label: str
    band: str
    clicked: bool
    state_changed: bool | None  # None if we couldn't even locate/click it


@dataclass
class UIAuditReport:
    has_nav: bool
    has_hero: bool
    has_footer: bool
    checked: list[ClickCheckResult] = field(default_factory=list)
    page_issues: list[str] = field(default_factory=list)

    @property
    def possibly_broken(self) -> list[ClickCheckResult]:
        return [c for c in self.checked if c.clicked and c.state_changed is False]

    @property
    def unreachable(self) -> list[ClickCheckResult]:
        return [c for c in self.checked if not c.clicked]


def _hash_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run_ui_audit(
    screenshot_provider: ScreenshotProvider,
    run_id: str,
    max_elements: int = 12,
) -> UIAuditReport:
    from agents.vision.locator import locate_text
    from agents.vision.page_health import detect_page_issues
    from agents.vision.ui_audit import audit_screenshot

    baseline_path = screenshot_provider(run_id, 8000)
    landmarks = audit_screenshot(baseline_path)
    baseline_hash = _hash_file(baseline_path)

    report = UIAuditReport(
        has_nav=landmarks.has_nav,
        has_hero=landmarks.has_hero,
        has_footer=landmarks.has_footer,
        page_issues=detect_page_issues(baseline_path),
    )

    # Only test nav + footer elements live-clicking -- hero CTAs are
    # frequently the same as a nav item (e.g. "Sign Up" appears in both),
    # and clicking body-band "interactive-looking" text is where the
    # heuristic false-positive rate is highest. This keeps the audit
    # focused on the landmarks explicitly called out in the feature
    # request (nav, footer) rather than clicking everything indiscriminately.
    candidates = (landmarks.nav_elements + landmarks.footer_elements)
    candidates = [e for e in candidates if e.looks_interactive][:max_elements]

    from runtime.hooks import interact
    from runtime.hooks.interact import NoDisplayError

    for i, element in enumerate(candidates):
        result = locate_text(baseline_path, element.text)
        if not result.found:
            report.checked.append(ClickCheckResult(label=element.text, band=element.band, clicked=False, state_changed=None))
            continue

        try:
            interact.click(result.x, result.y)
        except NoDisplayError:
            report.checked.append(ClickCheckResult(label=element.text, band=element.band, clicked=False, state_changed=None))
            continue

        after_path = screenshot_provider(run_id, 8100 + i)
        after_hash = _hash_file(after_path)
        state_changed = after_hash != baseline_hash
        report.checked.append(ClickCheckResult(label=element.text, band=element.band, clicked=True, state_changed=state_changed))
        report.page_issues.extend(issue for issue in detect_page_issues(after_path) if issue not in report.page_issues)

        # Best-effort return to the original page before testing the next
        # element -- if this fails (no display, or the shortcut doesn't
        # apply), subsequent locate_text() calls will simply fail to find
        # their target and be recorded as clicked=False rather than
        # crashing the whole audit.
        try:
            interact.browser_back()
        except NoDisplayError:
            pass

    return report
