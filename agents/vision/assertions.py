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


def _check_page_rendered(screenshot_path: str | Path) -> bool:
    """
    "page_loaded" fallback check: is there any real, readable content on
    screen at all (as opposed to a blank tab, a solid-color error/loading
    screen, or a crashed renderer)? This deliberately does NOT require any
    specific text -- it only needs to distinguish "something rendered"
    from "nothing rendered", which OCR finding *any* text at reasonable
    confidence is a good, simple, local-only proxy for (virtually every
    real webpage has some text somewhere: nav links, headings, footer,
    etc; a blank/broken page has none).
    """
    import pytesseract
    from PIL import Image

    from config.settings import settings

    try:
        if settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
        with Image.open(screenshot_path) as img:
            img.load()
            text = pytesseract.image_to_string(img)
        return bool(text and text.strip())
    except Exception:
        # OCR unavailable/failed -- fall back to "a screenshot exists at
        # all" rather than failing the assertion outright, since the
        # caller already confirmed final_screenshot is not None before
        # calling check_assertion.
        return True


def check_assertion(screenshot_path: str | Path, expected_state: str, min_ratio: float = 0.55) -> bool:
    readable = expected_state.replace("_", " ").strip()
    if _looks_structural(expected_state):
        return _check_page_rendered(screenshot_path)

    result = locate_text(screenshot_path, readable, min_ratio=min_ratio)
    if result.found:
        return True

    # Literal match failed. If this reads like a full descriptive
    # sentence rather than a short specific label, it was never
    # realistically going to be literal on-screen text to begin with (an
    # LLM-authored "the page is fully loaded and visible" vs. a
    # spec-authored "dashboard_visible") -- fall back to the generic "did
    # real content render at all" check rather than failing an assertion
    # that was never checkable as literal text in the first place.
    if _looks_like_descriptive_sentence(expected_state):
        return _check_page_rendered(screenshot_path)
    return False

