"""
Page health check — agents/vision/page_health.py

A generic, assertion-free check used by the autonomous scroll scan
(orchestrator/autoscan.py): reads whatever text is visible on screen via
OCR and flags common error/broken-page indicators. This is deliberately
shallow (substring matching on OCR text, not semantic understanding) --
its job is to catch obviously broken states (404s, stack traces, "access
denied") while scrolling through a page unattended, not to replace a real
written assertion for something specific.
"""
from __future__ import annotations

import logging

_ISSUE_MARKERS = [
    "404",
    "403 forbidden",
    "500 internal server error",
    "502 bad gateway",
    "503 service unavailable",
    "page not found",
    "not found",
    "internal server error",
    "access denied",
    "forbidden",
    "something went wrong",
    "an error occurred",
    "application error",
    "service unavailable",
    "this site can't be reached",
    "connection refused",
]


def detect_page_issues_detailed(screenshot_path: str) -> tuple[list[str], bool]:
    """
    Same matching as detect_page_issues(), but also returns whether OCR
    actually ran (`ocr_checked`). This is the fix for D-057's sibling bug
    in this module: `detect_page_issues` alone returns `[]` both when OCR
    ran and found nothing suspicious *and* when OCR itself failed (e.g.
    tesseract not installed) -- indistinguishable to any caller. Callers
    that need to tell "checked, found clean" apart from "couldn't check"
    (orchestrator/autoscan.py, orchestrator/ui_audit_runner.py) should use
    this instead and surface `ocr_checked=False` distinctly rather than
    silently reporting a clean page.

    Returns (issues, ocr_checked) -- ocr_checked is False only when OCR
    itself raised; issues is always [] in that case.
    """
    try:
        import pytesseract
        from PIL import Image

        with Image.open(screenshot_path) as img:
            img.load()
            text = pytesseract.image_to_string(img).lower()
    except Exception as e:
        logging.getLogger(__name__).warning(
            "page_health: OCR failed reading %s (%s) -- reporting no issue markers found, "
            "but this is 'couldn't check', not 'checked and found none clean'.",
            screenshot_path, e,
        )
        return [], False

    return [marker for marker in _ISSUE_MARKERS if marker in text], True


def detect_page_issues(screenshot_path: str) -> list[str]:
    """
    Returns a list of matched issue markers found in the screenshot's OCR
    text (empty list = nothing suspicious detected). Never raises --
    OCR/display failures are treated as "nothing to report" so a single
    bad capture doesn't halt an unattended scroll scan.

    Kept for backward compatibility (existing call sites/tests that only
    need the marker list). Prefer detect_page_issues_detailed() for any
    new caller that needs to distinguish "checked, found clean" from
    "couldn't check" -- see its docstring.
    """
    issues, _ocr_checked = detect_page_issues_detailed(screenshot_path)
    return issues
