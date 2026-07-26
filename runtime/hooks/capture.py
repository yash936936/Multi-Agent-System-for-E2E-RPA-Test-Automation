"""
Screenshot capture — runtime/hooks/capture.py

Phase 3 (docs/decisions.md D-076): `capture_screenshot()` now tries a
real Playwright `page.screenshot()` first -- viewport-native, no
monitor/DPI/multi-monitor ambiguity at all -- whenever a live browser
session exists (`runtime.hooks.browser.has_active_page()`). It only
falls back to the OS-level `mss` full-monitor capture
(`runtime/hooks/os_fallback.py`) when no live page exists, the exact
same single condition every other DOM-vs-fallback decision in AURA now
uses (`orchestrator/brain/policy.py::Policy.discovery_source()`).

This function's name and signature are unchanged from before Phase 3
specifically so every existing caller (`agents/planner/page_grounding.py`,
`api/routers/runs.py`, `aura/cli/preflight.py`,
`orchestrator/brain/router.py`, and anything importing
`from runtime.hooks.capture import capture_screenshot`) needed zero
changes to benefit from the Playwright-first path -- the improvement
is in this one function's body, not a caller-by-caller migration.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from config.settings import settings
from runtime.errors import NoDisplayError

__all__ = ["NoDisplayError"]  # re-exported for existing `from runtime.hooks.capture import NoDisplayError` call sites


def file_hash(path: str | Path) -> str:
    """SHA-256 of a file's bytes -- used to detect "did the screen change" without pixel-diffing."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def capture_screenshot(run_id: str, step_id: int, monitor: int = 1) -> Path:
    """
    Captures the current page (or, with no live page, the given OS
    monitor) and saves it under
    runtime/screenshots/run_<run_id>/step_<step_id>_<timestamp>.png

    Returns the path to the saved PNG.
    """
    out_dir = settings.screenshots_dir / f"run_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"step_{step_id:03d}_{int(time.time() * 1000)}.png"

    from runtime.hooks import browser as browser_hook

    if browser_hook.has_active_page():
        try:
            browser_hook.get_page().screenshot(path=str(out_path))
            return out_path
        except Exception:
            # Live page existed a moment ago but became unusable between
            # has_active_page()'s check and the screenshot call itself
            # (navigation mid-capture, tab closed, etc.) -- fall through
            # to the OS-level path below rather than raising, same
            # fail-soft contract this function always had.
            pass

    from runtime.hooks import os_fallback

    return os_fallback.capture_screenshot(run_id, step_id, monitor)
