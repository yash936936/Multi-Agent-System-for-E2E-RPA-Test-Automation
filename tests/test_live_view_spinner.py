"""
tests/test_live_view_spinner.py

Phase 5 (docs/AURA_REARCHITECTURE_PLAN.md, docs/decisions.md D-078):
aura/tui/live_view.py::spinner() -- a persistent status line for any
operation that can take >1s of otherwise-silent wait.
"""
from __future__ import annotations

import io

from rich.console import Console

from aura.tui import live_view


def test_spinner_yields_and_exits_cleanly():
    entered = []
    with live_view.spinner("Doing a thing..."):
        entered.append(True)
    assert entered == [True]


def test_spinner_propagates_exceptions_raised_inside_the_block():
    class _Boom(Exception):
        pass

    try:
        with live_view.spinner("Doing a thing..."):
            raise _Boom("nope")
    except _Boom:
        pass
    else:
        raise AssertionError("spinner() must not swallow exceptions raised inside its block")


def test_spinner_degrades_gracefully_when_stdout_is_not_a_real_tty(monkeypatch):
    """
    Piping output to a file (CI logs, `aura explore url > out.txt`) must
    produce clean, non-animated output -- not raw ANSI escape codes or a
    crash. rich.console.Console detects `force_terminal=False` / a
    non-interactive file stream itself; this test just confirms
    live_view.spinner() doesn't fight that or raise when it happens.
    """
    buf = io.StringIO()
    fake_console = Console(file=buf, force_terminal=False, no_color=True)
    monkeypatch.setattr(live_view, "console", fake_console)

    with live_view.spinner("Running..."):
        fake_console.print("some output during the run")

    output = buf.getvalue()
    assert "some output during the run" in output
    # No raw escape sequences leaked into the piped output.
    assert "\x1b[" not in output
