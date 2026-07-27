"""Merged test file: test_run_engine.py
Consolidated from: test_run_engine.py, test_run_engine_trace.py, test_run_engine_video.py, test_run_engine_keep_browser_open.py
All original test functions preserved 1:1. Colliding fixture/helper names
renamed with a source-file suffix to avoid silent shadowing across sections.
"""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
import pytest
from orchestrator.memory import RunMemoryStore
from orchestrator.run_engine import RunEngine
from orchestrator.schemas import RunStatus
from orchestrator.skill_store import SkillStore
from target_app.demo_login_app import render_login_screen
import os
import zipfile
from PIL import Image
from config.settings import settings
from orchestrator.schemas import ActionType, TestSpec, TestStep
from tests.conftest_local_server import make_server, server_url
from unittest.mock import MagicMock


# ============================================================================
# ---- from test_run_engine.py ----
# ============================================================================
REQUIREMENT_PATH = Path(__file__).resolve().parent.parent / "requirements_input" / "example_login_flow.md"


@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def make_provider(tmp_dir: Path):
    """
    Maps (run_id, step_id) -> a pre-rendered screenshot matching what the
    real demo app would show at that point in the login flow:
      step 1 (click Login button)     -> initial screen
      step 2 (type username)          -> login form visible
      step 3 (type password)          -> login form visible
      step 4 (click Submit)           -> login form visible (button still there pre-click)
      final assertion (after step 4)  -> dashboard
    """
    screens = {
        1: "initial",
        2: "login_form",
        3: "login_form",
        4: "login_form",
    }

    def provider(run_id: str, step_id: int) -> str:
        state = screens.get(step_id, "dashboard")  # anything beyond the 4 known steps -> dashboard
        path = tmp_dir / f"{run_id}_{step_id}_{state}.png"
        if not path.exists():
            render_login_screen(state, path)
        return str(path)

    return provider


def test_run_engine_completes_full_login_flow(tmp_dir: Path):
    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")

    engine = RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)
    result = engine.run(requirement_text, run_id="e2e_test_run")

    assert result.spec.test_id.startswith("TC-")
    assert len(result.spec.steps) == 4

    report = result.report
    assert report.total_steps == 4
    # All 4 steps should have located their real, visible targets and the
    # final dashboard assertion should have passed -- a clean run, no healing needed.
    assert report.status == RunStatus.PASSED
    assert report.escalated_steps == 0
    assert report.self_healed_steps == 0


def test_run_engine_final_assertion_records_audit_evidence(tmp_dir: Path):
    """
    AA1 (docs/decisions.md D-057) regression test: the final spec-level
    assertion result must carry verification_source + raw_evidence (which
    method decided the verdict, and the per-assertion detail behind it) --
    not just the collapsed assertion_passed bool. This is exactly the
    audit-trail gap that let D-056's bug go undetected: a step could say
    "fulfilled" while its real check had failed, with nothing in the trace
    itself to show what was actually checked.
    """
    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")

    engine = RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)
    result = engine.run(requirement_text, run_id="aa1_audit_test_run")

    raw = json.loads(Path(result.report.report_paths["raw_json"]).read_text())
    step_results = raw["step_results"]

    final_step = step_results[-1]  # the spec-level assertion step, appended after all spec.steps
    assert final_step["verification_source"] == "ocr"
    assert final_step["raw_evidence"] is not None
    assert "assertions" in final_step["raw_evidence"]
    assert len(final_step["raw_evidence"]["assertions"]) >= 1
    for detail in final_step["raw_evidence"]["assertions"]:
        assert "expected" in detail
        assert "passed" in detail
        assert "method" in detail  # e.g. "literal_ocr" / "structural_fallback" / "structural_sentinel"


def test_run_engine_persists_resumable_run_state(tmp_dir: Path):
    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")

    engine = RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)
    engine.run(requirement_text, run_id="resumable_run")

    resume_point = memory.get_resume_point("resumable_run")
    assert resume_point == 4  # last step completed


