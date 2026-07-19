"""
Visual regression — agents/vision/visual_regression.py (Phase G3, decisions.md D-027)

Replaces "did anything change" (runtime/hooks/capture.py's file_hash --
still used as-is for its actual job, the WAIT_FOR_HUMAN_ACTION polling
loop in orchestrator/run_engine.py, which genuinely only needs a cheap
boolean) with a real, quantified pixel-diff against a *persisted* baseline
image, for a new opt-in per-step check: "does this page still look the
way it looked last time we called it correct."

Deliberately separate from capture.py's file_hash / assertions.py's OCR
text matching -- three different questions, three different mechanisms:
  - file_hash: "did the screen change at all during this one run" (cheap,
    boolean, used only for the interactive wait-loop)
  - check_assertion (OCR): "does this specific text appear on screen"
  - compare_to_baseline (this module): "does this look the same as the
    last time we saved it as correct, within a tolerance"
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageChops
from pydantic import BaseModel

from config.settings import settings

# numpy is not declared as a direct AURA dependency, but it's a hard
# transitive dependency of opencv-python-headless (which pyproject.toml
# does declare) -- every environment where AURA installs successfully
# already has it. Used here for a vectorized diff instead of a
# pure-Python per-pixel loop, which would be slow on a real 1080p+
# screenshot (millions of pixels).
import numpy as np


class VisualDiffResult(BaseModel):
    diff_ratio: float  # fraction of pixels that differ, 0.0-1.0
    passed: bool
    baseline_created: bool = False  # True only on the first-ever comparison for this key
    diff_image_path: str | None = None  # written only when the comparison failed
    dimension_mismatch: bool = False


def _baseline_path(baseline_key: str) -> Path:
    # baseline_key comes from TestStep.visual_baseline_key, which a spec
    # author writes by hand -- sanitize before using it as a filename so a
    # key like "dashboard/after-login" can't escape baselines_dir or
    # collide with path separators.
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in baseline_key)
    return settings.baselines_dir / f"{safe}.png"


def _diff_image_path(baseline_key: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in baseline_key)
    return settings.baselines_dir / f"{safe}_diff_latest.png"


def compare_to_baseline(
    current_screenshot_path: str | Path,
    baseline_key: str,
    tolerance: float = 0.02,
) -> VisualDiffResult:
    """
    Compares `current_screenshot_path` against the stored baseline for
    `baseline_key` (runtime/baselines/<sanitized-key>.png).

    First call for a given key: no baseline exists yet. The current
    screenshot becomes the new baseline, and this reports success (not a
    pass/fail against nothing) with `baseline_created=True` -- matching
    this project's established honesty convention (see
    docs/decisions.md D-017's cloud_adapter note) of never fabricating a
    pass/fail verdict against data that doesn't exist yet.

    Every later call diffs against that stored baseline via
    PIL.ImageChops.difference -- counts pixels where any RGB channel
    differs at all, divided by total pixel count, gives diff_ratio.
    `passed = diff_ratio <= tolerance`. On a failing diff, the raw
    difference image (bright where pixels differ, black where they match)
    is saved next to the baseline so a human/report can see *what*
    changed, not just that something did.

    Dimension mismatch (baseline and current screenshot are different
    sizes -- e.g. someone changed viewport size, or the target page's
    layout genuinely changed size) is reported as a full failure
    (diff_ratio=1.0, dimension_mismatch=True) rather than attempting to
    resize/pad one to match the other, which would silently paper over a
    real, meaningful difference.
    """
    settings.baselines_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = _baseline_path(baseline_key)
    current_path = Path(current_screenshot_path)

    if not baseline_path.exists():
        baseline_img = Image.open(current_path).convert("RGB")
        baseline_img.save(baseline_path)
        return VisualDiffResult(diff_ratio=0.0, passed=True, baseline_created=True)

    baseline_img = Image.open(baseline_path).convert("RGB")
    current_img = Image.open(current_path).convert("RGB")

    if baseline_img.size != current_img.size:
        return VisualDiffResult(diff_ratio=1.0, passed=False, dimension_mismatch=True)

    diff = ImageChops.difference(baseline_img, current_img)
    total_pixels = baseline_img.size[0] * baseline_img.size[1]
    # A pixel "differs" if any of its R/G/B channels differ at all. This is
    # intentionally strict (not a perceptual/anti-aliasing-tolerant
    # comparison) -- tolerance is meant to absorb "how much of the page
    # changed," not "how different does a changed pixel need to be to
    # count." A softer per-channel threshold is a reasonable future
    # refinement but isn't pretended to exist here.
    diff_array = np.asarray(diff)
    differing = int(np.count_nonzero(np.any(diff_array != 0, axis=-1)))
    diff_ratio = differing / total_pixels if total_pixels else 0.0
    passed = diff_ratio <= tolerance

    result = VisualDiffResult(diff_ratio=diff_ratio, passed=passed)
    if not passed:
        diff_out_path = _diff_image_path(baseline_key)
        # Amplify the raw diff (real pixel deltas are often visually
        # subtle -- a 1-value RGB difference is invisible at normal
        # brightness) so a human looking at the saved diff image can
        # actually see what changed, not just a near-black image.
        amplified = diff.point(lambda p: min(255, p * 8))
        amplified.save(diff_out_path)
        result.diff_image_path = str(diff_out_path)

    return result


# --------------------------------------------------------------------------
# Phase Z (decisions.md D-052): baseline management -- the "natural, small
# follow-up" D-027 explicitly flagged as not yet done ("no CLI command for
# reviewing/approving a new baseline when a legitimate UI change causes an
# expected diff -- today, deleting the file under runtime/baselines/ and
# re-running is the only way to reset one").
# --------------------------------------------------------------------------

def list_baselines() -> list[dict]:
    """
    Returns metadata for every stored baseline: key, file path, size in
    bytes, last-modified time, and whether a pending (not-yet-approved)
    diff image exists for it (i.e. the most recent comparison against this
    baseline failed and hasn't been resolved yet by either approving the
    new screenshot or leaving the old baseline in place).
    """
    settings.baselines_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for path in sorted(settings.baselines_dir.glob("*.png")):
        if path.name.endswith("_diff_latest.png"):
            continue
        key = path.stem
        diff_path = settings.baselines_dir / f"{key}_diff_latest.png"
        stat = path.stat()
        results.append({
            "baseline_key": key,
            "path": str(path),
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "has_pending_diff": diff_path.exists(),
        })
    return results


class BaselineNotFoundError(RuntimeError):
    pass


def approve_baseline_from_path(baseline_key: str, replacement_screenshot_path: str) -> Path:
    """
    Replaces the stored baseline for `baseline_key` with the image at
    `replacement_screenshot_path`, and clears any pending diff artifact for
    that key. Raises BaselineNotFoundError if no baseline currently exists
    for this key (nothing to approve/replace -- the next
    `compare_to_baseline` call for a brand-new key already creates one
    automatically, so this path is specifically for *replacing* an
    existing one).
    """
    settings.baselines_dir.mkdir(parents=True, exist_ok=True)
    baseline_path = _baseline_path(baseline_key)
    if not baseline_path.exists():
        raise BaselineNotFoundError(
            f"No existing baseline for key '{baseline_key}' at {baseline_path} -- "
            "nothing to approve/replace. A new baseline is created automatically "
            "the first time compare_to_baseline() runs for a brand-new key."
        )

    replacement = Image.open(replacement_screenshot_path).convert("RGB")
    replacement.save(baseline_path)

    diff_path = _diff_image_path(baseline_key)
    if diff_path.exists():
        diff_path.unlink()

    return baseline_path


def reject_pending_diff(baseline_key: str) -> bool:
    """
    Discards a pending diff artifact without touching the stored baseline
    -- the "no, that was a real regression, I'm not approving it, just
    clear the flag once I've filed a bug" case. Returns True if a pending
    diff existed and was removed, False if there was nothing to clear.
    """
    diff_path = _diff_image_path(baseline_key)
    if diff_path.exists():
        diff_path.unlink()
        return True
    return False
