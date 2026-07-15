"""
Slideshow recorder — runtime/hooks/video_recorder.py

Phase I2 (docs/decisions.md D-030): video recording for runs that use the
OS/pixel path (`runtime/hooks/interact.py`/`agents/vision/locator.py`) --
native desktop targets with no live accessibility tree, where
`runtime/hooks/browser.py`'s real Playwright `record_video_dir` isn't an
option because there's no Playwright page in play at all.

This is deliberately **not** a video encoder. It's a manifest that
references each step's already-captured screenshot (`runtime/hooks/capture.py`)
in order, with a timestamp -- an honestly-labeled "step-boundary slideshow,"
never claimed to be continuous recording. A report renderer can turn this
into a client-side slideshow (cycle through the referenced images) without
AURA needing to depend on any video-encoding library.

Contract mirrors runtime/hooks/browser.py's video path as closely as
possible so callers (orchestrator/run_engine.py) can treat "got a video path
back" and "got a slideshow manifest path back" as parallel outcomes of the
same `settings.record_video` opt-in, just labeled honestly as different
`kind`s in report_paths.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from config.settings import settings


class SlideshowRecorder:
    """
    Call `add_frame(screenshot_path, step_id)` once per step as the run
    progresses, then `finalize(run_id)` at the end to write the manifest.
    Never touches the screenshot files themselves -- only references their
    existing paths under runtime/screenshots/run_<run_id>/.
    """

    def __init__(self) -> None:
        self._frames: list[dict] = []

    def add_frame(self, screenshot_path: str | Path, step_id: int) -> None:
        self._frames.append(
            {
                "step_id": step_id,
                "screenshot_path": str(screenshot_path),
                "captured_at": time.time(),
            }
        )

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    def finalize(self, run_id: str) -> str | None:
        """
        Writes the manifest JSON and returns its path, or None if no frames
        were ever recorded (nothing worth writing).
        """
        if not self._frames:
            return None

        out_dir = settings.videos_dir / f"slideshow_{run_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = out_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "kind": "slideshow",
                    "note": (
                        "Step-boundary slideshow, not continuous video -- the OS/pixel "
                        "path has no live frame stream to record, only per-step "
                        "screenshots. See docs/decisions.md D-030."
                    ),
                    "run_id": run_id,
                    "frame_count": len(self._frames),
                    "frames": self._frames,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(manifest_path)
