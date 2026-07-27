"""
tests/test_parallel_execution.py

Phase J (decisions.md D-031): tests for the two concurrency changes --

1. `aura execute --all --parallel N` (aura/main.py) actually dispatches
   through a ThreadPoolExecutor and every requirement doc still gets run
   exactly once, regardless of N.
2. `api/routers/runs.py` no longer serializes every run behind a single
   process-wide `RunEngine` + lock -- each background task now calls
   `AuraBrain().handle(...)`, and the Brain's router builds a fresh
   `RunEngine` per call (docs/decisions.md D-079), so two
   concurrent background tasks can never observe "Vision Core busy"
   (that message/behavior is gone).

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


def test_brain_hands_out_independent_run_engine_instances():
    """
    Phase J (still true post-D-079): the API layer must never hand
    out the same RunEngine instance twice. `_new_engine()` was removed
    when api/routers/runs.py migrated onto AuraBrain -- the equivalent
    guarantee now lives in orchestrator/brain/router.py, which builds a
    fresh RunEngine inside `_handle_execute_requirement`
    on every call rather than reusing one across runs.
    """
    from unittest.mock import patch

    from orchestrator.brain.router import Router
    from orchestrator.brain.policy import Policy
    from orchestrator.brain.context import BrainKnowledge
    from orchestrator.brain.intent import Intent
    from orchestrator.run_engine import RunEngine

    seen: list[RunEngine] = []
    real_init = RunEngine.__init__

    def spy_init(self, *args, **kwargs):
        seen.append(self)
        return real_init(self, *args, **kwargs)

    router = Router(Policy(BrainKnowledge.load()))

    with patch.object(RunEngine, "__init__", spy_init):
        for _ in range(2):
            try:
                router.resolve(
                    Intent(
                        kind="execute_interactive",
                        caller="api",
                        params={"prompt": "noop", "timeout": 0, "screenshot_provider": lambda rid, i: ""},
                    )
                )
            except Exception:
                pass

    assert len(seen) == 2
    assert seen[0] is not seen[1]


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
