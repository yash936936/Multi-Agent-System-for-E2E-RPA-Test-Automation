from __future__ import annotations

from pathlib import Path

import pytest

from agents.planner.diagnoser import diagnose
from agents.planner.parser import parse_requirement_file
from agents.planner.spec_generator import generate_spec
from orchestrator.schemas import (
    ActionType,
    DiagnosisInput,
    FixType,
    RequirementInput,
    TestStep,
)

SAMPLE_DOC = Path(__file__).resolve().parent.parent / "requirements_input" / "example_login_flow.md"


def test_parser_reads_login_flow_markdown():
    text = parse_requirement_file(SAMPLE_DOC)
    assert "Login button" in text
    assert "Username field" in text


def test_generate_spec_produces_schema_valid_test_spec():
    text = parse_requirement_file(SAMPLE_DOC)
    spec = generate_spec(RequirementInput(requirement_text=text))

    assert spec.test_id.startswith("TC-")
    assert len(spec.preconditions) == 2
    assert len(spec.steps) == 4  # click login, type username, type password, click submit


def test_generate_spec_step_actions_and_order():
    text = parse_requirement_file(SAMPLE_DOC)
    spec = generate_spec(RequirementInput(requirement_text=text))

    actions = [s.action for s in spec.steps]
    assert actions == [
        ActionType.VISUAL_CLICK,
        ActionType.TYPE_TEXT,
        ActionType.TYPE_TEXT,
        ActionType.VISUAL_CLICK,
    ]
    # step_ids are sequential starting at 1
    assert [s.step_id for s in spec.steps] == [1, 2, 3, 4]


def test_generate_spec_captures_login_and_submit_targets():
    text = parse_requirement_file(SAMPLE_DOC)
    spec = generate_spec(RequirementInput(requirement_text=text))

    click_targets = [s.target_description for s in spec.steps if s.action == ActionType.VISUAL_CLICK]
    assert any("Login button" in t for t in click_targets)
    assert any("Submit button" in t for t in click_targets)


def test_generate_spec_captures_assertion():
    text = parse_requirement_file(SAMPLE_DOC)
    spec = generate_spec(RequirementInput(requirement_text=text))

    assert len(spec.assertions) >= 1
    assert "dashboard" in spec.assertions[0].expected.lower()


def test_generate_spec_captures_data_requirements():
    text = parse_requirement_file(SAMPLE_DOC)
    spec = generate_spec(RequirementInput(requirement_text=text))

    assert "username" in spec.data_requirements
    assert "password" in spec.data_requirements
    assert any(d.startswith("edge_case_") for d in spec.data_requirements)


# --------------------------------------------------------------------------
# Regression tests: autonomous-mode requirement text used to produce zero
# steps, which failed TestSpec's "must contain at least one step" validator
# and crashed the run with:
#   "tool call 'Planner.generate_spec' failed: ... TestSpec must contain
#   at least one step"
# See api/routers/runs.py::create_run, which builds requirement_text as
# "Target: <url>\n\n<prompt>" (or just "Target: <url>" when prompt is
# empty) for mode == "autonomous".
# --------------------------------------------------------------------------

def test_generate_spec_autonomous_prompt_with_no_action_verbs_does_not_crash():
    # Mirrors the "Auto smoke" bug report exactly: target + a descriptive
    # prompt with no click/type/navigate phrasing.
    requirement_text = "Target: https://example.com\n\ncheck homepage loads"
    spec = generate_spec(RequirementInput(requirement_text=requirement_text))

    assert len(spec.steps) >= 1
    assert spec.steps[0].action == ActionType.NAVIGATE_URL
    assert spec.steps[0].url == "https://example.com"
    assert len(spec.assertions) >= 1


def test_generate_spec_autonomous_empty_prompt_does_not_crash():
    # Mirrors the second bug report: target set, prompt is an empty string.
    requirement_text = "Target: https://personal-portfolio-yashmalik.vercel.app/"
    spec = generate_spec(RequirementInput(requirement_text=requirement_text))

    assert len(spec.steps) >= 1
    assert spec.steps[0].action == ActionType.NAVIGATE_URL
    assert spec.steps[0].url == "https://personal-portfolio-yashmalik.vercel.app/"


def test_generate_spec_no_target_and_no_action_verbs_still_produces_valid_spec():
    # Defensive fallback: even with no URL and no recognizable action
    # verbs at all, generate_spec must never raise -- it should degrade to
    # an implicit page-loaded assertion rather than crash.
    spec = generate_spec(RequirementInput(requirement_text="Some vague, unstructured note."))

    assert len(spec.steps) == 1
    assert spec.steps[0].action == ActionType.ASSERT
    assert spec.steps[0].expected_state == "page_loaded"
    assert len(spec.assertions) == 1


