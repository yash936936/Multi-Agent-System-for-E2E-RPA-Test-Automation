"""
Page grounding — agents/planner/page_grounding.py

Fixes the root cause behind "AURA invents button names that don't
exist": agents/planner/spec_generator.py's generate_spec() previously
sent only the free-text requirement doc to every backend (heuristic,
local LLM, cloud LLM, Hermes) -- confirmed by a full line-by-line read of
that file. None of them ever saw the actual page. Every target_description
was a guess based on the words in the requirement doc, not on anything
real -- so a doc that says "click Search" produces that exact target
whether or not the site has a search feature at all.

This module supplies the missing piece: a best-effort snapshot of what's
*actually* clickable on the target page, taken before spec generation, so
the planner can be told what's really there instead of guessing.

Deliberately reuses existing detection code rather than writing a third
element-finder:
  - agents/vision/dom_locator.py::snapshot_elements() -- the same ARIA-tree
    walk agents/vision/executor.py's DOM path already uses.
  - agents/vision/ui_audit.py's OCR band detection -- the same one
    orchestrator/ui_audit_runner.py's explore/audit loop already uses --
    as a fallback when no live DOM is available (headless/no-Playwright
    environments, matching every other DOM-then-OCR fallback pattern in
    this codebase).

Fails soft, always: any failure (no display, navigation error, OCR
unavailable, an empty page) returns None, never raises. Callers treat
None identically to "grounding wasn't possible" and fall back to the
pre-existing blind-generation behavior -- this is a pure addition, not a
new required dependency, matching this codebase's consistent posture for
every other opt-in enhancement (LLM semantic tie-break, continuous-audit
monitor, DOM-extractor supplement).
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)

# Caps how many element names get sent to the planner -- a large,
# JS-heavy page can have hundreds of ARIA nodes; beyond a few dozen this
# stops being useful grounding and starts being prompt noise/cost with
# diminishing returns. Chosen to comfortably cover a typical nav + hero +
# footer's worth of real interactive elements.
_MAX_ELEMENTS = 60


def snapshot_page_elements(url: str) -> list[str] | None:
    """
    Best-effort: navigates to `url` (or reuses an already-open session at
    that URL) and returns a deduplicated list of real, currently-visible
    interactive elements' accessible names/OCR text -- or None if this
    couldn't be done for any reason. Never raises.
    """
    try:
        from runtime.hooks import browser as browser_hook

        browser_hook.open_url(url)
        page = browser_hook.get_page()
    except Exception as e:
        _logger.info("Page grounding: could not open %r for snapshotting (%s) -- generating without grounding.", url, e)
        return None

    names = _snapshot_via_dom(page)
    if names is None:
        names = _snapshot_via_ocr()

    if not names:
        return None

    # Dedup while preserving first-seen order (stable, human-readable
    # output) rather than using a set directly, which would shuffle order
    # on every call and make prompt diffs noisier than necessary.
    seen: list[str] = []
    for name in names:
        cleaned = name.strip()
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
        if len(seen) >= _MAX_ELEMENTS:
            break
    return seen or None


def _snapshot_via_dom(page) -> list[str] | None:
    """DOM path -- returns None (not []) on any failure, so the caller
    tries OCR next; returns [] only for a genuinely empty-of-elements page,
    which is meaningfully different (nothing to fall back to)."""
    try:
        from agents.vision.dom_locator import snapshot_elements

        elements = snapshot_elements(page)
        return [el["name"] for el in elements if el.get("name")]
    except Exception as e:
        _logger.info("Page grounding: DOM snapshot failed (%s) -- falling back to OCR.", e)
        return None


def _snapshot_via_ocr() -> list[str] | None:
    """
    OCR fallback -- used when no live Playwright page/DOM is available at
    all (matches every other DOM-then-OCR fallback in this codebase).
    Reuses agents/vision/ui_audit.py's existing OCR landmark scan (the
    same one orchestrator/ui_audit_runner.py's explore/audit loop already
    uses) rather than writing a second OCR-based element finder with its
    own tuning -- audit_screenshot()'s interactive_elements property
    already answers exactly "what looks clickable on this page."
    """
    try:
        from runtime.hooks.capture import capture_screenshot
        from agents.vision.ui_audit import audit_screenshot

        screenshot_path = capture_screenshot("page-grounding", 0)
        landmarks = audit_screenshot(str(screenshot_path))
        return [el.text for el in landmarks.interactive_elements if el.text]
    except Exception as e:
        _logger.info("Page grounding: OCR fallback also failed (%s) -- generating without grounding.", e)
        return None
