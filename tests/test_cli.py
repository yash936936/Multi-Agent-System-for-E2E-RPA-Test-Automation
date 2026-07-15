"""
tests/test_cli.py

Exercises the CLI commands that don't require a live display (init,
skills, schedule) via typer.testing.CliRunner. `aura execute` against a
real target app needs an actual screen (see aura/cli/execute_cmd.py's
_make_screenshot_provider docstring) so it isn't covered here -- the
underlying pipeline it wires together is already covered end-to-end by
tests/test_run_engine.py and tests/test_reports.py.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aura.main import app

runner = CliRunner()


@pytest.fixture()
def isolated_project(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        tmp_dir = Path(d)
        from config.settings import settings as global_settings

        monkeypatch.setattr(global_settings, "project_root", tmp_dir)
        yield tmp_dir


def test_init_non_interactive_writes_config(isolated_project: Path):
    result = runner.invoke(app, ["init", "--yes"])
    assert result.exit_code == 0

    config_path = isolated_project / "config" / "local_config.json"
    assert config_path.exists()


def test_init_env_scaffolds_profile_file(isolated_project: Path):
    result = runner.invoke(app, ["init", "--yes", "--env", "staging"])
    assert result.exit_code == 0

    profile_path = isolated_project / ".env.staging"
    assert profile_path.exists()
    assert "AURA environment profile: staging" in profile_path.read_text()


def test_init_env_does_not_overwrite_existing_profile(isolated_project: Path):
    profile_path = isolated_project / ".env.staging"
    profile_path.write_text("AURA_COMPRESSION_MODE=balanced\n")

    result = runner.invoke(app, ["init", "--yes", "--env", "staging"])
    assert result.exit_code == 0
    # Untouched -- scaffolding never clobbers a profile someone already edited.
    assert profile_path.read_text() == "AURA_COMPRESSION_MODE=balanced\n"


def test_top_level_env_flag_applies_profile_before_subcommand_runs(isolated_project: Path):
    (isolated_project / ".env.staging").write_text("AURA_COMPRESSION_MODE=balanced\n")

    result = runner.invoke(app, ["--env", "staging", "skills", "list"])
    assert result.exit_code == 0

    from config.settings import settings as global_settings

    assert global_settings.env == "staging"
    assert global_settings.compression_mode == "balanced"

    # Clean up so this doesn't leak into other tests sharing the process-wide singleton.
    global_settings.reload_profile(None)


def test_skills_list_empty(isolated_project: Path):
    result = runner.invoke(app, ["skills", "list"])
    assert result.exit_code == 0
    assert "No skills learned yet" in result.stdout


def test_skills_export_to_file(isolated_project: Path):
    out_file = isolated_project / "pack.json"
    result = runner.invoke(app, ["skills", "export", "--out", str(out_file)])
    assert result.exit_code == 0
    assert out_file.exists()
    assert '"format": "agentskills.io/v1"' in out_file.read_text()


def test_schedule_list_empty(isolated_project: Path):
    result = runner.invoke(app, ["schedule", "list"])
    assert result.exit_code == 0
    assert "No scheduled jobs" in result.stdout


def test_schedule_add_then_list(isolated_project: Path):
    add_result = runner.invoke(app, ["schedule", "add", "0 2 * * *", "TC-LOGIN-FLOW-001"])
    assert add_result.exit_code == 0
    assert "Scheduled" in add_result.stdout

    list_result = runner.invoke(app, ["schedule", "list"])
    assert "TC-LOGIN-FLOW-001" in list_result.stdout


def test_schedule_remove_unknown_job(isolated_project: Path):
    result = runner.invoke(app, ["schedule", "remove", "job_does_not_exist"])
    assert result.exit_code == 0
    assert "No such job" in result.stdout


def test_execute_without_all_or_test_id_errors(isolated_project: Path):
    result = runner.invoke(app, ["execute"])
    assert result.exit_code != 0


def test_build_url_smoke_requirement_normalizes_bare_domain():
    # Regression test for a real bug: aura execute --url example.com (no
    # scheme) previously produced "Given: navigate to example.com", which
    # _NAVIGATE_PATTERNS (https?://... only) never matches -- silently
    # zero steps, then a crash in TestSpec's "at least one step" validator.
    from aura.cli.execute_cmd import _build_url_smoke_requirement
    from agents.planner.spec_generator import generate_spec
    from orchestrator.schemas import ActionType, RequirementInput

    text = _build_url_smoke_requirement("example.com")
    assert "https://example.com" in text

    spec = generate_spec(RequirementInput(requirement_text=text))
    assert spec.steps[0].action == ActionType.NAVIGATE_URL
    assert spec.steps[0].url == "https://example.com"


def test_build_url_smoke_requirement_leaves_full_url_untouched():
    from aura.cli.execute_cmd import _build_url_smoke_requirement

    text = _build_url_smoke_requirement("https://example.com/login")
    assert "https://example.com/login" in text
    assert "https://https://" not in text


def test_execute_prompt_runs_fully_unattended(monkeypatch, tmp_path):
    from aura.cli import execute_cmd

    calls = {}

    def fake_run(requirement_text, display_source, auto_approve, refresh_data, export_pdf, scroll_test=False, ui_audit=False, junit_out=None, junit_suite_collector=None):
        calls["requirement_text"] = requirement_text
        calls["auto_approve"] = auto_approve
        calls["scroll_test"] = scroll_test
        calls["junit_out"] = junit_out
        return None  # execute_prompt just forwards this return value; real callers get a RunReport

    monkeypatch.setattr(execute_cmd, "_run_requirement_text", fake_run)

    execute_cmd.execute_prompt("Check the homepage loads correctly", url="https://example.com", scroll_test=True)

    assert calls["auto_approve"] is True
    assert "navigate to https://example.com" in calls["requirement_text"]
    assert "Check the homepage loads correctly" in calls["requirement_text"]
    assert calls["scroll_test"] is True
    assert calls["junit_out"] is None


def test_execute_prompt_forwards_junit_out(monkeypatch):
    # Phase G2 (decisions.md D-026): confirm --junit-out actually reaches
    # _run_requirement_text rather than being silently dropped anywhere
    # along execute_prompt's forwarding chain.
    from aura.cli import execute_cmd

    calls = {}

    def fake_run(requirement_text, display_source, auto_approve, refresh_data, export_pdf, scroll_test=False, ui_audit=False, junit_out=None, junit_suite_collector=None):
        calls["junit_out"] = junit_out

    monkeypatch.setattr(execute_cmd, "_run_requirement_text", fake_run)
    execute_cmd.execute_prompt("Check the homepage loads correctly", junit_out="/tmp/results.xml")
    assert calls["junit_out"] == "/tmp/results.xml"
