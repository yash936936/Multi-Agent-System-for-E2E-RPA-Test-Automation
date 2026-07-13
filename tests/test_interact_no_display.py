"""
Regression tests for runtime/hooks/interact.py's `_pyautogui()` guard.

Bug (found via live testing under Xvfb with tkinter uninstalled): pyautogui
transitively imports `mouseinfo`, which calls `sys.exit(...)` directly at
import time on Linux when tkinter isn't installed, instead of raising a
normal ImportError. `sys.exit()` raises `SystemExit`, which is a
`BaseException`, not an `Exception` -- so the previous
`except Exception as e: raise NoDisplayError(...)` never caught it, and it
propagated all the way up through orchestrator/autoscan.py,
orchestrator/ui_audit_runner.py, and agents/vision/executor.py, silently
killing the whole process (exit code 1, no traceback, no error message)
instead of degrading gracefully like every other no-display condition in
this codebase already does.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from runtime.hooks.interact import NoDisplayError, _pyautogui


def test_pyautogui_systemexit_from_mouseinfo_becomes_no_display_error(monkeypatch):
    """
    Simulates mouseinfo's sys.exit(...) call by making the `pyautogui`
    import itself raise SystemExit, and asserts it's converted into
    NoDisplayError instead of propagating and killing the process.
    """
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyautogui":
            sys.exit("NOTE: You must install tkinter on Linux to use MouseInfo.")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(NoDisplayError):
        _pyautogui()


def test_pyautogui_generic_import_error_still_becomes_no_display_error(monkeypatch):
    """The pre-existing ImportError/other-Exception path must keep working."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyautogui":
            raise ImportError("no module named pyautogui")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(NoDisplayError):
        _pyautogui()


def test_pyautogui_success_path_unaffected(monkeypatch):
    """When pyautogui imports fine, _pyautogui() should return it, FAILSAFE set."""
    fake_pyautogui = MagicMock()
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pyautogui)

    result = _pyautogui()

    assert result is fake_pyautogui
    assert fake_pyautogui.FAILSAFE is True
