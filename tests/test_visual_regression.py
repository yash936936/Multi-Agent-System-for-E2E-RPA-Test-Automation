"""
Tests for agents/vision/visual_regression.py -- Phase G3 (decisions.md D-027).

Synthetic-image tests only, same pattern as tests/test_vision.py already
uses for OCR locate_text() -- no live target/display needed, real Pillow
images with deliberate, known pixel changes.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from agents.vision.visual_regression import compare_to_baseline


@pytest.fixture(autouse=True)
def _isolate_baselines_dir(tmp_path, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)
    yield


def _save_solid_image(path: Path, color: tuple[int, int, int], size=(100, 100)) -> Path:
    img = Image.new("RGB", size, color)
    img.save(path)
    return path


def test_first_call_creates_baseline_and_reports_success(tmp_path):
    current = _save_solid_image(tmp_path / "current.png", (255, 0, 0))
    result = compare_to_baseline(current, baseline_key="widget_a")

    assert result.baseline_created is True
    assert result.passed is True
    assert result.diff_ratio == 0.0

    from config.settings import settings
    assert (settings.baselines_dir / "widget_a.png").exists()


def test_identical_image_passes_with_zero_diff(tmp_path):
    baseline_call = _save_solid_image(tmp_path / "first.png", (10, 20, 30))
    compare_to_baseline(baseline_call, baseline_key="widget_b")

    identical = _save_solid_image(tmp_path / "second.png", (10, 20, 30))
    result = compare_to_baseline(identical, baseline_key="widget_b")

    assert result.baseline_created is False
    assert result.passed is True
    assert result.diff_ratio == 0.0
    assert result.diff_image_path is None


def test_small_change_under_tolerance_passes(tmp_path):
    base = Image.new("RGB", (100, 100), (0, 0, 0))
    base.save(tmp_path / "base.png")
    compare_to_baseline(tmp_path / "base.png", baseline_key="widget_c")

    # Change 1% of pixels (a 10x10 patch in a 100x100 image = 1%)
    changed = Image.new("RGB", (100, 100), (0, 0, 0))
    for x in range(10):
        for y in range(10):
            changed.putpixel((x, y), (255, 255, 255))
    changed.save(tmp_path / "changed.png")

    result = compare_to_baseline(tmp_path / "changed.png", baseline_key="widget_c", tolerance=0.02)

    assert 0.005 < result.diff_ratio < 0.02
    assert result.passed is True
    assert result.diff_image_path is None  # only saved on failure


def test_large_change_over_tolerance_fails_and_saves_diff_image(tmp_path):
    base = Image.new("RGB", (100, 100), (0, 0, 0))
    base.save(tmp_path / "base.png")
    compare_to_baseline(tmp_path / "base.png", baseline_key="widget_d")

    changed = Image.new("RGB", (100, 100), (255, 255, 255))  # 100% different
    changed.save(tmp_path / "changed.png")

    result = compare_to_baseline(tmp_path / "changed.png", baseline_key="widget_d", tolerance=0.02)

    assert result.diff_ratio == pytest.approx(1.0)
    assert result.passed is False
    assert result.diff_image_path is not None
    assert Path(result.diff_image_path).exists()


def test_dimension_mismatch_is_a_full_failure_not_a_silent_resize(tmp_path):
    base = Image.new("RGB", (100, 100), (0, 0, 0))
    base.save(tmp_path / "base.png")
    compare_to_baseline(tmp_path / "base.png", baseline_key="widget_e")

    different_size = Image.new("RGB", (200, 50), (0, 0, 0))
    different_size.save(tmp_path / "resized.png")

    result = compare_to_baseline(tmp_path / "resized.png", baseline_key="widget_e")

    assert result.dimension_mismatch is True
    assert result.passed is False
    assert result.diff_ratio == 1.0


def test_baseline_key_is_sanitized_for_filesystem_safety(tmp_path):
    current = _save_solid_image(tmp_path / "current.png", (1, 2, 3))
    result = compare_to_baseline(current, baseline_key="dashboard/after-login step 1")

    assert result.baseline_created is True
    from config.settings import settings
    saved = list(settings.baselines_dir.glob("*.png"))
    assert len(saved) == 1
    assert "/" not in saved[0].name  # confirms the key couldn't escape baselines_dir via a path separator


def test_default_tolerance_is_conservative_small(tmp_path):
    # Sanity check on the documented default -- catches a very subtle,
    # unintentional loosening of the default in a future edit.
    from agents.vision.visual_regression import compare_to_baseline
    import inspect

    sig = inspect.signature(compare_to_baseline)
    assert sig.parameters["tolerance"].default == 0.02


# --------------------------------------------------------------------------
# Phase Z (decisions.md D-052): baseline management (list/approve/reject)
# --------------------------------------------------------------------------

from agents.vision.visual_regression import (
    BaselineNotFoundError,
    approve_baseline_from_path,
    list_baselines,
    reject_pending_diff,
)


def test_list_baselines_empty_when_none_stored(tmp_path):
    assert list_baselines() == []


def test_list_baselines_reflects_stored_keys(tmp_path):
    current = _save_solid_image(tmp_path / "current.png", (255, 0, 0))
    compare_to_baseline(current, baseline_key="widget_list_a")

    rows = list_baselines()
    assert len(rows) == 1
    assert rows[0]["baseline_key"] == "widget_list_a"
    assert rows[0]["has_pending_diff"] is False


def test_list_baselines_flags_pending_diff(tmp_path):
    _save_solid_image(tmp_path / "base.png", (0, 0, 0))
    compare_to_baseline(tmp_path / "base.png", baseline_key="widget_list_b")

    _save_solid_image(tmp_path / "changed.png", (255, 255, 255))
    compare_to_baseline(tmp_path / "changed.png", baseline_key="widget_list_b", tolerance=0.0)

    rows = list_baselines()
    assert rows[0]["has_pending_diff"] is True


def test_approve_baseline_replaces_stored_image(tmp_path):
    _save_solid_image(tmp_path / "base.png", (0, 0, 0))
    compare_to_baseline(tmp_path / "base.png", baseline_key="widget_approve_a")

    replacement = _save_solid_image(tmp_path / "replacement.png", (10, 20, 30))
    approve_baseline_from_path("widget_approve_a", str(replacement))

    # Re-comparing the same replacement image now passes cleanly -- it's
    # the new baseline.
    result = compare_to_baseline(replacement, baseline_key="widget_approve_a")
    assert result.passed is True
    assert result.baseline_created is False


def test_approve_baseline_clears_pending_diff(tmp_path):
    _save_solid_image(tmp_path / "base.png", (0, 0, 0))
    compare_to_baseline(tmp_path / "base.png", baseline_key="widget_approve_b")
    _save_solid_image(tmp_path / "changed.png", (255, 255, 255))
    compare_to_baseline(tmp_path / "changed.png", baseline_key="widget_approve_b", tolerance=0.0)
    assert list_baselines()[0]["has_pending_diff"] is True

    approve_baseline_from_path("widget_approve_b", str(tmp_path / "changed.png"))
    assert list_baselines()[0]["has_pending_diff"] is False


def test_approve_baseline_raises_when_key_does_not_exist(tmp_path):
    replacement = _save_solid_image(tmp_path / "replacement.png", (10, 20, 30))
    with pytest.raises(BaselineNotFoundError):
        approve_baseline_from_path("never_existed", str(replacement))


def test_reject_pending_diff_clears_flag_without_changing_baseline(tmp_path):
    _save_solid_image(tmp_path / "base.png", (0, 0, 0))
    compare_to_baseline(tmp_path / "base.png", baseline_key="widget_reject_a")
    _save_solid_image(tmp_path / "changed.png", (255, 255, 255))
    compare_to_baseline(tmp_path / "changed.png", baseline_key="widget_reject_a", tolerance=0.0)
    assert list_baselines()[0]["has_pending_diff"] is True

    cleared = reject_pending_diff("widget_reject_a")
    assert cleared is True
    assert list_baselines()[0]["has_pending_diff"] is False

    # Baseline itself is untouched -- comparing the ORIGINAL base image
    # still passes (it's still the stored baseline).
    result = compare_to_baseline(tmp_path / "base.png", baseline_key="widget_reject_a")
    assert result.passed is True


def test_reject_pending_diff_returns_false_when_nothing_pending(tmp_path):
    _save_solid_image(tmp_path / "base.png", (0, 0, 0))
    compare_to_baseline(tmp_path / "base.png", baseline_key="widget_reject_b")
    assert reject_pending_diff("widget_reject_b") is False
