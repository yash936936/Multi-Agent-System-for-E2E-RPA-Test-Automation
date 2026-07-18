"""
OS-level interaction — runtime/hooks/interact.py

Thin wrapper over `pyautogui` for mouse/keyboard dispatch. Like
capture.py, the import is deferred into each function body so this
module (and anything that imports it, like agents/vision/executor.py)
stays importable in headless/no-display environments — real dispatch
only happens when a step is actually executed against a live target app.

Phase S (decisions.md D-040): NoDisplayError is now the one shared class
from runtime.errors, not a module-local lookalike -- see runtime/errors.py.
"""
from __future__ import annotations

from runtime.errors import NoDisplayError

__all__ = ["NoDisplayError"]  # re-exported for existing `from runtime.hooks.interact import NoDisplayError` call sites


def _pyautogui():
    try:
        import pyautogui

        pyautogui.FAILSAFE = True
        return pyautogui
    except SystemExit as e:
        # mouseinfo (a pyautogui dependency) calls sys.exit(...) directly
        # at import time when tkinter isn't installed on Linux, instead of
        # raising a normal ImportError. SystemExit is a BaseException, not
        # an Exception, so it isn't caught below and previously killed the
        # whole process silently (no traceback, just exit code 1) instead
        # of surfacing as the same NoDisplayError every other no-display
        # condition in this module already produces. Converting it here
        # means every caller (autoscan.py, ui_audit_runner.py,
        # agents/vision/executor.py) gets the graceful fallback it already
        # expects, instead of the process dying underneath it.
        raise NoDisplayError(f"pyautogui unavailable (tkinter missing -- see mouseinfo's message: {e}))") from e
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

    Kept as the fallback path for the OCR/pixel pipeline only. When a live
    Playwright page is available, dom_smart_back() below is used instead --
    see its docstring for why this OS-level shortcut can't reliably handle
    a target="_blank" link (decisions.md D-044).
    """
    pg = _pyautogui()
    pg.hotkey("alt", "left")


def dom_smart_back(page, pages_before: int):
    """
    Playwright-aware "return to where we were" primitive (decisions.md
    D-044) -- fixes a real, verified gap: browser_back()'s OS-level
    Alt+Left has no notion of a new tab. A meaningful fraction of nav/
    footer links use target="_blank" -- when one of those is clicked,
    Alt+Left is sent to whichever window/tab has OS focus (which may not
    even be AURA's own browser) and does nothing useful in the new tab
    either way (it has no back history). The old click-audit loop had no
    way to detect this had happened; it just recorded whatever the next
    screenshot showed, which after a new-tab click is frequently still a
    picture of the *original* page (nothing on it visibly changed), so a
    target="_blank" link that worked perfectly got reported as "no
    visible change after click" -- a false "possibly non-functional" flag
    on a working element. Independently verified against
    alibaba/page-agent's ActionResult handling (docs/external_repos.md
    Batch 6, item 4): "explicit handling for edge cases like
    target=\"_blank\" anchors (reports 'opened in a new tab' rather than
    silently doing nothing)" -- same problem, same fix shape.

    Behavior:
      1. If the click opened one or more new tabs (context.pages grew
         past pages_before), record the new tab's URL, close every tab
         after the original, and bring the original back into focus.
         AURA does not follow the new tab deeper -- the click-audit loop
         tests *this* page's elements one at a time, not every external
         site a link points to.
      2. Otherwise, use Playwright's own page.go_back() (waits for the
         navigation to commit) instead of a blind OS keystroke.

    Returns a small result object (new_tab_opened, new_tab_url, went_back)
    so callers can report "opened in a new tab" explicitly instead of
    folding it into an ambiguous state_changed=True/False verdict.
    """
    from dataclasses import dataclass

    @dataclass
    class SmartBackResult:
        new_tab_opened: bool = False
        new_tab_url: str | None = None
        went_back: bool = False

    context = page.context
    result = SmartBackResult()

    if len(context.pages) > pages_before:
        for extra in context.pages[pages_before:]:
            try:
                extra.wait_for_load_state("commit", timeout=5000)
            except Exception:
                pass  # best-effort only -- still report/close it below even if the wait timed out
            try:
                result.new_tab_url = extra.url
            except Exception:
                pass
            try:
                extra.close()
            except Exception:
                pass  # tab may already be closing -- not fatal, the original tab is what matters next
        result.new_tab_opened = True
        try:
            page.bring_to_front()
        except Exception:
            pass
        return result

    try:
        page.go_back(wait_until="commit", timeout=5000)
        result.went_back = True
    except Exception:
        pass  # no back history, or navigation didn't happen -- caller's next locate() simply fails closed, same contract as the OS-level path
    return result
