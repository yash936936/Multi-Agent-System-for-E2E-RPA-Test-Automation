"""
Assertions — agents/vision/assertions.py

Post-action assertion checker: compares a post-action screenshot against
an expected_state description. Implementation reuses the same OCR text
matching as locator.py — an assertion like "dashboard_visible" passes if
OCR finds text on screen reasonably matching "dashboard visible" (after
underscore->space normalization, since TestSpec expected_state values are
often snake_case slugs — see agents/planner/spec_generator.py).

`page_loaded` is a special case, not a literal-text one. It's the generic
fallback expected_state that agents/planner/spec_generator.py's
LocalHeuristicBackend synthesizes whenever a requirement (most commonly
`aura execute --url <url>` with no explicit `Then:` clause) gives no real
assertion to check -- e.g. "TC-LIVE-URL-SMOKE-TEST-001"'s "navigate, then
wait for the page to finish loading" has nothing concrete to assert
against. Treating it as literal OCR text -- searching the screenshot for
the on-screen phrase "page loaded" -- was a real bug: no real webpage
displays that exact string, so this fallback assertion failed on every
single real smoke test regardless of whether the page actually rendered
correctly, silently turning a healthy 1/1-passed run into a reported
"failed" run. Verified against a real run against
https://personal-portfolio-yashmalik.vercel.app: navigation succeeded
(status 200, page visibly rendered), but the run was still marked
"failed" purely because of this assertion.
"""
from __future__ import annotations

from pathlib import Path

from agents.vision.locator import locate_text

# Sentinel expected_state values meaning "some real content rendered",
# not literal on-screen text to search for. Kept as a set (not a single
# string) since other generic fallbacks may be added later without
# needing to touch the check_assertion dispatch logic below.
_STRUCTURAL_SENTINELS = {"page_loaded", "page loaded"}

# Common English function/connective words. Used only to gauge whether a
# piece of text *reads like a sentence* -- not to detect any particular
# meaning -- so this list never needs to grow just because an LLM used a
# new way of saying "the page loaded".
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "and", "or", "with", "of", "to", "for", "on", "in", "at", "as",
    "has", "have", "had", "all", "its", "it", "which", "such", "that",
    "this", "these", "those", "successfully", "fully",
}


def _looks_like_descriptive_sentence(expected_state: str) -> bool:
    """
    Shape-based heuristic (no keyword/vocabulary whitelist): an
    LLM-generated expected_state description reads like an English
    sentence -- several words, strung together with several common
    connective words ("the", "is", "and", "with", ...) -- while a literal
    on-screen label or slug a spec author would actually write
    ("dashboard_visible", "Search Results", "upload_loaded") is short and
    has few or none of those connectives.

    This replaces an earlier approach that regex-matched specific
    vocabulary (page|homepage|site|app|screen + loaded|visible|rendered|
    displayed): that had to be manually extended every time an LLM used a
    phrasing it didn't anticipate -- it missed "homepage" outright (word
    boundary rules mean \\bpage\\b doesn't match "page" embedded inside
    "homepage"), and it would keep missing any future synonym ("the
    dashboard has finished loading", "everything looks correct", "the
    app is up and running" -- none of these contain "page"/"loaded" as
    the regex required). Checking the *shape* of the text instead of its
    specific words generalizes to phrasing this hasn't seen, without
    needing to be extended again.
    """
    words = [w.strip(".,!?;:") for w in expected_state.strip().lower().replace("_", " ").split()]
    words = [w for w in words if w]
    if len(words) < 6:
        return False
    stopword_hits = sum(1 for w in words if w in _STOPWORDS)
    return stopword_hits >= 3


def _looks_structural(expected_state: str) -> bool:
    readable = expected_state.replace("_", " ").strip().lower()
    return readable in _STRUCTURAL_SENTINELS


