"""
Comprehensive UI audit runner — orchestrator/ui_audit_runner.py

The "check everything a professional QA tester would check by default"
mode: classifies the page into nav/hero/footer (agents/vision/ui_audit.py),
then test-clicks interactive-looking elements, checking whether the click
produced any visible change. An element that produces zero visible change
after being clicked is flagged as "possibly non-functional" -- not a hard
failure (vision-only, no DOM access, so AURA can't be certain something is
truly broken vs. just slow/animated), but exactly the kind of thing a
human tester would flag for a second look.

Two entry points, sharing one engine (`_run_click_audit`):
  - run_ui_audit(): the existing `aura execute --ui-audit` behavior --
    nav + footer bands only, folded into a regular spec-driven run's
    HTML report.
  - run_exploration(): `aura explore <url>` -- every interactive-looking
    element on the page (nav + hero + footer + body), zero spec required.
    This is the literal "give it a URL and it behaves like a QA tester
    with no instructions" mode.

Same guardrail philosophy as orchestrator/autoscan.py and
orchestrator/guardrails.py: a hard cap on how many elements get clicked,
because an unattended loop needs a stop condition that isn't "trust the
page."
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from runtime.hooks.capture import file_hash

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
    # Populated only by run_exploration() when a --prompt requirement was
    # given -- a best-effort, disclosed-as-heuristic note on whether any
    # checked element/page text appears to satisfy it. This is a keyword
    # match, not real language understanding; see run_exploration()'s
    # docstring for exactly what it can and can't tell you.
    requirement_prompt: str | None = None
    requirement_match: bool | None = None
    requirement_notes: list[str] = field(default_factory=list)
    # Real, HTTP-level link verification (agents/capability/link_checker.py),
    # populated only when run_exploration() is given a `link_check_scope`.
    # Deliberately separate from `checked` (the OCR click-and-diff list):
    # a click-and-diff check on a broken link that still renders SOME page
    # (e.g. a custom 404 template) looks identical to a working navigation,
    # so it can't reliably answer "does this link's target actually
    # resolve" the way a real HTTP status check can.
    link_check_result: dict | None = None

    @property
    def possibly_broken(self) -> list[ClickCheckResult]:
        return [c for c in self.checked if c.clicked and c.state_changed is False]

    @property
    def unreachable(self) -> list[ClickCheckResult]:
        return [c for c in self.checked if not c.clicked]


def _run_click_audit(
    screenshot_provider: ScreenshotProvider,
    run_id: str,
    max_elements: int,
    band_filter: Callable[["object"], bool],
    requirement_prompt: str | None = None,
) -> UIAuditReport:
    from agents.vision.locator import locate_text
    from agents.vision.page_health import detect_page_issues
    from agents.vision.ui_audit import audit_screenshot

    baseline_path = screenshot_provider(run_id, 8000)
    landmarks = audit_screenshot(baseline_path)
    baseline_hash = file_hash(baseline_path)

    report = UIAuditReport(
        has_nav=landmarks.has_nav,
        has_hero=landmarks.has_hero,
        has_footer=landmarks.has_footer,
        page_issues=detect_page_issues(baseline_path),
        requirement_prompt=requirement_prompt,
    )

    all_elements = landmarks.nav_elements + landmarks.hero_elements + landmarks.footer_elements + landmarks.body_elements
    candidates = [e for e in all_elements if e.looks_interactive and band_filter(e)][:max_elements]

    from runtime.hooks import interact
    from runtime.hooks.interact import NoDisplayError

    all_seen_text: list[str] = [e.text for e in all_elements]

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
        after_hash = file_hash(after_path)
        state_changed = after_hash != baseline_hash
        report.checked.append(ClickCheckResult(label=element.text, band=element.band, clicked=True, state_changed=state_changed))
        report.page_issues.extend(issue for issue in detect_page_issues(after_path) if issue not in report.page_issues)

        after_landmarks = audit_screenshot(after_path)
        all_seen_text.extend(
            e.text for e in (after_landmarks.nav_elements + after_landmarks.hero_elements + after_landmarks.footer_elements + after_landmarks.body_elements)
        )

        # Best-effort return to the original page before testing the next
        # element -- if this fails (no display, or the shortcut doesn't
        # apply), subsequent locate_text() calls will simply fail to find
        # their target and be recorded as clicked=False rather than
        # crashing the whole audit.
        try:
            interact.browser_back()
        except NoDisplayError:
            pass

    if requirement_prompt:
        report.requirement_match, report.requirement_notes = _check_requirement_prompt(
            requirement_prompt, all_seen_text, report
        )

    return report


def _check_requirement_prompt(prompt: str, seen_text: list[str], report: UIAuditReport) -> tuple[bool, list[str]]:
    """
    Heuristic, keyword-level check of whether the exploration run appears
    to have covered a specific requirement (e.g. "check that clicking
    Sign Up opens a form"). This is deliberately conservative and
    disclosed as a heuristic in every place it's surfaced (CLI output,
    HTML report) -- it is NOT semantic understanding of the prompt, just
    a signal for "did anything relevant get touched."
    """
    prompt_words = {w.strip(".,!?").lower() for w in prompt.split() if len(w) > 3}
    seen_lower = " ".join(seen_text).lower()
    matched_words = sorted(w for w in prompt_words if w in seen_lower)

    notes: list[str] = []
    if matched_words:
        notes.append(
            f"Found on-screen text overlapping the request ({', '.join(matched_words[:6])}) -- "
            "review the click log above to confirm the relevant element was actually exercised."
        )
    else:
        notes.append(
            "No on-screen text overlapping the request was found during exploration -- "
            "the described element/flow may not exist on this page, or may use different wording."
        )

    matched = bool(matched_words) and not report.possibly_broken
    return matched, notes


def run_ui_audit(
    screenshot_provider: ScreenshotProvider,
    run_id: str,
    max_elements: int = 12,
) -> UIAuditReport:
    """Existing `--ui-audit` behavior: nav + footer bands only."""
    return _run_click_audit(
        screenshot_provider,
        run_id,
        max_elements,
        band_filter=lambda e: e.band in ("nav", "footer"),
    )


def run_exploration(
    screenshot_provider: ScreenshotProvider,
    run_id: str,
    max_elements: int = 25,
    requirement_prompt: str | None = None,
    page_url: str | None = None,
    link_check_scope: str | None = None,
) -> UIAuditReport:
    """
    `aura explore <url>` -- the zero-instruction mode. Every
    interactive-looking element on the page (nav, hero, footer, and body)
    is a candidate, up to `max_elements`, instead of just nav/footer.
    This is the same click-and-diff engine as run_ui_audit(), generalized
    per the "explore" feature request: no spec, no target description,
    just a URL and (optionally) a plain-English requirement to keep an
    eye out for while exploring.

    page_url / link_check_scope: when page_url is provided, this also runs
    a real HTTP-level link check (agents/capability/link_checker.py) --
    not just the OCR click-and-diff heuristic above -- scoped to
    link_check_scope ("footer" | "nav" | "all", default "all" whenever
    page_url is given, so every navigable link on the page gets a real
    status check, not just the footer). This is the decisive, real-status
    -code answer to "are the links actually working," which click-and-diff
    alone can't reliably give (see UIAuditReport.link_check_result's
    docstring).
    """
    report = _run_click_audit(
        screenshot_provider,
        run_id,
        max_elements,
        band_filter=lambda e: True,
        requirement_prompt=requirement_prompt,
    )

    if page_url:
        from agents.capability.link_checker import LinkCheckAdapter
        from orchestrator.schemas import CapabilityCheckInput

        adapter = LinkCheckAdapter()
        result = adapter.run(
            CapabilityCheckInput(
                capability=adapter.capability_type,
                target=page_url,
                params={"scope": link_check_scope or "all"},
                expected={},
            )
        )
        report.link_check_result = result.evidence

    return report
