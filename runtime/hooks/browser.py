"""
Browser navigation — runtime/hooks/browser.py

Opens a URL in the system's default browser so AURA can QA-test a live
website the exact same vision-first way it tests a desktop app: once the
page is rendered on screen, the screenshot/OCR/click hooks in capture.py
and interact.py don't know or care that it's a browser tab instead of a
Tkinter window.

Deliberately uses only the stdlib `webbrowser` module -- no Selenium/
Playwright/CDP. Reaching for a DOM-aware driver would quietly turn AURA
into a different (DOM-based) architecture; staying with "control the
whole screen, read it with OCR" keeps this consistent with the rest of
runtime/hooks and adds zero new dependencies (decisions.md D-002/D-005).

Like capture.py and interact.py, imports are deferred and a NoDisplayError
is raised (not a bare exception) when there's no display/browser to launch
against, so agents.vision.* stays importable in headless/test environments.
"""
from __future__ import annotations

import time


class NoDisplayError(RuntimeError):
    """Raised when a browser can't be launched (no display / no browser found)."""


def normalize_url(url: str) -> str:
    """Adds an https:// scheme if the caller passed a bare domain."""
    url = (url or "").strip()
    if not url:
        raise ValueError("normalize_url requires a non-empty url")
    if "://" not in url:
        url = f"https://{url}"
    return url


def _normalize_url(url: str) -> str:
    # Kept as a private alias for internal call sites in this module.
    return normalize_url(url)


def open_url(url: str, wait_seconds: float = 2.5, new_window: bool = False) -> str:
    """
    Opens `url` in the default browser and gives the page a moment to
    render before AURA's next screenshot/locate step runs against it.

    Returns the normalized URL that was opened (e.g. with an https://
    scheme added if the caller/spec omitted one).
    """
    normalized = _normalize_url(url)

    try:
        import webbrowser

        opened = webbrowser.open(normalized, new=1 if new_window else 0)
    except Exception as e:  # pragma: no cover - exercised only without a display/browser
        raise NoDisplayError(f"Could not launch a browser for {normalized!r}: {e}") from e

    if not opened:
        raise NoDisplayError(f"No browser available to open {normalized!r} in this environment.")

    # Best-effort page-load wait. AURA is vision-first with no DOM/network
    # signal to wait on, so this is a fixed settle time (configurable via
    # the wait_seconds arg) rather than a real "page loaded" check --
    # callers testing slow-loading sites should pass a larger value.
    time.sleep(max(0.0, wait_seconds))
    return normalized
