"""
OS-level interaction — runtime/hooks/interact.py

Thin wrapper over `pyautogui` for mouse/keyboard dispatch. Like
capture.py, the import is deferred into each function body so this
module (and anything that imports it, like agents/vision/executor.py)
stays importable in headless/no-display environments — real dispatch
only happens when a step is actually executed against a live target app.
"""
from __future__ import annotations


class NoDisplayError(RuntimeError):
    """Raised when an interaction is requested but no display is available."""


def _pyautogui():
    try:
        import pyautogui

        pyautogui.FAILSAFE = True
        return pyautogui
    except Exception as e:  # pragma: no cover - exercised only without a display
        raise NoDisplayError(f"pyautogui unavailable: {e}") from e


def click(x: int, y: int) -> None:
    pg = _pyautogui()
    pg.moveTo(x, y, duration=0.15)
    pg.click()


def type_text(text: str, interval: float = 0.02) -> None:
    pg = _pyautogui()
    pg.typewrite(text, interval=interval)


def scroll(amount: int) -> None:
    pg = _pyautogui()
    pg.scroll(amount)


def dom_click(locator) -> None:
    """
    Click primitive for the Playwright DOM-locator path (Phase C / TRD §10)
    -- dispatches through a resolved Locator's own .click(), never a raw
    OS coordinate, for browser targets. Errors are re-raised as
    NoDisplayError so agents/vision/executor.py can fall back to the
    pixel/OCR path using the same contract as the rest of this module.
    """
    try:
        locator.click(timeout=5000)
    except Exception as e:  # pragma: no cover - exercised only against a real/mocked browser
        raise NoDisplayError(f"Playwright click failed: {e}") from e


def dom_fill(locator, text: str) -> None:
    """Type primitive for the Playwright DOM-locator path -- fills via the Locator, not OS keystrokes."""
    try:
        locator.click(timeout=5000)
        locator.fill(text or "", timeout=5000)
    except Exception as e:  # pragma: no cover - exercised only against a real/mocked browser
        raise NoDisplayError(f"Playwright fill failed: {e}") from e


def dom_scroll_into_view(locator) -> None:
    """Scroll primitive for the Playwright DOM-locator path -- per TRD §10, scroll_into_view + wheel, not blind OS scroll."""
    try:
        locator.scroll_into_view_if_needed(timeout=5000)
    except Exception as e:  # pragma: no cover - exercised only against a real/mocked browser
        raise NoDisplayError(f"Playwright scroll_into_view failed: {e}") from e


def browser_back() -> None:
    """
    Sends the OS/browser-standard 'back' shortcut (Alt+Left, honored by
    Chrome/Firefox/Edge on Windows and most Linux browsers) so the UI
    audit runner (orchestrator/ui_audit_runner.py) can return to the
    original page after test-clicking a nav/footer link, without needing
    to track and re-navigate to the original URL.
    """
    pg = _pyautogui()
    pg.hotkey("alt", "left")
