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
