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
