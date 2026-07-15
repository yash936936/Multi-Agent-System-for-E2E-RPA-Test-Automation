"""
tests/test_parallel_execution.py

Phase J (decisions.md D-031): tests for the two concurrency changes --

1. `aura execute --all --parallel N` (aura/main.py) actually dispatches
   through a ThreadPoolExecutor and every requirement doc still gets run
   exactly once, regardless of N.
2. `api/routers/runs.py` no longer serializes every run behind a single
   process-wide `RunEngine` + lock -- each call to `_new_engine()` returns
   a fresh, independent instance, so two concurrent background tasks can
   never observe "Vision Core busy" (that message/behavior is gone).

`execute_cmd.execute_test` itself is monkeypatched here (same reasoning
as test_cli.py's module docstring: a real run needs a live display/
screenshot provider) -- these tests exercise the *dispatch* logic
(ThreadPoolExecutor wiring, per-target invocation, result collection),
not the underlying vision-execution pipeline, which is already covered
by tests/test_run_engine.py.
"""
from __future__ import annotations

import tempfile
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aura.cli import execute_cmd
from aura.main import app
from orchestrator.schemas import RunReport, RunStatus

runner = CliRunner()


@pytest.fixture()
def isolated_project_with_docs(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        tmp_dir = Path(d)
        from config.settings import settings as global_settings

        monkeypatch.setattr(global_settings, "project_root", tmp_dir)

        req_dir = tmp_dir / "requirements_input"
        req_dir.mkdir(parents=True, exist_ok=True)
        for i in range(4):
            (req_dir / f"doc_{i}.md").write_text(f"# TC-DOC-{i}\n\nGiven: navigate to https://example.com\n")

        yield tmp_dir


def _make_fake_report(test_id: str) -> RunReport:
    return RunReport(
        run_id=test_id.lower(),
        test_id=test_id,
        status=RunStatus.PASSED,
        total_steps=1,
        passed_steps=1,
        failed_steps=0,
        escalated_steps=0,
        healed_steps=0,
        step_results=[],
        report_paths={},
    )


def test_parallel_flag_runs_every_target_exactly_once(monkeypatch, isolated_project_with_docs: Path):
    calls: list[str] = []
    lock = threading.Lock()

    def fake_execute_test(test_id: str, **kwargs) -> RunReport:
        with lock:
            calls.append(test_id)
        return _make_fake_report(Path(test_id).stem.upper())

    monkeypatch.setattr(execute_cmd, "execute_test", fake_execute_test)

    result = runner.invoke(app, ["execute", "--all", "--yes", "--parallel", "3"])

    assert result.exit_code == 0, result.stdout
    assert len(calls) == 4
    assert len(set(calls)) == 4  # every doc ran exactly once, no duplicates/drops


def test_parallel_one_matches_sequential_behavior(monkeypatch, isolated_project_with_docs: Path):
    calls: list[str] = []

    def fake_execute_test(test_id: str, **kwargs) -> RunReport:
        calls.append(test_id)
        return _make_fake_report(Path(test_id).stem.upper())

    monkeypatch.setattr(execute_cmd, "execute_test", fake_execute_test)

    result = runner.invoke(app, ["execute", "--all", "--yes", "--parallel", "1"])

    assert result.exit_code == 0, result.stdout
    assert len(calls) == 4
    # Sequential path preserves requirements_input_dir's sorted-glob order.
    assert calls == sorted(calls)


def test_parallel_rejects_values_below_one(isolated_project_with_docs: Path):
    result = runner.invoke(app, ["execute", "--all", "--yes", "--parallel", "0"])
    assert result.exit_code != 0


def test_parallel_propagates_a_failed_run_as_nonzero_exit(monkeypatch, isolated_project_with_docs: Path):
    def fake_execute_test(test_id: str, **kwargs) -> RunReport:
        report = _make_fake_report(Path(test_id).stem.upper())
        report.status = RunStatus.FAILED
        return report

    monkeypatch.setattr(execute_cmd, "execute_test", fake_execute_test)

    result = runner.invoke(app, ["execute", "--all", "--yes", "--parallel", "2"])
    assert result.exit_code == 1


def test_api_new_engine_returns_independent_instances():
    """
    Phase J: the API layer must never hand out the same RunEngine
    instance twice -- that was the whole point of removing the
    module-level singleton + lock.
    """
    from api.routers import runs

    e1 = runs._new_engine()
    e2 = runs._new_engine()
    assert e1 is not e2


def test_api_runs_module_has_no_global_lock_or_singleton():
    """
    Regression guard: previously `_engine`/`_run_lock` module-level
    globals serialized every API run behind a single lock (any run
    submitted while another was in flight got a "Vision Core busy"
    failure instead of actually running). Phase J removed both.
    """
    from api.routers import runs

    assert not hasattr(runs, "_run_lock")
    assert not hasattr(runs, "_engine")
    assert not hasattr(runs, "_get_engine")
