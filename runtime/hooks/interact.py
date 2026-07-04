"""
OS-level interaction — runtime/hooks/interact.py

Thin wrapper over `pyautogui` for mouse/keyboard dispatch. Like
capture.py, the import is deferred into each function body so this
module (and anything that imports it, like agents/vision/executor.py)
stays importable in headless/no-display environments — real dispatch
only happens when a step is actually executed against a live target app.
"""
from __future__ import annotations

import os


class NoDisplayError(RuntimeError):
    """Raised when an interaction is requested but no display is available."""


def _dry_run() -> bool:
    """
    True when real OS-level dispatch must not happen -- set by tests
    (see tests/conftest.py) so that running the suite on a machine with
    a live desktop session (Windows dev box, etc.) never moves the real
    mouse or types on the real keyboard. `import pyautogui` succeeding is
    NOT a reliable signal for "safe to dispatch": on Windows it succeeds
    any time a user is logged in, live display or not.
    """
    return os.environ.get("AURA_DISABLE_DISPATCH") == "1"


def _pyautogui():
    try:
        import pyautogui

        pyautogui.FAILSAFE = True
        return pyautogui
    except Exception as e:  # pragma: no cover - exercised only without a display
        raise NoDisplayError(f"pyautogui unavailable: {e}") from e


def click(x: int, y: int) -> None:
    if _dry_run():
        return
    pg = _pyautogui()
    pg.moveTo(x, y, duration=0.15)
    pg.click()


def type_text(text: str, interval: float = 0.02) -> None:
    if _dry_run():
        return
    pg = _pyautogui()
    pg.typewrite(text, interval=interval)


def scroll(amount: int) -> None:
    if _dry_run():
        return
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
    if _dry_run():
        return
    pg = _pyautogui()
    pg.hotkey("alt", "left")