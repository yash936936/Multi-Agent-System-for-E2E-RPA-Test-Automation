"""
tests/test_crash_boundary_and_logging.py

AF1/AF2 (docs/decisions.md, Phase AF).

AF1: aura/main.py's main() -- the real console-script entry point now
(pyproject.toml: `aura = "aura.main:main"`, previously `aura.main:app`
with no boundary at all) -- must catch any genuinely unhandled exception
and turn it into a clean message + SystemExit(1), while leaving every
existing `raise typer.Exit(code=N)` control-flow path across the whole
CLI completely unaffected. (Ctrl-C/KeyboardInterrupt already exits 130
cleanly via Click's own built-in handling -- confirmed directly, not
assumed -- so _run_app_safely doesn't need special-case logic for it.)

AF2: config/logging_setup.configure_logging() must actually attach a
persistent, structured handler to the root logger -- previously nothing
in the codebase ever called logging.basicConfig()/attached a handler at
all, so every existing `logging.getLogger(__name__).info(...)` call
across the codebase (dozens of them) was silently going nowhere.
"""
from __future__ import annotations

import json
import logging

import pytest
import typer
from typer.testing import CliRunner

runner = CliRunner()


def _fresh_logging_state():
    """Undo configure_logging()'s idempotency sentinel + handlers between
    tests, so each test observes a truly unconfigured root logger, same
    as a fresh process would."""
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    if hasattr(root, "_aura_configured"):
        delattr(root, "_aura_configured")


# --------------------------------------------------------------------------
# AF2 -- logging_setup.configure_logging()
# --------------------------------------------------------------------------

def test_configure_logging_persists_a_message_to_the_log_file(tmp_path, monkeypatch):
    from config.logging_setup import configure_logging

    _fresh_logging_state()
    log_dir = tmp_path / "logs"
    configure_logging(log_dir=log_dir)

    logger = logging.getLogger("some.module.that.already.called.getLogger")
    logger.info("a real diagnostic message that must now be persisted")

    log_file = log_dir / "aura.log"
    assert log_file.exists()
    content = log_file.read_text()
    assert "a real diagnostic message that must now be persisted" in content

    # AF2's whole point: this must be structured (JSON), not just prose,
    # so it's greppable/jq-able the same way AB2's assertion_audit_log
    # already is for assertion evidence specifically.
    record = json.loads(content.strip().splitlines()[-1])
    assert record["message"] == "a real diagnostic message that must now be persisted"
    assert record["level"] == "INFO"
    assert record["logger"] == "some.module.that.already.called.getLogger"
    _fresh_logging_state()


def test_configure_logging_captures_exception_traceback(tmp_path):
    from config.logging_setup import configure_logging

    _fresh_logging_state()
    log_dir = tmp_path / "logs"
    configure_logging(log_dir=log_dir)

    logger = logging.getLogger("test.exc")
    try:
        raise ValueError("boom for the test")
    except ValueError:
        logger.error("something failed", exc_info=True)

    content = (log_dir / "aura.log").read_text()
    record = json.loads(content.strip().splitlines()[-1])
    assert "boom for the test" in record["exception"]
    assert "ValueError" in record["exception"]
    _fresh_logging_state()


def test_configure_logging_is_idempotent_does_not_duplicate_handlers(tmp_path):
    from config.logging_setup import configure_logging

    _fresh_logging_state()
    log_dir = tmp_path / "logs"
    configure_logging(log_dir=log_dir)
    handlers_after_first_call = len(logging.getLogger().handlers)
    configure_logging(log_dir=log_dir)  # second call must be a no-op
    handlers_after_second_call = len(logging.getLogger().handlers)

    assert handlers_after_first_call == handlers_after_second_call
    _fresh_logging_state()


# --------------------------------------------------------------------------
# AF1 -- aura/main.py's main() crash boundary
# --------------------------------------------------------------------------

def test_typer_exit_control_flow_is_unaffected_by_the_crash_boundary(monkeypatch):
    """
    The single most important property of AF1: it must NOT swallow the
    dozens of existing `raise typer.Exit(code=N)` calls across the CLI
    (e.g. `_exit_nonzero_if_failed`, `aura doctor`'s failure path, every
    "Usage: ..." error). Verified two ways: (1) empirically, directly
    against a throwaway Typer app, that Click's own standalone-mode
    main() already converts typer.Exit into a real SystemExit before it
    would ever reach an except Exception block wrapped around it (see
    the module docstring for the full reasoning) -- confirmed, not
    assumed -- and (2) here, through AURA's actual _run_app_safely.
    """
    import sys

    throwaway_app = typer.Typer()

    @throwaway_app.command()
    def foo():
        raise typer.Exit(code=7)

    @throwaway_app.command()
    def bar():
        pass  # a second command so Typer doesn't collapse to single-command mode

    monkeypatch.setattr(sys, "argv", ["prog", "foo"])

    from aura.main import _run_app_safely

    with pytest.raises(SystemExit) as exc_info:
        _run_app_safely(throwaway_app)
    assert exc_info.value.code == 7


def test_genuinely_unhandled_exception_is_caught_logged_and_exits_cleanly(monkeypatch, tmp_path, capsys):
    """
    The actual bug this phase was written for: a real Hermes-connection-
    refused + Gemini-503 double failure previously produced a raw,
    multi-hundred-line Python traceback with no persisted record and no
    clean message. Simulated here via a throwaway command that raises a
    genuinely unhandled RuntimeError.
    """
    import sys

    from config.logging_setup import configure_logging

    _fresh_logging_state()
    configure_logging(log_dir=tmp_path / "logs")

    throwaway_app = typer.Typer()

    @throwaway_app.command()
    def foo():
        raise RuntimeError("simulated genuinely unhandled failure")

    @throwaway_app.command()
    def bar():
        pass

    monkeypatch.setattr(sys, "argv", ["prog", "foo"])

    from aura.main import _run_app_safely

    with pytest.raises(SystemExit) as exc_info:
        _run_app_safely(throwaway_app)
    assert exc_info.value.code == 1

    printed = capsys.readouterr().out
    assert "unexpected error" in printed

    log_content = (tmp_path / "logs" / "aura.log").read_text()
    assert "simulated genuinely unhandled failure" in log_content
    assert "RuntimeError" in log_content
    _fresh_logging_state()


def test_keyboard_interrupt_exits_130_via_clicks_own_handling(monkeypatch):
    """
    Confirmed directly (not assumed): Click's own standalone-mode main()
    catches KeyboardInterrupt internally and converts it to
    SystemExit(130) *before* it ever reaches _run_app_safely's except
    Exception clause -- SystemExit isn't an Exception subclass, so this
    passes through untouched, same as typer.Exit's SystemExit conversion
    above. This test exists to pin that observed behavior down as a
    regression guard, not to claim _run_app_safely does anything special
    for Ctrl-C itself (it doesn't need to -- Click already gets this
    right).
    """
    import sys

    throwaway_app = typer.Typer()

    @throwaway_app.command()
    def foo():
        raise KeyboardInterrupt()

    @throwaway_app.command()
    def bar():
        pass

    monkeypatch.setattr(sys, "argv", ["prog", "foo"])

    from aura.main import _run_app_safely

    with pytest.raises(SystemExit) as exc_info:
        _run_app_safely(throwaway_app)
    assert exc_info.value.code == 130