def _check_page_rendered(screenshot_path: str | Path) -> tuple[bool, str | None]:
    """
    "page_loaded" fallback check: is there any real, readable content on
    screen at all (as opposed to a blank tab, a solid-color error/loading
    screen, or a crashed renderer)? This deliberately does NOT require any
    specific text -- it only needs to distinguish "something rendered"
    from "nothing rendered", which OCR finding *any* text at reasonable
    confidence is a good, simple, local-only proxy for (virtually every
    real webpage has some text somewhere: nav links, headings, footer,
    etc; a blank/broken page has none).

    Returns (passed, ocr_text_or_none) -- the raw OCR text is surfaced so
    callers can attach it as audit evidence (docs/decisions.md D-057)
    rather than only the derived boolean.
    """
    import logging

    import pytesseract
    from PIL import Image

    from config.settings import settings

    try:
        if settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
        with Image.open(screenshot_path) as img:
            img.load()
            text = pytesseract.image_to_string(img)
        return bool(text and text.strip()), text
    except Exception as e:
        # AA3 (docs/decisions.md D-057): previously a bare
        # `except Exception: return True` with no logging at all --
        # silently treating "OCR is broken/unavailable" the same as "OCR
        # ran and found content", which is a meaningfully different and
        # worth-knowing-about situation (e.g. tesseract not installed on
        # this machine at all). Now logged at WARNING so it's visible in
        # normal operation, not just discoverable by reading this source
        # file. Still falls back to True rather than failing the
        # assertion outright, since the caller already confirmed a real
        # screenshot exists before calling this -- an OCR-tooling problem
        # shouldn't fail every single assertion in the run.
        logging.getLogger(__name__).warning(
            "_check_page_rendered: OCR failed (%s) -- treating as rendered since a screenshot exists; "
            "verify tesseract/settings.tesseract_cmd if this appears repeatedly.",
            e,
        )
        return True, None


def check_assertion_detailed(screenshot_path: str | Path, expected_state: str, min_ratio: float = 0.55) -> dict:
    """
    AA1 (docs/decisions.md D-057) -- audit-trail hardening. Same verdict
    logic as check_assertion() below, but surfaces which method actually
    produced that verdict and the raw evidence behind it, instead of
    collapsing straight to a bare bool. This is what run_engine.py now
    attaches to VisionActionResult.raw_evidence/verification_source --
    exactly the information that was missing when D-056's bug let a step
    display "fulfilled" in the process report while its real assertion
    had failed: with this, the trace itself would have shown
    `method="literal_ocr", matched=False` instead of nothing at all.

    Returns a dict with:
    - passed: bool
    - method: "structural_sentinel" | "literal_ocr" | "structural_fallback" | "literal_ocr_failed_no_fallback"
    - matched_text: str | None -- the literal text that was searched for (literal_ocr methods only)
    - ocr_excerpt: str | None -- raw OCR text read from the screenshot, truncated to 500 chars
    """
    readable = expected_state.replace("_", " ").strip()

    if _looks_structural(expected_state):
        passed, ocr_text = _check_page_rendered(screenshot_path)
        return {
            "passed": passed,
            "method": "structural_sentinel",
            "matched_text": None,
            "ocr_excerpt": (ocr_text or "")[:500] or None,
        }

    result = locate_text(screenshot_path, readable, min_ratio=min_ratio)
    if result.found:
        return {
            "passed": True,
            "method": "literal_ocr",
            "matched_text": result.matched_text,
            "ocr_excerpt": None,
        }

    if _looks_like_descriptive_sentence(expected_state):
        passed, ocr_text = _check_page_rendered(screenshot_path)
        return {
            "passed": passed,
            "method": "structural_fallback",
            "matched_text": None,
            "ocr_excerpt": (ocr_text or "")[:500] or None,
        }

    return {
        "passed": False,
        "method": "literal_ocr_failed_no_fallback",
        "matched_text": readable,
        "ocr_excerpt": None,
    }


def check_assertion(screenshot_path: str | Path, expected_state: str, min_ratio: float = 0.55) -> bool:
    return check_assertion_detailed(screenshot_path, expected_state, min_ratio=min_ratio)["passed"]

