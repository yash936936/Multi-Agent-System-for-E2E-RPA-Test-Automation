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


def test_check_planner_backend_anthropic_is_gone_not_just_disabled(monkeypatch):
    # 2026-07-13 (decisions.md D-018, roadmap Phase B): AnthropicBackend
    # was removed entirely, not disabled behind a flag. Setting
    # planner_backend to "anthropic" is now just an unknown-value error,
    # the same as any other typo -- there is no special-cased "needs
    # network flag" branch left to test.
    from aura.cli.preflight import check_planner_backend_available
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "planner_backend", "anthropic")
    ok, message = check_planner_backend_available()
    assert ok is False
    assert "unknown value 'anthropic'" in message
    assert "heuristic | local_llm" in message


def test_allow_network_calls_setting_no_longer_exists():
    # Confirms the escape-hatch flag was actually removed from Settings,
    # not just left unused.
    from config.settings import Settings

    assert not hasattr(Settings(), "allow_network_calls")


def test_spec_generator_has_no_anthropic_backend():
    # This test predates Phase V (decisions.md D-044), which
    # intentionally added a third backend, "cloud_llm" -- a generic
    # OpenAI-compatible HTTP client, not a reintroduction of the
    # AnthropicBackend removed in D-018 (no vendor SDK, no hardcoded
    # provider, off by default, gated by settings.enable_cloud_planner
    # plus the same egress allowlist every capability adapter already
    # uses). The two assertions that actually matter -- no AnthropicBackend
    # class exists, "anthropic" isn't a registry key -- are unchanged and
    # still the real point of this test; only the exact-membership check
    # below needed updating twice now -- once for cloud_llm (Phase V), and
    # again for hermes_agent (Phase W, decisions.md D-047) -- to reflect
    # the now-intentional four-backend registry.
    import agents.planner.spec_generator as sg

    assert not hasattr(sg, "AnthropicBackend")
    assert "anthropic" not in sg._BACKEND_REGISTRY
    assert set(sg._BACKEND_REGISTRY) == {"heuristic", "local_llm", "cloud_llm", "hermes_agent"}


def test_check_planner_backend_unknown_value(monkeypatch):
    from aura.cli.preflight import check_planner_backend_available
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "planner_backend", "totally_made_up")
    ok, message = check_planner_backend_available()
    assert ok is False
    assert "totally_made_up" in message


def test_check_planner_backend_empty_string_is_rejected_not_treated_as_unset(monkeypatch):
    # Regression test for a real failure a user hit: `AURA_PLANNER_BACKEND=`
    # (blank value) in .env parses to the literal empty string '', not
    # None -- so config/settings.py's auto-detect ("if planner_backend is
    # None") never runs, and '' is correctly rejected here as an unknown
    # value rather than silently treated as "let auto-detect decide."
    from aura.cli.preflight import check_planner_backend_available
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "planner_backend", "")
    ok, message = check_planner_backend_available()
    assert ok is False
    assert "unknown value ''" in message


def test_check_planner_backend_cloud_llm_ok_when_base_url_set(monkeypatch):
    # Regression test for the real bug: this check predated Phase V's
    # cloud_llm backend and only ever recognized heuristic/local_llm --
    # meaning a validly auto-detected/configured cloud_llm backend was
    # rejected here as "unknown", blocking startup for any operator who
    # configured it (e.g. pointing cloud_llm at Gemini's OpenAI-compatible
    # endpoint).
    from aura.cli.preflight import check_planner_backend_available
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "planner_backend", "cloud_llm")
    monkeypatch.setattr(global_settings, "cloud_llm_base_url", "https://generativelanguage.googleapis.com/v1beta/openai")
    ok, message = check_planner_backend_available()
    assert ok is True
    assert message is None


def test_check_planner_backend_cloud_llm_missing_base_url(monkeypatch):
    from aura.cli.preflight import check_planner_backend_available
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "planner_backend", "cloud_llm")
    monkeypatch.setattr(global_settings, "cloud_llm_base_url", None)
    ok, message = check_planner_backend_available()
    assert ok is False
    assert "AURA_CLOUD_LLM_BASE_URL" in message


def test_check_planner_backend_hermes_agent_ok_when_base_url_set(monkeypatch):
    # Same class of bug as cloud_llm above, for Phase W's hermes_agent
    # backend (D-047) -- this is the exact case that blocked a real user
    # whose .env had AURA_PLANNER_PRIORITY=hermes_first configured.
    from aura.cli.preflight import check_planner_backend_available
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "planner_backend", "hermes_agent")
    monkeypatch.setattr(global_settings, "hermes_agent_base_url", "http://localhost:8642")
    ok, message = check_planner_backend_available()
    assert ok is True
    assert message is None


def test_check_planner_backend_hermes_agent_missing_base_url(monkeypatch):
    from aura.cli.preflight import check_planner_backend_available
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "planner_backend", "hermes_agent")
    monkeypatch.setattr(global_settings, "hermes_agent_base_url", None)
    ok, message = check_planner_backend_available()
    assert ok is False
    assert "AURA_HERMES_AGENT_BASE_URL" in message


def test_run_preflight_or_exit_checks_both_tesseract_and_planner_backend(monkeypatch):
    from aura.cli import preflight

    monkeypatch.setattr(preflight, "check_tesseract_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_planner_backend_available", lambda: (False, "planner misconfigured"))

    import typer

    with pytest.raises(typer.Exit):
        preflight.run_preflight_or_exit()