def test_diagnose_returns_schema_valid_skill_record_for_not_found():
    step = TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login button")
    payload = DiagnosisInput(
        failed_step=step,
        before_screenshot="run_1/step_001_before.png",
        after_screenshot="run_1/step_001_after.png",
        execution_logs=["dispatched search", "target not found: Login button"],
    )
    record = diagnose(payload)
    assert record.skill_id.startswith("SKILL-")
    assert record.fix_type == FixType.RETRY_STRATEGY
    assert "login_button" in record.failure_signature.lower()


def test_diagnose_classifies_assertion_mismatch_as_spec_correction():
    step = TestStep(step_id=4, action=ActionType.ASSERT, expected_state="dashboard_visible")
    payload = DiagnosisInput(
        failed_step=step,
        execution_logs=["action succeeded", "assertion failed: unexpected state"],
    )
    record = diagnose(payload)
    assert record.fix_type == FixType.SPEC_CORRECTION


def test_diagnose_classifies_timeout():
    step = TestStep(step_id=2, action=ActionType.TYPE_TEXT, field_description="Username field")
    payload = DiagnosisInput(
        failed_step=step,
        execution_logs=["waiting for screen", "timed out after 5000ms"],
    )
    record = diagnose(payload)
    assert "timeout" in record.failure_signature


def test_diagnose_low_confidence_fallback_for_unclassified_logs():
    step = TestStep(step_id=9, action=ActionType.VISUAL_CLICK, target_description="Mystery button")
    payload = DiagnosisInput(failed_step=step, execution_logs=["something odd happened"])
    record = diagnose(payload)
    assert record.confidence < 0.5


# --------------------------------------------------------------------------
# LocalLLMBackend (decisions.md D-010) -- offline local-model planner path
# --------------------------------------------------------------------------

def test_local_llm_backend_raises_clear_error_when_no_model_path_configured(monkeypatch):
    from agents.planner import spec_generator
    from agents.planner.spec_generator import LocalLLMBackend, LocalLLMModelNotFoundError

    # LocalLLMBackend(model_path=None) falls back to the global settings
    # singleton -- force it clear here so this test doesn't depend on
    # whether the machine running it happens to have a real bundled model
    # (settings.local_llm_model_path is populated from .env/models/*.gguf
    # at import time, independent of this test's tmp_path).
    monkeypatch.setattr(spec_generator.settings, "local_llm_model_path", None)

    backend = LocalLLMBackend(model_path=None)
    with pytest.raises(LocalLLMModelNotFoundError, match="local_llm_model_path"):
        backend.generate("some requirement text")


def test_local_llm_backend_raises_clear_error_when_model_file_missing(tmp_path: Path):
    from agents.planner.spec_generator import LocalLLMBackend, LocalLLMModelNotFoundError

    missing_path = tmp_path / "does_not_exist.gguf"
    backend = LocalLLMBackend(model_path=str(missing_path))
    with pytest.raises(LocalLLMModelNotFoundError, match="no file exists"):
        backend.generate("some requirement text")


def test_extract_json_object_strips_markdown_fences():
    from agents.planner.spec_generator import _extract_json_object

    text = '```json\n{"test_id": "TC-X-001", "steps": []}\n```'
    result = _extract_json_object(text)
    assert result == {"test_id": "TC-X-001", "steps": []}


def test_extract_json_object_strips_preamble_prose():
    from agents.planner.spec_generator import _extract_json_object

    text = 'Here is the JSON:\n{"test_id": "TC-Y-001", "steps": []}\nHope that helps!'
    result = _extract_json_object(text)
    assert result["test_id"] == "TC-Y-001"


def test_extract_json_object_raises_on_no_json_present():
    from agents.planner.spec_generator import _extract_json_object

    with pytest.raises(ValueError, match="did not contain a JSON object"):
        _extract_json_object("I cannot help with that.")


def test_default_backend_resolves_heuristic_by_default(monkeypatch):
    from agents.planner.spec_generator import LocalHeuristicBackend, _default_backend
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "planner_backend", "heuristic")
    assert isinstance(_default_backend(), LocalHeuristicBackend)