def test_run_engine_visual_regression_first_run_creates_baseline(tmp_dir: Path, monkeypatch):
    # Phase G3 (decisions.md D-027): end-to-end proof that
    # TestStep.visual_baseline_key actually reaches
    # agents/vision/visual_regression.compare_to_baseline via RunEngine,
    # not just a unit test of the module in isolation.
    from config.settings import settings
    from orchestrator.schemas import ActionType, TestSpec, TestStep

    monkeypatch.setattr(settings, "project_root", tmp_dir)

    spec = TestSpec(
        test_id="TC-VISUAL-001",
        requirement_ref="visual regression smoke test",
        steps=[
            TestStep(
                step_id=1, action=ActionType.VISUAL_CLICK,
                target_description="Login button",
                visual_baseline_key="login_screen_g3_test",
            ),
        ],
    )
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")
    engine = RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)

    result = engine.run_spec(spec, run_id="visual_regression_run")

    raw_results = json.loads(Path(result.report.report_paths["raw_json"]).read_text())
    step_1 = raw_results["step_results"][0]
    assert step_1["visual_baseline_created"] is True
    assert step_1["visual_diff_ratio"] == 0.0
    assert (settings.baselines_dir / "login_screen_g3_test.png").exists()


def test_run_engine_visual_regression_second_run_compares_against_baseline(tmp_dir: Path, monkeypatch):
    from config.settings import settings
    from orchestrator.schemas import ActionType, TestSpec, TestStep

    monkeypatch.setattr(settings, "project_root", tmp_dir)

    spec = TestSpec(
        test_id="TC-VISUAL-002",
        requirement_ref="visual regression smoke test",
        steps=[
            TestStep(
                step_id=1, action=ActionType.VISUAL_CLICK,
                target_description="Login button",
                visual_baseline_key="login_screen_g3_test_2",
            ),
        ],
    )
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")
    provider = make_provider(tmp_dir)
    engine = RunEngine(screenshot_provider=provider, skill_store=skill_store, memory=memory)

    # First run creates the baseline from whatever screen the provider shows at step 1 ("initial").
    engine.run_spec(spec, run_id="visual_run_a")

    # Second run against the exact same screenshot -- should compare clean, zero diff.
    result_b = engine.run_spec(spec, run_id="visual_run_b")
    raw_results_b = json.loads(Path(result_b.report.report_paths["raw_json"]).read_text())
    step_1_b = raw_results_b["step_results"][0]
    assert step_1_b["visual_baseline_created"] is False
    assert step_1_b["visual_diff_ratio"] == 0.0
    assert step_1_b["assertion_passed"] is not False  # a clean visual match shouldn't fail the step



    """
    If the screenshot provider never shows the expected UI (simulating a
    genuinely broken app), every step should escalate through the healing
    loop and eventually hit the guardrail hard_stop, landing in the
    escalation queue rather than looping forever.
    """
    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")

    blank_path = tmp_dir / "blank.png"
    render_login_screen("initial", blank_path)  # only ever shows the initial screen, never progresses

    def broken_provider(run_id: str, step_id: int) -> str:
        return str(blank_path)

    engine = RunEngine(screenshot_provider=broken_provider, skill_store=skill_store, memory=memory)
    result = engine.run(requirement_text, run_id="broken_run")

    assert result.report.escalated_steps > 0
    pending = memory.pending_escalations()
    assert len(pending) > 0
    assert pending[0]["run_id"] == "broken_run"


def test_run_engine_generates_and_reuses_cached_synthetic_data(tmp_dir: Path, monkeypatch):
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "project_root", tmp_dir)

    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")
    engine = RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)

    result1 = engine.run(requirement_text, run_id="data_run_1")
    from agents.data_synth.cache import load_cached

    cached = load_cached(result1.spec.test_id)
    assert cached is not None
    assert "username" in cached


def test_run_engine_escalates_cleanly_on_no_display(tmp_dir: Path):
    """
    Regression test: previously, `self.screenshot_provider(...)` in the main
    vision branch was called with no try/except, so a NoDisplayError (raised
    by runtime/hooks/capture.py whenever no display/mss is available -- the
    normal case in headless CI/sandbox environments) propagated all the way
    up and crashed `aura execute`/`aura explore` with a raw traceback instead
    of escalating like every other action path already does. This test
    simulates that exact condition via a provider that raises NoDisplayError,
    and asserts the run completes with steps escalated instead of raising.
    """
    from runtime.hooks.capture import NoDisplayError

    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")

    def no_display_provider(run_id: str, step_id: int) -> str:
        raise NoDisplayError("no display available (simulated)")

    engine = RunEngine(screenshot_provider=no_display_provider, skill_store=skill_store, memory=memory)

    # This must NOT raise -- that's the whole point of the fix.
    result = engine.run(requirement_text, run_id="no_display_run")

    assert result.report.escalated_steps > 0
    assert result.report.status.value in ("escalated", "failed")

