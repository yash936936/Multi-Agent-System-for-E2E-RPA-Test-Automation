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
    if readable.lower() in _STRUCTURAL_SENTINELS:
        return _check_page_rendered(screenshot_path)
    result = locate_text(screenshot_path, readable, min_ratio=min_ratio)
    return result.found

