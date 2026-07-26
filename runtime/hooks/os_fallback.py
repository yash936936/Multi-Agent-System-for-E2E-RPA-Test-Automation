"""
OS-level fallback — runtime/hooks/os_fallback.py

Phase 3 (docs/AURA_REARCHITECTURE_PLAN.md, docs/decisions.md D-076):
the ONE deliberately-kept OS-level (pyautogui mouse/keyboard, mss
screen-capture) dispatch path in AURA, isolated into its own clearly-
named module instead of being threaded through `runtime/hooks/interact.py`
and `runtime/hooks/capture.py`'s generically-named functions as it was
before this phase.

**When this module is used, and only this condition:** no live
Playwright page exists (`runtime.hooks.browser.has_active_page()` is
False) -- the exact same single condition
`orchestrator/brain/policy.py::Policy.discovery_source()` already uses
for DOM-vs-OCR, and the same one `capture_screenshot()` in
`runtime/hooks/capture.py` now checks before falling back here. One
rule governs every fallback in the system; this module is where the
"otherwise" branch of that rule actually lives.

**Why this path still exists at all** (the open product decision
D-076 resolved): `aura execute --interactive` with no `--url` given
means "AURA, watch whatever's already on my screen" -- the person may
already have a browser (or any other app) open in a state they don't
want AURA to reset by navigating. There is no live Playwright page to
screenshot or dispatch input through in that case by definition, so a
real OS-level fallback is a genuine, load-bearing requirement for that
one mode, not leftover caution. Every other call site in AURA
(`aura explore`, `aura execute` without `--interactive`,
`aura ui-audit`) always has its own live Playwright page and never
reaches this module at all post-Phase-3.

If a future native-desktop-app (non-browser) automation target is ever
wanted, that is explicitly a separate, new RPA-adapter effort (e.g. a
pywinauto-based adapter with its own accessibility tree, same
DOM-first philosophy applied to Windows UIA) — not a reason to widen
this module's use.
"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image

from config.settings import settings
from runtime.errors import NoDisplayError

__all__ = ["NoDisplayError", "click", "type_text", "scroll", "browser_back", "capture_screenshot"]


def _pyautogui():
    try:
        import pyautogui

        pyautogui.FAILSAFE = True
        return pyautogui
    except SystemExit as e:
        # mouseinfo (a pyautogui dependency) calls sys.exit(...) directly
        # at import time when tkinter isn't installed on Linux, instead of
        # raising a normal ImportError. SystemExit is a BaseException, not
        # an Exception, so it isn't caught below and would otherwise kill
        # the whole process silently (no traceback, just exit code 1)
        # instead of surfacing as the same NoDisplayError every other
        # no-display condition in this module already produces.
        raise NoDisplayError(f"pyautogui unavailable (tkinter missing -- see mouseinfo's message: {e}))") from e
    except Exception as e:  # pragma: no cover - exercised only without a display
        raise NoDisplayError(f"pyautogui unavailable: {e}") from e


def click(x: int, y: int) -> None:
    """
    OS-absolute-pixel-space click. Only ever called when no live
    Playwright page exists (see module docstring) -- everywhere else
    dispatches via `runtime/hooks/interact.py::dom_click()` (viewport-
    space, Playwright-native) instead.
    """
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
    Chrome/Firefox/Edge on Windows and most Linux browsers). Fixed here
    (docs/decisions.md D-076) after being left as dead code calling an
    undefined `_pyautogui()` name mid-migration -- moved from
    `runtime/hooks/interact.py`, its pre-Phase-3 home, since it's an
    OS-level primitive and this module is now the one place those live.

    Only ever reached by `orchestrator/ui_audit_runner.py`'s true
    last-resort path (`resolution_strategy == "ocr" and not
    dispatch_via_playwright` -- i.e. no live Playwright page, or the
    click was genuinely dispatched at the OS level). When a live page
    exists, `runtime/hooks/interact.py::dom_smart_back()` is used
    instead -- see its docstring for why this OS-level shortcut can't
    reliably handle a `target="_blank"` link (decisions.md D-044).
    """
    pg = _pyautogui()
    pg.hotkey("alt", "left")


def capture_screenshot(run_id: str, step_id: int, monitor: int = 1) -> Path:
    """
    Full-monitor capture via `mss`. Only ever called when no live
    Playwright page exists -- `runtime/hooks/capture.py::capture_screenshot()`
    is the function every real caller in AURA actually imports; it tries
    `page.screenshot()` first and falls back to this function, so this
    one should not be called directly from anywhere new.
    """
    try:
        import mss
    except Exception as e:  # pragma: no cover - exercised only without mss installed
        raise NoDisplayError(f"mss unavailable: {e}") from e

    out_dir = settings.screenshots_dir / f"run_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"step_{step_id:03d}_{int(time.time() * 1000)}.png"

    try:
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[monitor])
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            img.save(out_path)
    except Exception as e:
        raise NoDisplayError(f"Could not capture screen: {e}") from e

    return out_path
