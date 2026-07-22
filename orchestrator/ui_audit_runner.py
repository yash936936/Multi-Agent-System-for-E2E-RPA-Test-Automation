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

import logging
from dataclasses import dataclass, field
from typing import Callable

from config.settings import settings

from runtime.hooks.capture import file_hash

_logger = logging.getLogger(__name__)

ScreenshotProvider = Callable[[str, int], str]  # (run_id, index) -> screenshot_path


@dataclass
class ClickCheckResult:
    label: str
    band: str
    clicked: bool
    state_changed: bool | None  # None if we couldn't even locate/click it
    # Phase C/D-044: True when the click opened a new tab (target="_blank"
    # or similar) -- AURA closed it and returned, rather than following it
    # deeper. Only ever populated via the DOM-first path (dom_page is not
    # None); the OCR/pixel path has no tab concept, so this stays False
    # there, same as it always implicitly was.
    new_tab_opened: bool = False
    new_tab_url: str | None = None
    resolution_strategy: str = "ocr"  # "dom" | "ocr" | "dom_extractor_direct" -- which path actually resolved/clicked this element


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


def _try_dom_click(page, target_text: str):
    """
    Resolves target_text against the live accessibility tree
    (agents/vision/dom_locator.locate_dom), self-heals once via
    relocate_dom() if the primary threshold misses (Scrapling-style,
    per docs/external_repos.md Batch 6 -- same pattern already used by
    agents/vision/executor.py for spec-driven runs), clicks through the
    resolved Locator, and returns to the original page via the
    Playwright-aware, tab-aware dom_smart_back(). Returns None (never
    raises) on any failure to resolve/click, so the caller falls back to
    the OCR/pixel path exactly as it did before this function existed.
    """
    from agents.vision.dom_locator import locate_dom, relocate_dom
    from runtime.hooks.interact import dom_click, dom_smart_back

    try:
        pages_before = len(page.context.pages)

        located = locate_dom(page, target_text)
        if not located.found:
            located = relocate_dom(page, {"name": target_text})
        if not located.found or located.locator is None:
            return None

        dom_click(located.locator)
        return dom_smart_back(page, pages_before)
    except Exception:
        return None  # any failure here (stale page, navigation mid-click, etc.) -- OCR fallback handles it, same as a plain "couldn't locate" result


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
    from runtime.errors import NoDisplayError, display_guard

    # Debug pass (D-044): this engine previously only used the OCR/pixel
    # path (locate_text + interact.click(x, y) + OS-level browser_back()),
    # even though Phase C added a Playwright DOM-first locator
    # (agents/vision/dom_locator.py) with Scrapling-style self-heal to
    # agents/vision/executor.py for spec-driven `aura execute` runs. That
    # migration never reached `aura explore`/`--ui-audit`, so the
    # zero-instruction exploration mode -- the mode most likely to hit
    # unpredictable real-world pages -- was left on the more fragile,
    # older path. When a live Playwright page is available (browser mode,
    # runtime/hooks/browser.get_page()), this now resolves and clicks
    # through the DOM-first path first, with the exact same OCR/OS
    # fallback as before for anything it can't resolve (native desktop /
    # no accessibility tree, or no active page at all) -- this preserves
    # every existing OCR-only test's behavior unchanged.
    dom_page = None
    try:
        from runtime.hooks import browser as _browser_hook

        if _browser_hook.has_active_page():
            dom_page = _browser_hook.get_page()
    except Exception:
        dom_page = None  # no Playwright/browser session available -- OCR/OS path handles everything, same as before this change

    with display_guard() as guard:
        guard.value = screenshot_provider(run_id, 8000)
    if guard.no_display:
        # No display/screenshot capability at all -- every other real
        # capture site in this pipeline already turns this into a clean
        # escalation/stop rather than an uncaught traceback; this was the
        # one call site in the click-audit engine (shared by both
        # `aura execute --ui-audit` and `aura explore`) that didn't.
        # Return an empty-but-valid report instead of crashing, so callers
        # can render "no display available" instead of a stack trace.
        return UIAuditReport(
            has_nav=False,
            has_hero=False,
            has_footer=False,
            page_issues=["No display available -- UI audit/exploration skipped (headless/no-display environment)."],
            requirement_prompt=requirement_prompt,
        )
    baseline_path = guard.value

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

    # DOM-sourced supplement (agents/vision/dom_extractor.py): OCR-band
    # detection above only sees elements with visible, readable static
    # text at screenshot time -- it structurally misses icon-only
    # controls and custom div/span controls with no rendered label text
    # AURA's OCR pass would recognize. When a live Playwright session is
    # already open (browser.has_active_page()), pull those in too, deduped
    # against the OCR list by (rounded position, text) so a control both
    # paths agree on isn't double-clicked during the audit below.
    dom_sourced_keys: set[tuple[str, int, int]] = set()
    if settings.enable_dom_extractor and dom_page is not None:
        try:
            from agents.vision.dom_extractor import to_ui_elements

            page_height = dom_page.evaluate("document.documentElement.scrollHeight") or 8000
            dom_elements = to_ui_elements(dom_page, page_height)
            existing_keys = {(e.text.strip().lower(), round(e.cx / 12), round(e.cy / 12)) for e in all_elements}
            for de in dom_elements:
                key = (de.text.strip().lower(), round(de.cx / 12), round(de.cy / 12))
                if key not in existing_keys:
                    all_elements.append(de)
                    existing_keys.add(key)
                    dom_sourced_keys.add(key)
        except Exception:
            # Best-effort supplement only -- a DOM-extraction failure (page
            # navigated away, no browser session, JS evaluate error) must
            # never break the OCR-based audit that already succeeded above.
            pass

    candidates = [e for e in all_elements if e.looks_interactive and band_filter(e)][:max_elements]

    from runtime.hooks import interact

    all_seen_text: list[str] = [e.text for e in all_elements]

    for i, element in enumerate(candidates):
        el_cx, el_cy = getattr(element, "cx", 0), getattr(element, "cy", 0)
        element_key = (element.text.strip().lower(), round(el_cx / 12), round(el_cy / 12))
        is_dom_sourced = element_key in dom_sourced_keys

        dom_click_result = _try_dom_click(dom_page, element.text) if dom_page is not None else None

        if dom_click_result is not None:
            # D-044 semantic path resolved and clicked it by accessible
            # name -- works for both OCR-sourced and DOM-extractor-sourced
            # elements whenever the target actually has a matchable name
            # in the accessibility tree.
            resolution_strategy = "dom"
            new_tab_opened = dom_click_result.new_tab_opened
            new_tab_url = dom_click_result.new_tab_url
        else:
            new_tab_opened = False
            new_tab_url = None
            result = locate_text(baseline_path, element.text)
            if result.found:
                click_x, click_y = result.x, result.y
                dispatch_via_playwright = False
                resolution_strategy = "ocr"
            elif is_dom_sourced and el_cx and el_cy and dom_page is not None:
                # Neither D-044's semantic locate_dom() (no accessibility-
                # tree match for this element's name -- expected for a
                # cursor-pointer-only custom control with no ARIA role, see
                # agents/vision/dom_extractor.py's module docstring) nor
                # OCR (no visible/readable label at this exact spot) could
                # resolve this element by name. It still has a real,
                # directly-measured position from getBoundingClientRect()
                # (CSS/viewport space), so dispatch straight to that point
                # via Playwright's own mouse rather than declaring it
                # unreachable just because neither name-based path matched.
                click_x, click_y = el_cx, el_cy
                dispatch_via_playwright = True
                resolution_strategy = "dom_extractor_direct"
            elif el_cx and el_cy:
                # Same direct-coordinate fallback, but in OS/screenshot-
                # pixel space (interact.click's expected space) -- for an
                # OCR-sourced element whose text re-search on this specific
                # baseline screenshot happened to miss, even though its
                # original OCR detection pass did find real coordinates.
                click_x, click_y = el_cx, el_cy
                dispatch_via_playwright = False
                resolution_strategy = "ocr"
            else:
                report.checked.append(ClickCheckResult(label=element.text, band=element.band, clicked=False, state_changed=None))
                continue

            try:
                if dispatch_via_playwright:
                    pages_before = len(dom_page.context.pages)
                    dom_page.mouse.click(click_x, click_y)
                else:
                    # Phase 2 (cursor-coordinate fix, next-phase plan):
                    # click_x/click_y here came from OCR against the
                    # OS-level baseline screenshot (mss full-monitor
                    # capture) -- never valid as a raw OS coordinate for
                    # interact.click (see runtime/hooks/browser.py's
                    # get_click_point_in_page docstring for the root
                    # cause: DPI scaling / multi-monitor offset / window
                    # position all send that number somewhere else on the
                    # real desktop -- the "taskbar jump" bug). Translate
                    # into this page's own CSS/viewport space and dispatch
                    # through Playwright's mouse whenever a live page
                    # exists; only fall back to the raw OS coordinate when
                    # it doesn't (a native, non-browser target) or the
                    # translation itself fails.
                    page_point = _browser_hook.get_click_point_in_page(click_x, click_y) if dom_page is not None else None
                    if page_point is not None:
                        pages_before = len(dom_page.context.pages)
                        dom_page.mouse.click(*page_point)
                        # Reuses the dispatch_via_playwright-gated tab-aware
                        # return (below) and skips the OS-level browser_back
                        # (further below) -- both paths already exist for
                        # exactly this "dispatched via Playwright's mouse"
                        # case, just previously only reachable from the
                        # dom_extractor_direct strategy.
                        dispatch_via_playwright = True
                    else:
                        interact.click(click_x, click_y)
            except NoDisplayError:
                report.checked.append(ClickCheckResult(label=element.text, band=element.band, clicked=False, state_changed=None))
                continue
            except Exception:
                # Playwright mouse.click can raise its own errors (page
                # closed mid-audit, element detached) distinct from
                # NoDisplayError -- treat the same as any other failed
                # dispatch: record as not clicked, keep auditing the rest.
                report.checked.append(ClickCheckResult(label=element.text, band=element.band, clicked=False, state_changed=None))
                continue

            if dispatch_via_playwright:
                # Tab-aware return, same mechanism _try_dom_click() uses
                # internally -- this path bypasses that helper (it clicks
                # by raw coordinate, not by resolved Locator), so the
                # tab-awareness has to be applied explicitly here too.
                from runtime.hooks.interact import dom_smart_back

                smart_back_result = dom_smart_back(dom_page, pages_before)
                new_tab_opened = smart_back_result.new_tab_opened
                new_tab_url = smart_back_result.new_tab_url

        with display_guard() as after_guard:
            after_guard.value = screenshot_provider(run_id, 8100 + i)
        if after_guard.no_display:
            # Display was available for the baseline capture but dropped
            # partway through the audit (or the click itself somehow
            # succeeded in a race against a display disconnect) -- record
            # this element as clicked-but-unverifiable and stop the audit
            # rather than crashing the whole run on the next iteration too.
            report.checked.append(ClickCheckResult(label=element.text, band=element.band, clicked=True, state_changed=None, new_tab_opened=new_tab_opened, new_tab_url=new_tab_url, resolution_strategy=resolution_strategy))
            break
        after_path = after_guard.value
        after_hash = file_hash(after_path)
        # A new tab opening (and being closed again) is itself proof the
        # click worked, even if the original page's own screenshot ends up
        # byte-identical to the baseline -- report it as changed/working
        # rather than an old "no visible change" false negative.
        state_changed = new_tab_opened or (after_hash != baseline_hash)
        report.checked.append(ClickCheckResult(
            label=element.text, band=element.band, clicked=True, state_changed=state_changed,
            new_tab_opened=new_tab_opened, new_tab_url=new_tab_url, resolution_strategy=resolution_strategy,
        ))
        report.page_issues.extend(issue for issue in detect_page_issues(after_path) if issue not in report.page_issues)

        after_landmarks = audit_screenshot(after_path)
        all_seen_text.extend(
            e.text for e in (after_landmarks.nav_elements + after_landmarks.hero_elements + after_landmarks.footer_elements + after_landmarks.body_elements)
        )

        # Best-effort return to the original page before testing the next
        # element. DOM path (resolution_strategy == "dom") and the direct
        # DOM-extractor path already went back via dom_smart_back above --
        # OCR path uses the OS-level shortcut as before *unless* it was
        # actually dispatched via Playwright's mouse (dispatch_via_playwright
        # now covers that case too, see the click dispatch above), in which
        # case dom_smart_back already handled the return and a second
        # OS-level back would be redundant. If the OS shortcut fails (no
        # display, or the shortcut doesn't apply), subsequent locate_text()
        # calls simply fail to find their target and get recorded as
        # clicked=False rather than crashing the whole audit.
        if resolution_strategy == "ocr" and not dispatch_via_playwright:
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
    page_url: str | None = None,
    link_check_scope: str = "all",
) -> UIAuditReport:
    """
    Existing `--ui-audit` behavior: nav + footer bands only, via OCR
    click-and-diff.

    page_url: when given, this now ALSO runs a real HTTP-level link check
    (agents/capability/link_checker.py -- fetches the actual page HTML and
    checks every in-scope <a href>'s real status code) alongside the OCR
    pass, merging into the same UIAuditReport.link_check_result field
    run_exploration() already populates. Previously this capability only
    existed on run_exploration() (`aura explore --check-links`) -- this
    function (what `aura execute --ui-audit` actually calls) had no path
    to it at all, so a normal execute run's --ui-audit never got a real
    link check, only the OCR click-and-diff heuristic, which can't
    reliably tell "the link resolves" from "clicking it produced no
    visible change" (see link_check_result's own docstring above). Reuses
    LinkCheckAdapter directly rather than duplicating its HTTP-fetch/
    parse logic a third time.

    Best-effort: if page_url isn't known or the check itself fails for
    any reason, this degrades to exactly the pre-existing OCR-only
    behavior (link_check_result stays None) rather than blocking or
    failing the whole audit over an optional supplementary check.
    """
    report = _run_click_audit(
        screenshot_provider,
        run_id,
        max_elements,
        band_filter=lambda e: e.band in ("nav", "footer"),
    )

    if page_url:
        try:
            from agents.capability.link_checker import LinkCheckAdapter
            from orchestrator.schemas import CapabilityCheckInput

            # Same fix as run_exploration() below: if this run already has
            # a live, hydrated browser page open (the same session driving
            # the OCR screenshots above), hand its HTML straight to the
            # link checker instead of letting it fall back to launching
            # its own sync_playwright() -- a second sync Playwright
            # instance in the same thread is not supported and silently
            # fails (bare except -> None) every time a run's own browser
            # is already active, which for `aura execute --ui-audit` is
            # always. Without this, a client-rendered page (React/Next.js/
            # etc.) reports "0 links found" -- looking like a clean pass
            # when really no links were ever checked at all.
            live_page_html = None
            try:
                from runtime.hooks import browser as _browser_hook

                if _browser_hook.has_active_page():
                    live_page_html = _browser_hook.get_page().content()
            except Exception:
                live_page_html = None  # best-effort only; adapter falls back to its own standalone render

            params = {"scope": link_check_scope}
            if live_page_html:
                params["live_page_html"] = live_page_html

            adapter = LinkCheckAdapter()
            result = adapter.run(
                CapabilityCheckInput(
                    capability=adapter.capability_type,
                    target=page_url,
                    params=params,
                    expected={},
                )
            )
            report.link_check_result = result.evidence
        except Exception as e:
            _logger.info("run_ui_audit: real link check failed (%s) -- OCR-only audit result stands.", e)

    return report


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
