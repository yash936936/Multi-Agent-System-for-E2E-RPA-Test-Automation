"""
RunEngine-level integration test for Phase I2 (video recording,
docs/decisions.md D-030): with settings.record_video on and a real
Playwright DOM-path session already active, a completed run's
RunReport.report_paths must contain a real, non-empty video file --
not just a unit-level check of the underlying browser.py primitives.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from config.settings import settings
from orchestrator.memory import RunMemoryStore
from orchestrator.run_engine import RunEngine
from orchestrator.schemas import ActionType, TestSpec, TestStep
from orchestrator.skill_store import SkillStore
from tests.conftest_local_server import make_server, server_url

PAGE = b"""
<html><body>
  <button onclick="document.title='clicked'">Login Button</button>
</body></html>
"""


@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(autouse=True)
def _reset_browser_and_settings():
    from runtime.hooks import browser

    browser.close()
    original_video = settings.record_video
    yield
    browser.close()
    settings.record_video = original_video


@pytest.fixture
def server():
    srv = make_server(PAGE)
    yield srv
    srv.shutdown()


def _synthetic_screenshot_provider(run_id: str, step_id: int, tmp_dir: Path) -> str:
    """A trivial, real PNG on disk -- RunEngine's screenshot path just needs
    a real file, since the DOM-path click itself doesn't use pixels at all."""
    path = tmp_dir / f"{run_id}_{step_id}.png"
    Image.new("RGB", (100, 100), color="white").save(path)
    return str(path)


def test_completed_run_with_record_video_on_attaches_a_real_video_file(tmp_dir, server):
    from runtime.hooks import browser

    settings.record_video = True
    browser.open_url(server_url(server), wait_seconds=0.1)  # DOM path session active before the run starts

    engine = RunEngine(
        screenshot_provider=lambda run_id, step_id: _synthetic_screenshot_provider(run_id, step_id, tmp_dir),
        skill_store=SkillStore(db_path=tmp_dir / "skills.db"),
        memory=RunMemoryStore(db_path=tmp_dir / "memory.db"),
    )
    spec = TestSpec(
        test_id="TC-VIDEO-001",
        requirement_ref="REQ-VIDEO",
        steps=[TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login Button")],
    )

    result = engine.run_spec(spec, run_id="video_run_001")

    assert "video" in result.report.report_paths
    video_path = result.report.report_paths["video"]
    assert os.path.exists(video_path)
    assert os.path.getsize(video_path) > 0
    assert "video_slideshow" not in result.report.report_paths  # real video takes priority


def test_completed_run_without_record_video_has_no_video_keys(tmp_dir, server):
    from runtime.hooks import browser

    assert settings.record_video is False
    browser.open_url(server_url(server), wait_seconds=0.1)

    engine = RunEngine(
        screenshot_provider=lambda run_id, step_id: _synthetic_screenshot_provider(run_id, step_id, tmp_dir),
        skill_store=SkillStore(db_path=tmp_dir / "skills.db"),
        memory=RunMemoryStore(db_path=tmp_dir / "memory.db"),
    )
    spec = TestSpec(
        test_id="TC-VIDEO-002",
        requirement_ref="REQ-VIDEO",
        steps=[TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login Button")],
    )

    result = engine.run_spec(spec, run_id="video_run_002")

    assert "video" not in result.report.report_paths
    assert "video_slideshow" not in result.report.report_paths