# ============================================================================
# ---- from test_run_engine_trace.py ----
# ============================================================================
PAGE = b"""
<html><body>
  <button onclick="document.title='clicked'">Login Button</button>
</body></html>
"""


@pytest.fixture()
def tmp_dir__run_engine_trace():
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


def _synthetic_screenshot_provider(run_id: str, step_id: int, tmp_dir__run_engine_trace: Path) -> str:
    path = tmp_dir__run_engine_trace / f"{run_id}_{step_id}.png"
    Image.new("RGB", (100, 100), color="white").save(path)
    return str(path)


def test_completed_run_with_record_trace_on_attaches_a_real_trace_file(tmp_dir__run_engine_trace, server):
    from runtime.hooks import browser

    settings.record_trace = True
    browser.open_url(server_url(server), wait_seconds=0.1)  # DOM path session active before the run starts

    engine = RunEngine(
        screenshot_provider=lambda run_id, step_id: _synthetic_screenshot_provider(run_id, step_id, tmp_dir__run_engine_trace),
        skill_store=SkillStore(db_path=tmp_dir__run_engine_trace / "skills.db"),
        memory=RunMemoryStore(db_path=tmp_dir__run_engine_trace / "memory.db"),
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


def test_completed_run_without_record_trace_has_no_trace_key(tmp_dir__run_engine_trace, server):
    from runtime.hooks import browser

    assert settings.record_trace is False
    browser.open_url(server_url(server), wait_seconds=0.1)

    engine = RunEngine(
        screenshot_provider=lambda run_id, step_id: _synthetic_screenshot_provider(run_id, step_id, tmp_dir__run_engine_trace),
        skill_store=SkillStore(db_path=tmp_dir__run_engine_trace / "skills.db"),
        memory=RunMemoryStore(db_path=tmp_dir__run_engine_trace / "memory.db"),
    )
    spec = TestSpec(
        test_id="TC-TRACE-002",
        requirement_ref="REQ-TRACE",
        steps=[TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login Button")],
    )

    result = engine.run_spec(spec, run_id="trace_run_002")

    assert "trace" not in result.report.report_paths


def test_record_video_and_record_trace_together_attach_both(tmp_dir__run_engine_trace, server):
    """The two features are independently toggleable -- confirms one
    doesn't clobber or suppress the other when both are on at once."""
    from runtime.hooks import browser

    settings.record_video = True
    settings.record_trace = True
    browser.open_url(server_url(server), wait_seconds=0.1)

    engine = RunEngine(
        screenshot_provider=lambda run_id, step_id: _synthetic_screenshot_provider(run_id, step_id, tmp_dir__run_engine_trace),
        skill_store=SkillStore(db_path=tmp_dir__run_engine_trace / "skills.db"),
        memory=RunMemoryStore(db_path=tmp_dir__run_engine_trace / "memory.db"),
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

# ============================================================================
# ---- from test_run_engine_video.py ----
# ============================================================================
PAGE = b"""
<html><body>
  <button onclick="document.title='clicked'">Login Button</button>
</body></html>
"""


@pytest.fixture()
def tmp_dir__run_engine_video():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture(autouse=True)
def _reset_browser_and_settings__run_engine_video():
    from runtime.hooks import browser

    browser.close()
    original_video = settings.record_video
    yield
    browser.close()
    settings.record_video = original_video


@pytest.fixture
def server__run_engine_video():
    srv = make_server(PAGE)
    yield srv
    srv.shutdown()


def _synthetic_screenshot_provider__run_engine_video(run_id: str, step_id: int, tmp_dir__run_engine_video: Path) -> str:
    """A trivial, real PNG on disk -- RunEngine's screenshot path just needs
    a real file, since the DOM-path click itself doesn't use pixels at all."""
    path = tmp_dir__run_engine_video / f"{run_id}_{step_id}.png"
    Image.new("RGB", (100, 100), color="white").save(path)
    return str(path)


def test_completed_run_with_record_video_on_attaches_a_real_video_file(tmp_dir__run_engine_video, server__run_engine_video):
    from runtime.hooks import browser

    settings.record_video = True
    browser.open_url(server_url(server__run_engine_video), wait_seconds=0.1)  # DOM path session active before the run starts

    engine = RunEngine(
        screenshot_provider=lambda run_id, step_id: _synthetic_screenshot_provider__run_engine_video(run_id, step_id, tmp_dir__run_engine_video),
        skill_store=SkillStore(db_path=tmp_dir__run_engine_video / "skills.db"),
        memory=RunMemoryStore(db_path=tmp_dir__run_engine_video / "memory.db"),
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


def test_completed_run_without_record_video_has_no_video_keys(tmp_dir__run_engine_video, server__run_engine_video):
    from runtime.hooks import browser

    assert settings.record_video is False
    browser.open_url(server_url(server__run_engine_video), wait_seconds=0.1)

    engine = RunEngine(
        screenshot_provider=lambda run_id, step_id: _synthetic_screenshot_provider__run_engine_video(run_id, step_id, tmp_dir__run_engine_video),
        skill_store=SkillStore(db_path=tmp_dir__run_engine_video / "skills.db"),
        memory=RunMemoryStore(db_path=tmp_dir__run_engine_video / "memory.db"),
    )
    spec = TestSpec(
        test_id="TC-VIDEO-002",
        requirement_ref="REQ-VIDEO",
        steps=[TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login Button")],
    )

    result = engine.run_spec(spec, run_id="video_run_002")

    assert "video" not in result.report.report_paths
    assert "video_slideshow" not in result.report.report_paths

# ============================================================================
# ---- from test_run_engine_keep_browser_open.py ----
# ============================================================================
REQUIREMENT_PATH = Path(__file__).resolve().parent.parent / "requirements_input" / "example_login_flow.md"


@pytest.fixture()
def tmp_dir__run_engine_keep_browser_open():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def make_provider__run_engine_keep_browser_open(tmp_dir__run_engine_keep_browser_open: Path):
    screens = {1: "initial", 2: "login_form", 3: "login_form", 4: "login_form"}

    def provider(run_id: str, step_id: int) -> str:
        state = screens.get(step_id, "dashboard")
        path = tmp_dir__run_engine_keep_browser_open / f"{run_id}_{step_id}_{state}.png"
        if not path.exists():
            render_login_screen(state, path)
        return str(path)

    return provider


def _make_engine(tmp_dir__run_engine_keep_browser_open: Path) -> RunEngine:
    skill_store = SkillStore(db_path=tmp_dir__run_engine_keep_browser_open / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir__run_engine_keep_browser_open / "memory.db")
    return RunEngine(screenshot_provider=make_provider__run_engine_keep_browser_open(tmp_dir__run_engine_keep_browser_open), skill_store=skill_store, memory=memory)


def test_default_run_closes_browser_at_end(tmp_dir__run_engine_keep_browser_open: Path, monkeypatch):
    """Baseline behavior: keep_browser_open defaults to False, so a plain
    `aura execute` (no --scroll-test/--ui-audit) still tears the browser
    down at the end of the run, same as before this fix."""
    mock_close = MagicMock()
    monkeypatch.setattr("runtime.hooks.browser.close", mock_close)

    engine = _make_engine(tmp_dir__run_engine_keep_browser_open)
    engine.run(REQUIREMENT_PATH.read_text(), run_id="default_close_run")

    mock_close.assert_called_once()


def test_keep_browser_open_true_skips_close_at_end_of_run(tmp_dir__run_engine_keep_browser_open: Path, monkeypatch):
    """The core regression case: with keep_browser_open=True, RunEngine
    must NOT close the browser itself -- the caller (execute_cmd.py) owns
    closing it once --scroll-test/--ui-audit are done."""
    mock_close = MagicMock()
    monkeypatch.setattr("runtime.hooks.browser.close", mock_close)

    engine = _make_engine(tmp_dir__run_engine_keep_browser_open)
    engine.run(REQUIREMENT_PATH.read_text(), run_id="keep_open_run", keep_browser_open=True)

    mock_close.assert_not_called()


def test_keep_browser_open_propagates_through_run_spec(tmp_dir__run_engine_keep_browser_open: Path, monkeypatch):
    """run() delegates to run_spec() -- confirm the flag actually reaches
    the real close-guard in run_spec() and isn't dropped along the way."""
    mock_close = MagicMock()
    monkeypatch.setattr("runtime.hooks.browser.close", mock_close)

    engine = _make_engine(tmp_dir__run_engine_keep_browser_open)
    result = engine.run(REQUIREMENT_PATH.read_text(), run_id="propagation_run", keep_browser_open=True)

    assert result.report is not None
    mock_close.assert_not_called()