def test_default_backend_resolves_local_llm_when_configured(monkeypatch):
    from agents.planner.spec_generator import LocalLLMBackend, _default_backend
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "planner_backend", "local_llm")
    # Construction alone must not require llama-cpp-python or a model file --
    # the model is loaded lazily on first .generate() call, not at construction.
    backend = _default_backend()
    assert isinstance(backend, LocalLLMBackend)


def test_default_backend_rejects_unknown_backend_name(monkeypatch):
    from agents.planner.spec_generator import _default_backend
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "planner_backend", "not_a_real_backend")
    with pytest.raises(ValueError, match="Unknown settings.planner_backend"):
        _default_backend()


def test_local_llm_backend_generate_spec_with_fake_model(monkeypatch):
    """
    Exercises generate_spec's full path with a fake backend standing in for
    a real local model, so this test runs without needing an actual .gguf
    file -- validates the plumbing (generate -> TestSpec.model_validate),
    not the model's own output quality (which needs a real model to judge).
    """
    from agents.planner.spec_generator import generate_spec

    class FakeLocalLLM:
        def generate(self, requirement_text: str) -> dict:
            return {
                "test_id": "TC-FAKE-LLM-001",
                "requirement_ref": "TC-FAKE-LLM-001",
                "preconditions": [],
                "steps": [
                    {"step_id": 1, "action": "visual_click", "target_description": "Login button"},
                ],
                "assertions": [],
                "data_requirements": [],
            }

    spec = generate_spec(RequirementInput(requirement_text="irrelevant, backend is faked"), backend=FakeLocalLLM())
    assert spec.test_id == "TC-FAKE-LLM-001"
    assert spec.steps[0].action == ActionType.VISUAL_CLICK


def test_generate_spec_detects_navigate_url_and_prepends_step():
    text = (
        "# Live URL Smoke Test\n\n"
        "Given: navigate to https://example.com/login\n\n"
        "The user clicks the Sign In button.\n"
        "The user enters a username into the Email field.\n"
    )
    spec = generate_spec(RequirementInput(requirement_text=text))

    assert spec.steps[0].action == ActionType.NAVIGATE_URL
    assert spec.steps[0].url == "https://example.com/login"
    assert spec.steps[0].step_id == 1
    # remaining steps renumbered to follow the navigate step
    assert [s.step_id for s in spec.steps] == list(range(1, len(spec.steps) + 1))
    assert any(s.action == ActionType.VISUAL_CLICK for s in spec.steps[1:])


def test_generate_spec_without_url_has_no_navigate_step():
    text = parse_requirement_file(SAMPLE_DOC)
    spec = generate_spec(RequirementInput(requirement_text=text))
    assert all(s.action != ActionType.NAVIGATE_URL for s in spec.steps)


def test_generate_spec_with_bare_domain_normalized_upstream_still_works():
    # Regression test for a real bug: _NAVIGATE_PATTERNS only matches
    # https?://..., so a bare domain slipped through generate_spec() with
    # zero navigate steps produced, leaving TestSpec.steps empty and
    # crashing the "must have at least one step" validator. The fix lives
    # in the CLI layer (runtime.hooks.browser.normalize_url is applied
    # before the requirement text is built) -- this test locks in that the
    # planner itself behaves correctly once a scheme is present, which is
    # the contract the CLI now guarantees it always gets.
    text = "# Smoke Test\n\nGiven: navigate to https://example.com\n\nThe user waits for the page to finish loading.\n"
    spec = generate_spec(RequirementInput(requirement_text=text))
    assert spec.steps[0].action == ActionType.NAVIGATE_URL
    assert spec.steps[0].url == "https://example.com"


def test_generate_spec_bare_domain_without_scheme_falls_back_instead_of_crashing():
    # A bare domain with no "https://" scheme still doesn't match any
    # _NAVIGATE_PATTERNS entry (by design -- ActionType.NAVIGATE_URL.url
    # needs a real URL), and "the user waits for the page to finish
    # loading" doesn't match any click/type pattern either. This used to
    # mean zero steps were produced, which crashed TestSpec's "must
    # contain at least one step" validator (the same class of bug as the
    # autonomous-mode "Target: <url>" crash above). generate_spec must
    # degrade to the implicit page-loaded fallback instead of raising.
    text = "# Smoke Test\n\nGiven: navigate to example.com\n\nThe user waits for the page to finish loading.\n"
    spec = generate_spec(RequirementInput(requirement_text=text))

    assert len(spec.steps) == 1
    assert spec.steps[0].action == ActionType.ASSERT
    assert spec.steps[0].expected_state == "page_loaded"
