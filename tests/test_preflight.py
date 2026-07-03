"""
tests/test_preflight.py

Covers aura/cli/preflight.py -- the friendly, actionable "Tesseract not
found" message shown before a run starts, instead of letting a raw
pytesseract stack trace surface mid-run. Matters most for the packaged
.exe aimed at non-technical QA staff (decisions.md D-012).
"""
from __future__ import annotations

import pytest

from aura.cli.preflight import check_tesseract_available


def test_check_tesseract_available_returns_ok_true_when_tesseract_works(monkeypatch):
    import pytesseract

    monkeypatch.setattr(pytesseract, "get_tesseract_version", lambda: "5.3.0")
    ok, message = check_tesseract_available()
    assert ok is True
    assert message is None


def test_check_tesseract_available_gives_actionable_message_when_not_found(monkeypatch):
    import pytesseract

    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "tesseract_cmd", None)

    def raise_not_found():
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "get_tesseract_version", raise_not_found)
    ok, message = check_tesseract_available()
    assert ok is False
    assert "Tesseract" in message
    assert "github.com/UB-Mannheim/tesseract" in message
    assert "AURA_TESSERACT_CMD" in message


def test_check_tesseract_available_mentions_configured_path_when_set_but_wrong(monkeypatch):
    import pytesseract

    from config.settings import settings as global_settings

    # check_tesseract_available() sets pytesseract.pytesseract.tesseract_cmd as a
    # real side effect (same pattern as production _ocr_data()). Snapshot the
    # current value via monkeypatch *before* that happens, so monkeypatch's
    # teardown restores it afterward regardless of what gets assigned during
    # the test -- otherwise this test would permanently corrupt the real
    # tesseract_cmd for every test running later in the same pytest process
    # (this bug was caught by the full suite failing when run in file order).
    monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", pytesseract.pytesseract.tesseract_cmd)
    monkeypatch.setattr(global_settings, "tesseract_cmd", r"C:\wrong\path\tesseract.exe")

    def raise_not_found():
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "get_tesseract_version", raise_not_found)
    ok, message = check_tesseract_available()
    assert ok is False
    assert r"C:\wrong\path\tesseract.exe" in message


def test_check_tesseract_available_handles_unexpected_errors_gracefully(monkeypatch):
    import pytesseract

    def raise_weird_error():
        raise RuntimeError("something unrelated broke")

    monkeypatch.setattr(pytesseract, "get_tesseract_version", raise_weird_error)
    ok, message = check_tesseract_available()
    assert ok is False
    assert "something unrelated broke" in message


def test_run_preflight_or_exit_raises_typer_exit_on_failure(monkeypatch):
    import typer

    from aura.cli import preflight

    monkeypatch.setattr(preflight, "check_tesseract_available", lambda: (False, "test failure message"))
    with pytest.raises(typer.Exit):
        preflight.run_preflight_or_exit()


def test_run_preflight_or_exit_does_not_raise_when_ok(monkeypatch):
    from aura.cli import preflight

    monkeypatch.setattr(preflight, "check_tesseract_available", lambda: (True, None))
    preflight.run_preflight_or_exit()  # should not raise


def test_check_planner_backend_ok_for_default_heuristic(monkeypatch):
    from aura.cli.preflight import check_planner_backend_available
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "planner_backend", "heuristic")
    ok, message = check_planner_backend_available()
    assert ok is True
    assert message is None


def test_check_planner_backend_local_llm_missing_path(monkeypatch):
    # Regression test for a real failure a user hit: AURA_PLANNER_BACKEND
    # set to local_llm with no AURA_LOCAL_LLM_MODEL_PATH configured at all
    # previously surfaced as a raw LocalLLMModelNotFoundError traceback
    # from inside spec_generator.py mid-run instead of a clean pre-check.
    from aura.cli.preflight import check_planner_backend_available
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "planner_backend", "local_llm")
    monkeypatch.setattr(global_settings, "local_llm_model_path", None)
    ok, message = check_planner_backend_available()
    assert ok is False
    assert "AURA_LOCAL_LLM_MODEL_PATH" in message
    assert "heuristic" in message


def test_check_planner_backend_local_llm_nonexistent_path(monkeypatch):
    # The exact scenario a real user hit: the README's placeholder path
    # copy-pasted verbatim into a real .env.
    from aura.cli.preflight import check_planner_backend_available
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "planner_backend", "local_llm")
    monkeypatch.setattr(global_settings, "local_llm_model_path", r"C:\path\to\your-model.gguf")
    ok, message = check_planner_backend_available()
    assert ok is False
    assert "doesn't exist" in message
    assert "placeholder" in message


def test_check_planner_backend_local_llm_real_path_ok(monkeypatch, tmp_path):
    from aura.cli.preflight import check_planner_backend_available
    from config.settings import settings as global_settings

    real_model = tmp_path / "model.gguf"
    real_model.write_bytes(b"not a real gguf, just needs to exist")

    monkeypatch.setattr(global_settings, "planner_backend", "local_llm")
    monkeypatch.setattr(global_settings, "local_llm_model_path", str(real_model))
    ok, message = check_planner_backend_available()
    assert ok is True
    assert message is None


def test_check_planner_backend_anthropic_requires_network_flag(monkeypatch):
    from aura.cli.preflight import check_planner_backend_available
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "planner_backend", "anthropic")
    monkeypatch.setattr(global_settings, "allow_network_calls", False)
    ok, message = check_planner_backend_available()
    assert ok is False
    assert "AURA_ALLOW_NETWORK_CALLS" in message


def test_check_planner_backend_unknown_value(monkeypatch):
    from aura.cli.preflight import check_planner_backend_available
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "planner_backend", "totally_made_up")
    ok, message = check_planner_backend_available()
    assert ok is False
    assert "totally_made_up" in message


def test_run_preflight_or_exit_checks_both_tesseract_and_planner_backend(monkeypatch):
    from aura.cli import preflight

    monkeypatch.setattr(preflight, "check_tesseract_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_planner_backend_available", lambda: (False, "planner misconfigured"))

    import typer

    with pytest.raises(typer.Exit):
        preflight.run_preflight_or_exit()
