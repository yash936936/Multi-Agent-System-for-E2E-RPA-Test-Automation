"""
RunEngine-level integration test for Phase Q (Playwright native trace
files, docs/decisions.md D-038): with settings.record_trace on and a real
Playwright DOM-path session already active, a completed run's
RunReport.report_paths must contain a real, non-empty trace .zip -- not
just a unit-level check of the underlying browser.py primitives.

Deliberately mirrors tests/test_run_engine_video.py's structure -- Phase Q
is the same lifecycle shape as Phase I2's video recording, just wired
through Playwright's tracing API instead of record_video_dir.
"""
from __future__ import annotations

import os
import tempfile
import zipfile
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
    original_trace = settings.record_trace
    yield
    browser.close()
    settings.record_video = original_video
    settings.record_trace = original_trace


@pytest.fixture
def server():
    srv = make_server(PAGE)
    yield srv
    srv.shutdown()


def _synthetic_screenshot_provider(run_id: str, step_id: int, tmp_dir: Path) -> str:
    path = tmp_dir / f"{run_id}_{step_id}.png"
    Image.new("RGB", (100, 100), color="white").save(path)
    return str(path)


def test_completed_run_with_record_trace_on_attaches_a_real_trace_file(tmp_dir, server):
    from runtime.hooks import browser

    settings.record_trace = True
    browser.open_url(server_url(server), wait_seconds=0.1)  # DOM path session active before the run starts

    engine = RunEngine(
        screenshot_provider=lambda run_id, step_id: _synthetic_screenshot_provider(run_id, step_id, tmp_dir),
        skill_store=SkillStore(db_path=tmp_dir / "skills.db"),
        memory=RunMemoryStore(db_path=tmp_dir / "memory.db"),
    )
    spec = TestSpec(
        test_id="TC-TRACE-001",
        requirement_ref="REQ-TRACE",
        steps=[TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login Button")],
    )

    result = engine.run_spec(spec, run_id="trace_run_001")

    assert "trace" in result.report.report_paths
    trace_path = result.report.report_paths["trace"]
    assert os.path.exists(trace_path)
    assert os.path.getsize(trace_path) > 0
    # A real Playwright trace is a valid, non-empty zip archive -- not
    # just a same-named placeholder file.
    assert zipfile.is_zipfile(trace_path)


def test_completed_run_without_record_trace_has_no_trace_key(tmp_dir, server):
    from runtime.hooks import browser

    assert settings.record_trace is False
    browser.open_url(server_url(server), wait_seconds=0.1)

    engine = RunEngine(
        screenshot_provider=lambda run_id, step_id: _synthetic_screenshot_provider(run_id, step_id, tmp_dir),
        skill_store=SkillStore(db_path=tmp_dir / "skills.db"),
        memory=RunMemoryStore(db_path=tmp_dir / "memory.db"),
    )
    spec = TestSpec(
        test_id="TC-TRACE-002",
        requirement_ref="REQ-TRACE",
        steps=[TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login Button")],
    )

    result = engine.run_spec(spec, run_id="trace_run_002")

    assert "trace" not in result.report.report_paths


def test_record_video_and_record_trace_together_attach_both(tmp_dir, server):
    """The two features are independently toggleable -- confirms one
    doesn't clobber or suppress the other when both are on at once."""
    from runtime.hooks import browser

    settings.record_video = True
    settings.record_trace = True
    browser.open_url(server_url(server), wait_seconds=0.1)

    engine = RunEngine(
        screenshot_provider=lambda run_id, step_id: _synthetic_screenshot_provider(run_id, step_id, tmp_dir),
        skill_store=SkillStore(db_path=tmp_dir / "skills.db"),
        memory=RunMemoryStore(db_path=tmp_dir / "memory.db"),
    )
    spec = TestSpec(
        test_id="TC-TRACE-003",
        requirement_ref="REQ-TRACE",
        steps=[TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login Button")],
    )

    result = engine.run_spec(spec, run_id="trace_run_003")

    assert "video" in result.report.report_paths
    assert "trace" in result.report.report_paths
    assert os.path.exists(result.report.report_paths["video"])
    assert os.path.exists(result.report.report_paths["trace"])