def test_check_display_available_returns_false_gracefully_without_display():
    """
    Advisory check, never raises regardless of environment -- this sandbox
    has no display, so ok should be False with a friendly message rather
    than an uncaught NoDisplayError.
    """
    from aura.cli.preflight import check_display_available

    ok, message = check_display_available()
    assert isinstance(ok, bool)
    if not ok:
        assert message is not None


def test_check_playwright_browser_available_never_raises():
    from aura.cli.preflight import check_playwright_browser_available

    ok, message = check_playwright_browser_available()
    assert isinstance(ok, bool)
    if not ok:
        assert message is not None


def test_check_capability_adapter_dependencies_returns_list():
    from aura.cli.preflight import check_capability_adapter_dependencies

    warnings = check_capability_adapter_dependencies()
    assert isinstance(warnings, list)


def test_run_preflight_or_exit_does_not_block_on_advisory_failures(monkeypatch):
    """
    Even if display/Playwright checks fail, run_preflight_or_exit() must
    NOT raise -- these are advisory warnings only, never hard blockers,
    since plenty of legitimate runs (pure API/DB capability checks) don't
    need a display or a browser at all.
    """
    from aura.cli import preflight

    monkeypatch.setattr(preflight, "check_tesseract_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_planner_backend_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_display_available", lambda: (False, "no display"))
    monkeypatch.setattr(preflight, "check_playwright_browser_available", lambda: (False, "no playwright"))
    monkeypatch.setattr(preflight, "check_capability_adapter_dependencies", lambda: ["'boto3' isn't installed"])

    preflight.run_preflight_or_exit()  # should not raise


def test_run_doctor_returns_true_when_all_hard_checks_pass(monkeypatch):
    """
    AC2: `aura doctor` is a standalone report a user runs proactively, not
    tied to run_preflight_or_exit()'s raise-and-exit behavior. It must
    never raise, and should return True purely based on the two hard
    checks (Tesseract, planner backend) -- advisory failures (no display,
    no Playwright browser -- both true in this sandbox) must not flip it.
    """
    from aura.cli import preflight

    monkeypatch.setattr(preflight, "check_tesseract_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_planner_backend_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_display_available", lambda: (False, "no display"))
    monkeypatch.setattr(preflight, "check_playwright_browser_available", lambda: (False, "no browser"))
    monkeypatch.setattr(preflight, "check_capability_adapter_dependencies", lambda: [])

    assert preflight.run_doctor() is True  # advisory failures don't affect the verdict


def test_run_doctor_returns_false_when_a_hard_check_fails(monkeypatch):
    from aura.cli import preflight

    monkeypatch.setattr(preflight, "check_tesseract_available", lambda: (False, "tesseract missing"))
    monkeypatch.setattr(preflight, "check_planner_backend_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_display_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_playwright_browser_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_capability_adapter_dependencies", lambda: [])

    assert preflight.run_doctor() is False


def test_run_doctor_never_raises_even_with_every_check_failing(monkeypatch):
    """
    Unlike run_preflight_or_exit(), `aura doctor` must never raise
    typer.Exit itself -- it's a report, not a gate. The CLI command
    (aura/main.py's `doctor()`) is what turns a False return into an exit
    code, not run_doctor() itself.
    """
    from aura.cli import preflight

    monkeypatch.setattr(preflight, "check_tesseract_available", lambda: (False, "tesseract missing"))
    monkeypatch.setattr(preflight, "check_planner_backend_available", lambda: (False, "planner misconfigured"))
    monkeypatch.setattr(preflight, "check_display_available", lambda: (False, "no display"))
    monkeypatch.setattr(preflight, "check_playwright_browser_available", lambda: (False, "no browser"))
    monkeypatch.setattr(preflight, "check_capability_adapter_dependencies", lambda: ["'boto3' isn't installed"])

    assert preflight.run_doctor() is False  # must not raise


def test_aura_doctor_cli_command_exits_nonzero_on_hard_failure(monkeypatch):
    """
    Integration test for the actual `aura doctor` CLI wiring in
    aura/main.py -- confirms run_doctor()'s bool return is correctly
    turned into a process exit code via typer's CliRunner, the same
    mechanism a user's shell script would check.
    """
    from typer.testing import CliRunner

    from aura import main as aura_main
    from aura.cli import preflight

    monkeypatch.setattr(preflight, "check_tesseract_available", lambda: (False, "tesseract missing"))
    monkeypatch.setattr(preflight, "check_planner_backend_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_display_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_playwright_browser_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_capability_adapter_dependencies", lambda: [])

    result = CliRunner().invoke(aura_main.app, ["doctor"])
    assert result.exit_code == 1
    assert "tesseract missing" in result.stdout.lower() or "tesseract" in result.stdout.lower()


def test_aura_doctor_cli_command_exits_zero_when_healthy(monkeypatch):
    from typer.testing import CliRunner

    from aura import main as aura_main
    from aura.cli import preflight

    monkeypatch.setattr(preflight, "check_tesseract_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_planner_backend_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_display_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_playwright_browser_available", lambda: (True, None))
    monkeypatch.setattr(preflight, "check_capability_adapter_dependencies", lambda: [])

    result = CliRunner().invoke(aura_main.app, ["doctor"])
    assert result.exit_code == 0
