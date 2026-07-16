"""
Screenshot capture — runtime/hooks/capture.py

Thin wrapper over `mss` for cross-platform, cloud-free screenshotting.
`mss` (and pyautogui in interact.py) require a live display connection,
which isn't available in headless CI/sandbox environments — so the
import is deferred to inside each function rather than at module level.
That keeps `agents.vision.*` importable and unit-testable (against
synthetic PIL images) even where no display exists; the real capture
path is exercised only when actually running against a target app.

Phase S (decisions.md D-040): NoDisplayError is now the one shared class
from runtime.errors, not a module-local lookalike -- see runtime/errors.py.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from PIL import Image

from config.settings import settings
from runtime.errors import NoDisplayError

__all__ = ["NoDisplayError"]  # re-exported for existing `from runtime.hooks.capture import NoDisplayError` call sites


def file_hash(path: str | Path) -> str:
    """SHA-256 of a file's bytes -- used to detect "did the screen change" without pixel-diffing."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def capture_screenshot(run_id: str, step_id: int, monitor: int = 1) -> Path:
    """
    Captures the given monitor and saves it under
    runtime/screenshots/run_<run_id>/step_<step_id>_<timestamp>.png

    Returns the path to the saved PNG.
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
