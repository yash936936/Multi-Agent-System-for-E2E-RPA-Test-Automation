"""
Shared runtime errors — runtime/errors.py

Phase S (Roadmap Phase S, decisions.md D-040/D-041): `NoDisplayError` used
to be defined three separate times -- once each in `runtime.hooks.browser`,
`runtime.hooks.capture`, and `runtime.hooks.interact` -- as three distinct
`RuntimeError` subclasses that happened to share a name. They were never
related by inheritance, so callers that needed to catch "no display,
whichever hook raised it" had to import all three under aliases
(`CaptureNoDisplayError`, `BrowserNoDisplayError`, ...) and list every
alias in an `except` tuple. Missing one meant a genuine no-display
condition from that hook fell through to a generic `except Exception`
(or wasn't caught at all), which is exactly the "every new vision-adjacent
feature has to remember to guard its own screenshot call" failure mode
D-022 and D-024 each patched piecemeal.

This module is the single source of truth going forward: `runtime.hooks.browser`,
`runtime.hooks.capture`, and `runtime.hooks.interact` all import and raise
*this* class rather than defining their own. Callers only need one import,
one `except NoDisplayError`, regardless of which hook raised it.

Deliberately dependency-free (no imports beyond stdlib) so importing it
never risks pulling in `mss`, `pyautogui`, or Playwright -- the whole
point of the hooks' lazy-import pattern is that this exception type must
be catchable even in headless/no-display environments where none of
those libraries are installed.
"""
from __future__ import annotations

from contextlib import contextmanager


class NoDisplayError(RuntimeError):
    """Raised whenever a display-dependent operation cannot proceed --
    no display server, no browser/binary found, no screen-capture backend
    available, or the interaction/navigation library itself failed to
    initialize for a display-related reason. Every display-touching hook
    (`runtime.hooks.browser`, `runtime.hooks.capture`, `runtime.hooks.interact`)
    raises this one shared class instead of a per-module lookalike."""


class DisplayGuardResult:
    """Populated by `display_guard()` -- see its docstring."""

    __slots__ = ("value", "no_display", "error")

    def __init__(self) -> None:
        self.value = None
        self.no_display = False
        self.error: NoDisplayError | None = None


@contextmanager
def display_guard():
    """
    S2 (Roadmap Phase S, decisions.md D-041): the single shared guard every
    screenshot/display-dependent call site uses, built around S1's unified
    NoDisplayError.

    Before this, every call site that could hit "no display" had to write
    its own try/except NoDisplayError, and it was easy (and had already
    happened three separate times -- see decisions.md D-022, D-024, and
    the pre-S1 ui_audit_runner.py/autoscan.py/run_engine.py sites) to
    forget one, or to only catch one hook's variant while another hook's
    lookalike class slipped through. Wrapping the call site in this
    context manager turns "remember to guard your screenshot/display
    call" from a discipline into an enforced code path: the guard is the
    only way any code should touch a display-dependent operation now.

    Usage:
        with display_guard() as guard:
            guard.value = screenshot_provider(run_id, step_id)
        if guard.no_display:
            ...  # handle "no display" however this call site needs to
        else:
            use(guard.value)

    Only NoDisplayError is caught here -- any other exception propagates
    normally, exactly as an uncaught error should. A caller that needs the
    original error message (e.g. `aura/cli/preflight.py`'s advisory
    warning) can read `guard.error`.
    """
    guard = DisplayGuardResult()
    try:
        yield guard
    except NoDisplayError as e:
        guard.no_display = True
        guard.error = e
