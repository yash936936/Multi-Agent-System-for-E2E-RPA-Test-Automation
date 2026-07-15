from __future__ import annotations

import json

from runtime.hooks.video_recorder import SlideshowRecorder


def test_finalize_returns_none_with_no_frames(tmp_path, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)
    recorder = SlideshowRecorder()
    assert recorder.finalize("run123") is None


def test_add_frame_and_finalize_writes_honest_manifest(tmp_path, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)
    recorder = SlideshowRecorder()
    recorder.add_frame("/some/path/step_1.png", 1)
    recorder.add_frame("/some/path/step_2.png", 2)

    assert recorder.frame_count == 2

    manifest_path = recorder.finalize("run123")
    assert manifest_path is not None

    data = json.loads(open(manifest_path, encoding="utf-8").read())
    assert data["kind"] == "slideshow"
    assert "not continuous video" in data["note"]
    assert data["frame_count"] == 2
    assert data["frames"][0]["step_id"] == 1
    assert data["frames"][0]["screenshot_path"] == "/some/path/step_1.png"
    assert data["frames"][1]["step_id"] == 2
