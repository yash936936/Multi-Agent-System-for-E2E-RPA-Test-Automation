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


def detect_page_issues(screenshot_path: str) -> list[str]:
    """
    Returns a list of matched issue markers found in the screenshot's OCR
    text (empty list = nothing suspicious detected). Never raises --
    OCR/display failures are treated as "nothing to report" so a single
    bad capture doesn't halt an unattended scroll scan.
    """
    try:
        import pytesseract
        from PIL import Image

        with Image.open(screenshot_path) as img:
            img.load()
            text = pytesseract.image_to_string(img).lower()
    except Exception:
        return []

    return [marker for marker in _ISSUE_MARKERS if marker in text]
