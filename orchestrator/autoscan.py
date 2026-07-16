"""
Autonomous scroll scan — orchestrator/autoscan.py

The unattended "scroll and check the whole page for me" mode: no
hand-written steps, no approval checkpoint. Repeatedly screenshots the
current view, runs the generic page-health check (page_health.py), then
scrolls down -- stopping either when a scroll produces no visual change
(bottom of the page reached, detected by comparing screenshot hashes) or
a safety cap is hit, whichever comes first. The cap exists for the same
reason orchestrator/guardrails.py exists elsewhere in this codebase:
unattended loops need a hard stop that isn't "trust the page to behave."
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable

ScreenshotProvider = Callable[[str, int], str]  # (run_id, index) -> screenshot_path


@dataclass
class AutoScanStepResult:
    index: int
    screenshot_ref: str
    issues: list[str] = field(default_factory=list)


@dataclass
class AutoScanReport:
    steps: list[AutoScanStepResult]
    reached_bottom: bool  # True if we stopped because scrolling changed nothing; False if we hit max_scrolls
    # True if the scan stopped because no display/screenshot capability was
    # available at all (runtime/hooks/capture.py's NoDisplayError) rather
    # than because it hit max_scrolls without reaching the bottom. Lets
    # callers show an accurate message ("no display" vs "hit the scan
    # limit") instead of conflating the two very different reasons a scan
    # can end early. See decisions.md for the fix this field is part of.
    display_unavailable: bool = False

    @property
    def all_issues(self) -> list[str]:
        seen: list[str] = []
        for step in self.steps:
            for issue in step.issues:
                if issue not in seen:
                    seen.append(issue)
        return seen


def _hash_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run_autoscan(
    screenshot_provider: ScreenshotProvider,
    run_id: str,
    max_scrolls: int = 25,
    scroll_amount: int = -600,
) -> AutoScanReport:
    from runtime.hooks import interact
    from runtime.errors import NoDisplayError, display_guard

    from agents.vision.page_health import detect_page_issues

    steps: list[AutoScanStepResult] = []
    prev_hash: str | None = None
    reached_bottom = False
    display_unavailable = False

    for i in range(max_scrolls):
        with display_guard() as guard:
            guard.value = screenshot_provider(run_id, 9000 + i)  # offset keeps these out of the main spec's step_id range
        if guard.no_display:
            # No display/screenshot capability available at all (headless
            # CI/sandbox environment, or a display that dropped mid-scan).
            # Every other real capture site in this pipeline
            # (orchestrator/run_engine.py's _safe_screenshot,
            # agents/vision/executor.py's action handlers) already turns
            # this into a clean stop instead of an uncaught traceback --
            # this was the one screenshot call site in the autonomous
            # scroll-scan loop that didn't, and crashed both `aura execute
            # --scroll-test` and `aura explore` whenever no display was
            # present. Stop cleanly with whatever was already collected
            # (typically nothing, on the first iteration) instead of
            # taking the whole run down.
            display_unavailable = True
            break
        path = guard.value
        issues = detect_page_issues(path)
        steps.append(AutoScanStepResult(index=i, screenshot_ref=path, issues=issues))

        current_hash = _hash_file(path)
        if prev_hash is not None and current_hash == prev_hash:
            reached_bottom = True
            break
        prev_hash = current_hash

        try:
            interact.scroll(scroll_amount)
        except NoDisplayError:
            break

    return AutoScanReport(steps=steps, reached_bottom=reached_bottom, display_unavailable=display_unavailable)
