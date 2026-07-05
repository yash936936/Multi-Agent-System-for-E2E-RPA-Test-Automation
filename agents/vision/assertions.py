"""
Assertions — agents/vision/assertions.py

Post-action assertion checker: compares a post-action screenshot against
an expected_state description. Implementation reuses the same OCR text
matching as locator.py — an assertion like "dashboard_visible" passes if
OCR finds text on screen reasonably matching "dashboard visible" (after
underscore->space normalization, since TestSpec expected_state values are
often snake_case slugs — see agents/planner/spec_generator.py).
"""
from __future__ import annotations

from pathlib import Path

from agents.vision.locator import locate_text


def check_assertion(screenshot_path: str | Path, expected_state: str, min_ratio: float = 0.55) -> bool:
    readable = expected_state.replace("_", " ").strip()
    result = locate_text(screenshot_path, readable, min_ratio=min_ratio)
    return result.found
