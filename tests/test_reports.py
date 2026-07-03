"""
tests/test_reports.py

Verifies reports/render.py produces valid, section-complete HTML from the
artifacts a real run already leaves on disk (report.json + raw_results.json
from orchestrator/report_aggregator.py). Reuses the same RunEngine +
synthetic-screenshot fixture pattern as tests/test_run_engine.py so this
test is exercising real output, not a hand-built fixture.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from orchestrator.memory import RunMemoryStore
from orchestrator.run_engine import RunEngine
from orchestrator.skill_store import SkillStore
from reports.render import render_html
from target_app.demo_login_app import render_login_screen

REQUIREMENT_PATH = Path(__file__).resolve().parent.parent / "requirements_input" / "example_login_flow.md"


@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def make_provider(tmp_dir: Path):
    screens = {1: "initial", 2: "login_form", 3: "login_form", 4: "login_form"}

    def provider(run_id: str, step_id: int) -> str:
        state = screens.get(step_id, "dashboard")
        path = tmp_dir / f"{run_id}_{step_id}_{state}.png"
        if not path.exists():
            render_login_screen(state, path)
        return str(path)

    return provider


def test_render_html_produces_all_required_sections(tmp_dir: Path, monkeypatch):
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "project_root", tmp_dir)

    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")
    engine = RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)
    result = engine.run(requirement_text, run_id="report_test_run")

    html_path = render_html(result.run_id, spec=result.spec.model_dump())
    assert html_path.exists()

    html = html_path.read_text()
    assert "AURA Run Report" in html
    assert result.run_id in html
    assert "Step detail" in html
    assert "audit trace" in html
    # summary card numbers should reflect the real report
    assert str(result.report.total_steps) in html
    # feature roadmap: plain-English "what this test does" explanation
    assert "What this test does:" in html
    assert result.spec.test_id in html


def test_render_html_raises_clear_error_when_no_run_exists(tmp_dir: Path, monkeypatch):
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "project_root", tmp_dir)

    with pytest.raises(FileNotFoundError):
        render_html("no-such-run")
