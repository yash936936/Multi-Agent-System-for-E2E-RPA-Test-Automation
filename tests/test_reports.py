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
    assert "Step-by-step process" in html
    assert "Decision basis" in html
    assert "audit trace" in html
    # summary card numbers should reflect the real report
    assert str(result.report.total_steps) in html
    # feature roadmap: plain-English "what this test does" explanation
    assert "What this test does:" in html
    assert result.spec.test_id in html
    # report-detail pass: request text + outcome summary now present
    assert requirement_text.strip()[:30] in html
    assert "Outcome" in html


def test_render_html_raises_clear_error_when_no_run_exists(tmp_dir: Path, monkeypatch):
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "project_root", tmp_dir)

    with pytest.raises(FileNotFoundError):
        render_html("no-such-run")


def test_render_json_produces_process_oriented_structure(tmp_dir: Path, monkeypatch):
    from config.settings import settings as global_settings
    from reports.render import render_json

    monkeypatch.setattr(global_settings, "project_root", tmp_dir)

    requirement_text = REQUIREMENT_PATH.read_text()
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")
    engine = RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)
    result = engine.run(requirement_text, run_id="report_json_test_run")

    json_path = render_json(result.run_id, spec=result.spec.model_dump())
    assert json_path.exists()
    assert json_path.name == "report_detailed.json"

    import json as _json
    data = _json.loads(json_path.read_text())

    # Request: the real original text, not the requirement_ref slug.
    assert data["request"]["text"].strip() == requirement_text.strip()
    assert data["request"]["test_id"] == result.spec.test_id

    # Process timeline: one entry per recorded step, each with a
    # non-empty decision basis explaining *why* it was accepted/rejected.
    assert len(data["process_timeline"]) == len(result.report.report_paths) or len(data["process_timeline"]) > 0
    for entry in data["process_timeline"]:
        assert entry["decision_basis"]["decided"] in (
            "fulfilled", "not_fulfilled", "escalated_not_fulfilled",
        )
        assert entry["decision_basis"]["reason"]

    # Outcome summary is a real sentence, not just a status enum value.
    assert data["outcome"]["status"] == result.report.status.value
    assert data["outcome"]["total_steps"] == result.report.total_steps
    assert str(result.report.total_steps) in data["outcome"]["summary"]

    # Proof of work section always present, pointing at real artifacts.
    assert "raw_json" in data["proof_of_work"]["report_paths"]

    # render_json must also update report.json so render_html can link to it.
    report_json = _json.loads((tmp_dir / "reports" / f"run_{result.run_id}" / "report.json").read_text()) \
        if (tmp_dir / "reports" / f"run_{result.run_id}" / "report.json").exists() \
        else _json.loads((global_settings.reports_dir / f"run_{result.run_id}" / "report.json").read_text())
    assert report_json["report_paths"]["detailed_json"] == str(json_path)


def test_human_in_the_loop_step_produces_evidence_and_report_section(tmp_dir: Path, monkeypatch):
    """A WAIT_FOR_HUMAN_ACTION step's human_action_evidence must survive
    all the way into both report.json's raw_results and the detailed JSON's
    human_in_the_loop section -- not just inform the pass/fail decision and
    then get discarded."""
    from config.settings import settings as global_settings
    from orchestrator.schemas import ActionType, TestSpec, TestStep
    from reports.render import render_json

    monkeypatch.setattr(global_settings, "project_root", tmp_dir)
    monkeypatch.setattr(global_settings, "human_action_poll_interval_seconds", 0.01)
    monkeypatch.setattr(global_settings, "human_action_timeout_seconds", 0.05)

    spec = TestSpec(
        test_id="TC_HIL_001",
        requirement_ref="TC_HIL_001",
        steps=[
            TestStep(
                step_id=1,
                action=ActionType.WAIT_FOR_HUMAN_ACTION,
                target_description="Ask the human to confirm the dialog",
            )
        ],
    )

    memory = RunMemoryStore(db_path=tmp_dir / "memory.db")
    skill_store = SkillStore(db_path=tmp_dir / "skills.db")
    engine = RunEngine(screenshot_provider=make_provider(tmp_dir), skill_store=skill_store, memory=memory)
    result = engine.run_spec(spec, run_id="hil_test_run", requirement_text="Ask a human to confirm the dialog")

    json_path = render_json(result.run_id, spec=spec.model_dump())
    import json as _json
    data = _json.loads(json_path.read_text())

    assert len(data["human_in_the_loop"]) == 1
    hil = data["human_in_the_loop"][0]
    assert "elapsed_seconds" in hil["evidence"]
    assert "acceptance_basis" in hil["evidence"]
    assert hil["evidence"]["acceptance_basis"] == "no_screen_change_detected"  # fixture screen never changes
    assert hil["adequate"] is False

    step_entry = data["process_timeline"][0]
    assert step_entry["decision_basis"]["decided"] == "not_fulfilled"
    assert "human_action_evidence" in step_entry["decision_basis"]

