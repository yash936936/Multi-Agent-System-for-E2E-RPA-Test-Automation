"""Merged test file: test_cloud_llm_backends.py
Consolidated from: test_phase_v_cloud_llm.py, test_phase_w_hermes_and_llm_verifier.py
All original test functions preserved 1:1. Colliding fixture/helper names
renamed with a source-file suffix to avoid silent shadowing across sections.
"""
from __future__ import annotations
import logging
from unittest.mock import MagicMock, patch
import pytest
from agents.planner.spec_generator import (
    CloudLLMBackend,
    CloudLLMConfigError,
    CloudLLMEgressBlockedError,
    LocalHeuristicBackend,
    _default_backend,
    generate_spec,
)
from config.settings import Settings, settings as global_settings
from orchestrator.schemas import RequirementInput
from agents.planner.spec_generator import (
    HermesAgentBackend,
    HermesAgentConfigError,
    _default_backend,
)
from agents.vision import llm_verifier
from agents.vision.executor import _apply_tie_break
from config.settings import settings as global_settings
from orchestrator.hermes_client import (
    HermesAgentClient,
    HermesAgentConfigError as ClientConfigError,
    HermesAgentEgressBlockedError,
)
from orchestrator.schemas import RequirementInput, DiagnosisInput, TestStep, ActionType
from config.settings import Settings
from agents.planner.diagnoser import HermesAgentDiagnoser, LocalHeuristicDiagnoser, _default_backend as _diagnoser_default_backend


# ============================================================================
# ---- from test_phase_v_cloud_llm.py ----
# ============================================================================
# --------------------------------------------------------------------------
# CloudLLMBackend
# --------------------------------------------------------------------------

def test_cloud_llm_backend_requires_base_url(monkeypatch):
    monkeypatch.setattr(global_settings, "cloud_llm_base_url", None)
    backend = CloudLLMBackend(base_url=None, model="gpt-4o-mini")
    with pytest.raises(CloudLLMConfigError, match="cloud_llm_base_url"):
        backend.generate("some requirement text")


def test_cloud_llm_backend_requires_model():
    backend = CloudLLMBackend(base_url="https://api.openai.com/v1", model=None)
    with pytest.raises(CloudLLMConfigError, match="cloud_llm_model"):
        backend.generate("some requirement text")


def test_cloud_llm_backend_blocks_disallowed_host(monkeypatch):
    monkeypatch.setattr(global_settings, "allowed_capability_hosts", ["api.openai.com"])
    backend = CloudLLMBackend(base_url="https://evil.example.com/v1", model="gpt-4o-mini")
    with pytest.raises(CloudLLMEgressBlockedError, match="evil.example.com"):
        backend.generate("some requirement text")
    monkeypatch.setattr(global_settings, "allowed_capability_hosts", None)


def test_cloud_llm_backend_allows_allowlisted_host(monkeypatch):
    monkeypatch.setattr(global_settings, "allowed_capability_hosts", ["api.openai.com"])
    backend = CloudLLMBackend(
        base_url="https://api.openai.com/v1", api_key="sk-test", model="gpt-4o-mini"
    )

    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {
        "choices": [{"message": {"content": '{"test_id": "TC-CLOUD-001", "steps": []}'}}]
    }
    fake_client = MagicMock()
    fake_client.post.return_value = fake_response

    with patch("httpx.Client", return_value=fake_client):
        result = backend.generate("some requirement text")

    assert result == {"test_id": "TC-CLOUD-001", "steps": []}
    call = fake_client.post.call_args
    assert call.args[0] == "https://api.openai.com/v1/chat/completions"
    assert call.kwargs["headers"]["Authorization"] == "Bearer sk-test"
    assert call.kwargs["json"]["model"] == "gpt-4o-mini"
    monkeypatch.setattr(global_settings, "allowed_capability_hosts", None)


def test_cloud_llm_backend_no_auth_header_without_api_key():
    backend = CloudLLMBackend(base_url="https://api.openai.com/v1", api_key=None, model="gpt-4o-mini")
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {
        "choices": [{"message": {"content": '{"test_id": "TC-CLOUD-002", "steps": []}'}}]
    }
    fake_client = MagicMock()
    fake_client.post.return_value = fake_response

    with patch("httpx.Client", return_value=fake_client):
        backend.generate("some requirement text")

    call = fake_client.post.call_args
    assert "Authorization" not in call.kwargs["headers"]


def test_cloud_llm_backend_raises_on_non_200():
    backend = CloudLLMBackend(base_url="https://api.openai.com/v1", model="gpt-4o-mini")
    fake_response = MagicMock(status_code=500, text="internal server error")
    fake_client = MagicMock()
    fake_client.post.return_value = fake_response

    with patch("httpx.Client", return_value=fake_client):
        with pytest.raises(RuntimeError, match="status 500"):
            backend.generate("some requirement text")


def test_cloud_llm_backend_reuses_capability_router_allowlist_function(monkeypatch):
    """
    Confirms Phase V actually calls Phase D's existing allowlist function
    (not a re-implementation) -- patches
    orchestrator.capability_router.is_egress_host_allowed directly and
    checks it's consulted.
    """
    from orchestrator import capability_router

    backend = CloudLLMBackend(base_url="https://api.openai.com/v1", model="gpt-4o-mini")
    with patch.object(capability_router, "is_egress_host_allowed", return_value=False) as mock_check:
        with pytest.raises(CloudLLMEgressBlockedError):
            backend.generate("some requirement text")
    mock_check.assert_called_once_with("api.openai.com")


# --------------------------------------------------------------------------
# _default_backend registry wiring
# --------------------------------------------------------------------------

def test_default_backend_resolves_cloud_llm_when_configured(monkeypatch):
    monkeypatch.setattr(global_settings, "planner_backend", "cloud_llm")
    backend = _default_backend()
    assert isinstance(backend, CloudLLMBackend)


# --------------------------------------------------------------------------
# Settings auto-detection matrix (fresh Settings() instances, not the
# module-level singleton, so these don't depend on this sandbox's actual
# models/ directory or .env contents)
# --------------------------------------------------------------------------

def test_detection_matrix_defaults_to_heuristic_with_nothing_available(tmp_path, monkeypatch):
    s = Settings(project_root=tmp_path, planner_backend=None, enable_cloud_planner=False, cloud_llm_base_url=None)
    assert s.planner_backend == "heuristic"


def test_detection_matrix_prefers_cloud_when_local_unavailable(tmp_path, monkeypatch):
    s = Settings(
        project_root=tmp_path,
        planner_backend=None,
        enable_cloud_planner=True,
        cloud_llm_base_url="https://api.openai.com/v1",
    )
    assert s.planner_backend == "cloud_llm"


def test_detection_matrix_local_first_prefers_local_when_both_available(tmp_path, monkeypatch):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "tiny.gguf").write_bytes(b"fake")

    s = Settings(
        project_root=tmp_path,
        planner_backend=None,
        enable_cloud_planner=True,
        cloud_llm_base_url="https://api.openai.com/v1",
        planner_priority="local_first",
    )
    assert s.planner_backend == "local_llm"
    assert s.local_llm_model_path == str(models_dir / "tiny.gguf")


def test_detection_matrix_cloud_first_prefers_cloud_when_both_available(tmp_path, monkeypatch):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "tiny.gguf").write_bytes(b"fake")

    s = Settings(
        project_root=tmp_path,
        planner_backend=None,
        enable_cloud_planner=True,
        cloud_llm_base_url="https://api.openai.com/v1",
        planner_priority="cloud_first",
    )
    assert s.planner_backend == "cloud_llm"


def test_detection_matrix_rejects_unknown_priority(tmp_path, monkeypatch):
    with pytest.raises(Exception, match="Unknown settings.planner_priority"):
        Settings(project_root=tmp_path, planner_backend=None, planner_priority="fastest_first")


def test_require_llm_backend_fails_fast_when_nothing_available(tmp_path, monkeypatch):
    with pytest.raises(Exception, match="require_llm_backend is True but no LLM backend is usable"):
        Settings(
            project_root=tmp_path,
            planner_backend=None,
            enable_cloud_planner=False,
            cloud_llm_base_url=None,
            require_llm_backend=True,
        )


def test_require_llm_backend_succeeds_when_cloud_available(tmp_path, monkeypatch):
    s = Settings(
        project_root=tmp_path,
        planner_backend=None,
        enable_cloud_planner=True,
        cloud_llm_base_url="https://api.openai.com/v1",
        require_llm_backend=True,
    )
    assert s.planner_backend == "cloud_llm"


def test_explicit_planner_backend_bypasses_detection_matrix_entirely(tmp_path, monkeypatch):
    """An explicit AURA_PLANNER_BACKEND always wins -- require_llm_backend
    and the detection matrix only apply to the None/auto-detect case."""
    s = Settings(project_root=tmp_path, planner_backend="heuristic", require_llm_backend=True)
    assert s.planner_backend == "heuristic"


# --------------------------------------------------------------------------
# generate_spec escalation policy
# --------------------------------------------------------------------------

class _AlwaysFailsBackend:
    def generate(self, requirement_text: str) -> dict:
        raise RuntimeError("primary backend is down")


class _FakeCloudBackend:
    def generate(self, requirement_text: str) -> dict:
        return {
            "test_id": "TC-ESCALATED-001",
            "requirement_ref": "TC-ESCALATED-001",
            "preconditions": [],
            "steps": [{"step_id": 1, "action": "visual_click", "target_description": "Login button"}],
        }


def test_explicit_backend_never_escalates_even_if_cloud_enabled(monkeypatch, caplog):
    """Passing `backend=` explicitly opts out of the escalation policy
    entirely -- matches every pre-Phase-V caller's expectations."""
    monkeypatch.setattr(global_settings, "enable_cloud_planner", True)
    with pytest.raises(RuntimeError, match="primary backend is down"):
        generate_spec(RequirementInput(requirement_text="click the button"), backend=_AlwaysFailsBackend())
    monkeypatch.setattr(global_settings, "enable_cloud_planner", False)


def test_generate_spec_escalates_to_cloud_when_primary_fails_and_cloud_enabled(monkeypatch, caplog):
    monkeypatch.setattr(global_settings, "planner_backend", "heuristic")
    monkeypatch.setattr(global_settings, "enable_cloud_planner", True)

    with patch("agents.planner.spec_generator._default_backend", return_value=_AlwaysFailsBackend()):
        with patch("agents.planner.spec_generator.CloudLLMBackend", return_value=_FakeCloudBackend()):
            with caplog.at_level(logging.WARNING):
                spec = generate_spec(RequirementInput(requirement_text="click the button"))

    assert spec.test_id == "TC-ESCALATED-001"
    assert any("escalating" in r.message for r in caplog.records)
    monkeypatch.setattr(global_settings, "enable_cloud_planner", False)


def test_generate_spec_does_not_escalate_when_cloud_disabled(monkeypatch):
    monkeypatch.setattr(global_settings, "enable_cloud_planner", False)

    with patch("agents.planner.spec_generator._default_backend", return_value=_AlwaysFailsBackend()):
        with pytest.raises(RuntimeError, match="primary backend is down"):
            generate_spec(RequirementInput(requirement_text="click the button"))


def test_generate_spec_does_not_escalate_when_primary_is_already_cloud(monkeypatch):
    """Avoids a pointless self-escalation loop: if settings.planner_backend
    is already "cloud_llm", a failure must not retry against a second,
    freshly-constructed CloudLLMBackend instance."""
    monkeypatch.setattr(global_settings, "enable_cloud_planner", True)
    monkeypatch.setattr(global_settings, "planner_backend", "cloud_llm")

    class _FailingCloud(CloudLLMBackend):
        def generate(self, requirement_text: str) -> dict:
            raise RuntimeError("cloud backend is down")

    with patch("agents.planner.spec_generator._default_backend", return_value=_FailingCloud()):
        with pytest.raises(RuntimeError, match="cloud backend is down"):
            generate_spec(RequirementInput(requirement_text="click the button"))
    monkeypatch.setattr(global_settings, "enable_cloud_planner", False)


def test_generate_spec_falls_back_to_heuristic_when_escalation_also_fails(monkeypatch, caplog):
    """
    Bug fix (reported from a live run: Hermes connection refused + a
    transient Cloud 503 in the same run crashed the entire `aura execute`
    command). When both the primary backend and the CloudLLM escalation
    fail, generate_spec() now falls back to the fully-offline
    LocalHeuristicBackend as a last resort -- keeping the run alive with a
    lower-quality but real spec -- rather than raising and losing the
    whole run. Uses a real, parseable requirement so the heuristic
    fallback can genuinely succeed here, matching what a real run's
    already-decent requirement doc would do.
    """
    monkeypatch.setattr(global_settings, "planner_backend", "heuristic")
    monkeypatch.setattr(global_settings, "enable_cloud_planner", True)

    class _AlsoFailsBackend:
        def generate(self, requirement_text: str) -> dict:
            raise RuntimeError("cloud also down")

    with patch("agents.planner.spec_generator._default_backend", return_value=_AlwaysFailsBackend()):
        with patch("agents.planner.spec_generator.CloudLLMBackend", return_value=_AlsoFailsBackend()):
            with caplog.at_level(logging.WARNING):
                spec = generate_spec(RequirementInput(requirement_text="Click the login button."))

    assert spec.steps  # heuristic fallback actually produced a usable spec, not an empty/crashed run
    assert any("falling back to the fully-offline LocalHeuristicBackend" in r.message for r in caplog.records)
    monkeypatch.setattr(global_settings, "enable_cloud_planner", False)


def test_generate_spec_raises_original_error_when_heuristic_fallback_also_fails(monkeypatch, caplog):
    """
    The other half of the fallback: if even LocalHeuristicBackend fails
    (e.g. a requirement doc with no parseable actions at all), the
    original, more actionable network-failure error is what surfaces --
    not the heuristic's own less-informative parse failure -- with the
    heuristic failure chained on as __cause__ so it's still visible.
    """
    monkeypatch.setattr(global_settings, "planner_backend", "heuristic")
    monkeypatch.setattr(global_settings, "enable_cloud_planner", True)

    class _AlsoFailsBackend:
        def generate(self, requirement_text: str) -> dict:
            raise RuntimeError("cloud also down")

    with patch("agents.planner.spec_generator._default_backend", return_value=_AlwaysFailsBackend()):
        with patch("agents.planner.spec_generator.CloudLLMBackend", return_value=_AlsoFailsBackend()):
            with patch.object(LocalHeuristicBackend, "generate", side_effect=ValueError("heuristic also broke")):
                with caplog.at_level(logging.WARNING):
                    with pytest.raises(RuntimeError, match="cloud also down"):
                        generate_spec(RequirementInput(requirement_text="click the button"))

    assert any("escalation to CloudLLMBackend also failed" in r.message for r in caplog.records)
    assert any("fallback to LocalHeuristicBackend also failed" in r.message for r in caplog.records)
    monkeypatch.setattr(global_settings, "enable_cloud_planner", False)

# ============================================================================
# ---- from test_phase_w_hermes_and_llm_verifier.py ----
# ============================================================================
# --------------------------------------------------------------------------
# Phase X3: HermesAgentDiagnoser (decisions.md D-049)
# --------------------------------------------------------------------------

def _make_diagnosis_input():
    step = TestStep(
        step_id=1,
        action=ActionType.VISUAL_CLICK,
        target_description="the Submit button",
    )
    return DiagnosisInput(
        failed_step=step,
        execution_logs=["locate_text: not found", "confidence below threshold"],
    )


def test_diagnose_default_backend_is_heuristic(monkeypatch):
    monkeypatch.setattr(global_settings, "diagnosis_backend", "heuristic")
    assert isinstance(_diagnoser_default_backend(), LocalHeuristicDiagnoser)


def test_diagnose_default_backend_selects_hermes_when_configured(monkeypatch):
    monkeypatch.setattr(global_settings, "diagnosis_backend", "hermes_agent")
    assert isinstance(_diagnoser_default_backend(), HermesAgentDiagnoser)


def test_diagnose_default_backend_falls_back_on_unrecognized_value(monkeypatch):
    monkeypatch.setattr(global_settings, "diagnosis_backend", "something_typo'd")
    assert isinstance(_diagnoser_default_backend(), LocalHeuristicDiagnoser)


def test_hermes_agent_diagnoser_round_trip():
    fake_client = MagicMock()
    fake_client.chat.return_value = (
        '{"root_cause": "Button was relabeled", '
        '"proposed_fix": "Retry with relaxed OCR matching", '
        '"fix_type": "retry_strategy", "confidence": 0.75}'
    )
    diagnoser = HermesAgentDiagnoser(client=fake_client)
    result = diagnoser.diagnose(_make_diagnosis_input())

    assert result["root_cause"] == "Button was relabeled"
    assert result["proposed_fix"] == "Retry with relaxed OCR matching"
    assert result["fix_type"] == "retry_strategy"
    assert result["confidence"] == 0.75
    assert result["created_by"] == "hermes_agent_diagnoser"
    assert result["skill_id"].startswith("SKILL-")


def test_hermes_agent_diagnoser_raises_on_bad_json():
    fake_client = MagicMock()
    fake_client.chat.return_value = "not json at all"
    diagnoser = HermesAgentDiagnoser(client=fake_client)
    with pytest.raises(Exception):
        diagnoser.diagnose(_make_diagnosis_input())


# --------------------------------------------------------------------------
# Phase X follow-up: opt-in hermes_first auto-detection
# --------------------------------------------------------------------------

def test_hermes_agent_excluded_from_default_matrix(tmp_path):
    """A reachable/enabled Hermes config must NOT be auto-selected under
    the default local_first/cloud_first priorities -- only local_llm/
    cloud_llm compete there, per D-047."""
    s = Settings(
        project_root=tmp_path,
        planner_backend=None,
        enable_hermes_agent=True,
        hermes_agent_base_url="http://localhost:4141",
        planner_priority="local_first",
    )
    assert s.planner_backend == "heuristic"


def test_hermes_first_priority_selects_hermes_when_available(tmp_path):
    s = Settings(
        project_root=tmp_path,
        planner_backend=None,
        enable_hermes_agent=True,
        hermes_agent_base_url="http://localhost:4141",
        planner_priority="hermes_first",
    )
    assert s.planner_backend == "hermes_agent"


def test_hermes_first_falls_back_to_local_then_cloud(tmp_path):
    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "tiny.gguf").write_bytes(b"fake")

    s = Settings(
        project_root=tmp_path,
        planner_backend=None,
        enable_hermes_agent=False,
        planner_priority="hermes_first",
    )
    assert s.planner_backend == "local_llm"


def test_hermes_first_is_a_valid_priority_value(tmp_path):
    # Regression guard: hermes_first must not trip the "unknown priority"
    # validator that rejects arbitrary strings.
    s = Settings(project_root=tmp_path, planner_backend=None, planner_priority="hermes_first")
    assert s.planner_backend == "heuristic"


# --------------------------------------------------------------------------
# HermesAgentClient
# --------------------------------------------------------------------------

def test_hermes_client_requires_base_url(monkeypatch):
    monkeypatch.setattr(global_settings, "hermes_agent_base_url", None)
    client = HermesAgentClient(base_url=None)
    with pytest.raises(ClientConfigError, match="hermes_agent_base_url"):
        client.chat("system", "user")


def test_hermes_client_blocks_disallowed_host(monkeypatch):
    monkeypatch.setattr(global_settings, "allowed_capability_hosts", ["localhost"])
    client = HermesAgentClient(base_url="http://evil.example.com:4141")
    with pytest.raises(HermesAgentEgressBlockedError, match="evil.example.com"):
        client.chat("system", "user")
    monkeypatch.setattr(global_settings, "allowed_capability_hosts", None)


def test_hermes_client_successful_chat_call():
    client = HermesAgentClient(base_url="http://localhost:4141", api_key="test-key", model="hermes-agent")

    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"choices": [{"message": {"content": "hello from hermes"}}]}
    fake_client = MagicMock()
    fake_client.post.return_value = fake_response

    with patch("httpx.Client", return_value=fake_client):
        result = client.chat("system prompt", "user prompt")

    assert result == "hello from hermes"
    call = fake_client.post.call_args
    assert call.args[0] == "http://localhost:4141/v1/chat/completions"
    assert call.kwargs["headers"]["Authorization"] == "Bearer test-key"
    assert call.kwargs["json"]["messages"][0] == {"role": "system", "content": "system prompt"}


def test_hermes_client_session_id_header():
    client = HermesAgentClient(base_url="http://localhost:4141", session_id="transcript-alpha")
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    fake_client = MagicMock()
    fake_client.post.return_value = fake_response

    with patch("httpx.Client", return_value=fake_client):
        client.chat("s", "u")

    call = fake_client.post.call_args
    assert call.kwargs["headers"]["X-Hermes-Session-Id"] == "transcript-alpha"


def test_hermes_client_raises_on_non_200():
    client = HermesAgentClient(base_url="http://localhost:4141")
    fake_response = MagicMock(status_code=503, text="service unavailable")
    fake_client = MagicMock()
    fake_client.post.return_value = fake_response

    with patch("httpx.Client", return_value=fake_client):
        with pytest.raises(RuntimeError, match="status 503"):
            client.chat("s", "u")


# --------------------------------------------------------------------------
# HermesAgentBackend (planner backend registration)
# --------------------------------------------------------------------------

def test_hermes_agent_backend_registered_in_registry(monkeypatch):
    monkeypatch.setattr(global_settings, "planner_backend", "hermes_agent")
    backend = _default_backend()
    assert isinstance(backend, HermesAgentBackend)


def test_hermes_agent_backend_requires_base_url():
    backend = HermesAgentBackend(base_url=None)
    with pytest.raises(HermesAgentConfigError, match="hermes_agent_base_url"):
        backend.generate("some requirement text")


def test_hermes_agent_backend_generate_round_trip():
    backend = HermesAgentBackend(base_url="http://localhost:4141", model="hermes-agent")
    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {
        "choices": [{"message": {"content": '{"test_id": "TC-HERMES-001", "steps": []}'}}]
    }
    fake_client = MagicMock()
    fake_client.post.return_value = fake_response

    with patch("httpx.Client", return_value=fake_client):
        result = backend.generate("some requirement text")

    assert result == {"test_id": "TC-HERMES-001", "steps": []}


# --------------------------------------------------------------------------
# LLM semantic verifier
# --------------------------------------------------------------------------

class _FakeLocateResult:
    def __init__(self, found=True, matched_text=None, role=None, strategy=None):
        self.found = found
        self.matched_text = matched_text
        self.role = role
        self.strategy = strategy


def test_semantic_verify_disabled_by_default(monkeypatch):
    monkeypatch.setattr(global_settings, "enable_llm_semantic_verifier", False)
    ocr = _FakeLocateResult(matched_text="Submit")
    dom = _FakeLocateResult(matched_text="Cancel", role="button")
    assert llm_verifier.semantic_verify("the submit button", ocr, dom) is None


def test_semantic_verify_no_backend_configured(monkeypatch):
    monkeypatch.setattr(global_settings, "enable_llm_semantic_verifier", True)
    monkeypatch.setattr(global_settings, "enable_hermes_agent", False)
    monkeypatch.setattr(global_settings, "enable_cloud_planner", False)
    ocr = _FakeLocateResult(matched_text="Submit")
    dom = _FakeLocateResult(matched_text="Cancel", role="button")
    assert llm_verifier.semantic_verify("the submit button", ocr, dom) is None


def test_semantic_verify_uses_hermes_when_enabled(monkeypatch):
    monkeypatch.setattr(global_settings, "enable_llm_semantic_verifier", True)
    monkeypatch.setattr(global_settings, "enable_hermes_agent", True)
    monkeypatch.setattr(global_settings, "hermes_agent_base_url", "http://localhost:4141")

    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {
        "choices": [{"message": {"content": '{"winner": "ocr", "reason": "matches the label exactly"}'}}]
    }
    fake_client = MagicMock()
    fake_client.post.return_value = fake_response

    ocr = _FakeLocateResult(matched_text="Submit")
    dom = _FakeLocateResult(matched_text="Cancel", role="button")

    with patch("httpx.Client", return_value=fake_client):
        winner = llm_verifier.semantic_verify("the submit button", ocr, dom)

    assert winner == "ocr"
    monkeypatch.setattr(global_settings, "enable_hermes_agent", False)


def test_semantic_verify_fails_soft_on_unparseable_response(monkeypatch):
    monkeypatch.setattr(global_settings, "enable_llm_semantic_verifier", True)
    monkeypatch.setattr(global_settings, "enable_hermes_agent", True)
    monkeypatch.setattr(global_settings, "hermes_agent_base_url", "http://localhost:4141")

    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"choices": [{"message": {"content": "not json at all"}}]}
    fake_client = MagicMock()
    fake_client.post.return_value = fake_response

    ocr = _FakeLocateResult(matched_text="Submit")
    dom = _FakeLocateResult(matched_text="Cancel", role="button")

    with patch("httpx.Client", return_value=fake_client):
        winner = llm_verifier.semantic_verify("the submit button", ocr, dom)

    assert winner is None
    monkeypatch.setattr(global_settings, "enable_hermes_agent", False)


def test_semantic_verify_uses_cloud_llm_when_hermes_not_enabled(monkeypatch):
    """CloudLLMBackend is the second-priority path in _get_backend_client()
    -- exercised via a real (mocked-transport) request through its
    _ChatAdapter, not just the Hermes path above."""
    monkeypatch.setattr(global_settings, "enable_llm_semantic_verifier", True)
    monkeypatch.setattr(global_settings, "enable_hermes_agent", False)
    monkeypatch.setattr(global_settings, "enable_cloud_planner", True)
    monkeypatch.setattr(global_settings, "cloud_llm_base_url", "http://localhost:11434/v1")
    monkeypatch.setattr(global_settings, "cloud_llm_model", "mock-model")
    monkeypatch.setattr(global_settings, "allowed_capability_hosts", None)

    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {
        "choices": [{"message": {"content": '{"winner": "dom", "reason": "accessible name is exact"}'}}]
    }
    fake_client = MagicMock()
    fake_client.post.return_value = fake_response

    ocr = _FakeLocateResult(matched_text="Submit")
    dom = _FakeLocateResult(matched_text="Submit form", role="button")

    with patch("httpx.Client", return_value=fake_client):
        winner = llm_verifier.semantic_verify("the submit button", ocr, dom)

    assert winner == "dom"
    monkeypatch.setattr(global_settings, "enable_cloud_planner", False)


def test_semantic_verify_cloud_llm_path_respects_egress_allowlist(monkeypatch):
    """Regression test: the CloudLLM path of semantic_verify() used to
    build and send its own httpx request without ever calling
    is_egress_host_allowed(), even though CloudLLMBackend.generate() (the
    sibling class it borrows its client from) enforces that allowlist.
    A disallowed cloud_llm_base_url must fail soft to None here -- and,
    just as importantly, must never actually reach the network -- exactly
    like every other egress-controlled call site in this codebase."""
    monkeypatch.setattr(global_settings, "enable_llm_semantic_verifier", True)
    monkeypatch.setattr(global_settings, "enable_hermes_agent", False)
    monkeypatch.setattr(global_settings, "enable_cloud_planner", True)
    monkeypatch.setattr(global_settings, "cloud_llm_base_url", "http://localhost:11434/v1")
    monkeypatch.setattr(global_settings, "cloud_llm_model", "mock-model")
    monkeypatch.setattr(global_settings, "allowed_capability_hosts", ["some-other-host.example.com"])

    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {
        "choices": [{"message": {"content": '{"winner": "dom", "reason": "should never be reached"}'}}]
    }
    fake_client = MagicMock()
    fake_client.post.return_value = fake_response

    ocr = _FakeLocateResult(matched_text="Submit")
    dom = _FakeLocateResult(matched_text="Submit form", role="button")

    with patch("httpx.Client", return_value=fake_client):
        winner = llm_verifier.semantic_verify("the submit button", ocr, dom)

    assert winner is None
    fake_client.post.assert_not_called()  # the whole point of the fix: never even try
    monkeypatch.setattr(global_settings, "enable_cloud_planner", False)
    monkeypatch.setattr(global_settings, "allowed_capability_hosts", None)


# --------------------------------------------------------------------------
# executor._apply_tie_break's llm_semantic mode
# --------------------------------------------------------------------------

def test_apply_tie_break_llm_semantic_falls_back_when_no_opinion(monkeypatch):
    monkeypatch.setattr(global_settings, "enable_llm_semantic_verifier", False)
    ocr = MagicMock(found=True, matched_text="Submit", confidence=0.80)
    dom = MagicMock(found=True, matched_text="Cancel", confidence=0.90)
    winner = _apply_tie_break(ocr, dom, "llm_semantic", "the submit button")
    # No opinion available -> falls back to highest_confidence -> dom (0.90 >= 0.80)
    assert winner == "dom"


def test_apply_tie_break_llm_semantic_honors_verifier_opinion(monkeypatch):
    monkeypatch.setattr(
        "agents.vision.llm_verifier.semantic_verify",
        lambda target, ocr, dom: "ocr",
    )
    ocr = MagicMock(found=True, matched_text="Submit", confidence=0.60)
    dom = MagicMock(found=True, matched_text="Cancel", confidence=0.95)
    winner = _apply_tie_break(ocr, dom, "llm_semantic", "the submit button")
    # Verifier says "ocr" despite dom having higher confidence -- honored.
    assert winner == "ocr"


# ---- merged from tests/test_http_retry.py ----
"""
tests/test_http_retry.py

AF5 (docs/decisions.md, Phase AF) regression tests for
orchestrator/http_retry.py's post_with_retry(), plus its wiring into
CloudLLMBackend.generate() and HermesAgentClient.chat().
"""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from orchestrator.http_retry import post_with_retry


def _fake_client(*responses_or_exceptions):
    """A minimal fake httpx.Client whose .post() returns/raises each
    item in sequence, one per call."""
    client = MagicMock()
    client.post.side_effect = list(responses_or_exceptions)
    return client


def _resp(status_code: int) -> MagicMock:
    return MagicMock(status_code=status_code)


# --------------------------------------------------------------------------
# post_with_retry itself
# --------------------------------------------------------------------------

def test_succeeds_first_try_no_retry_needed():
    client = _fake_client(_resp(200))
    sleeps = []
    response = post_with_retry(client, "https://x/y", headers={}, json={}, sleep_fn=sleeps.append)
    assert response.status_code == 200
    assert client.post.call_count == 1
    assert sleeps == []  # never slept -- no retry happened


def test_retries_on_transport_error_then_succeeds():
    client = _fake_client(httpx.ConnectError("refused"), _resp(200))
    sleeps = []
    response = post_with_retry(client, "https://x/y", headers={}, json={}, sleep_fn=sleeps.append)
    assert response.status_code == 200
    assert client.post.call_count == 2
    assert len(sleeps) == 1  # exactly one backoff sleep before the successful retry


def test_retries_on_retryable_status_then_succeeds():
    client = _fake_client(_resp(503), _resp(200))
    sleeps = []
    response = post_with_retry(client, "https://x/y", headers={}, json={}, sleep_fn=sleeps.append)
    assert response.status_code == 200
    assert client.post.call_count == 2


def test_does_not_retry_on_non_retryable_status():
    """A 401 (bad API key) or 404 must surface immediately -- retrying a
    real configuration error just delays the operator finding out."""
    client = _fake_client(_resp(401))
    sleeps = []
    response = post_with_retry(client, "https://x/y", headers={}, json={}, sleep_fn=sleeps.append)
    assert response.status_code == 401
    assert client.post.call_count == 1
    assert sleeps == []


def test_gives_up_after_max_attempts_on_persistent_transport_error():
    client = _fake_client(httpx.ConnectError("refused"), httpx.ConnectError("refused"), httpx.ConnectError("refused"))
    sleeps = []
    with pytest.raises(httpx.ConnectError):
        post_with_retry(client, "https://x/y", headers={}, json={}, max_attempts=3, sleep_fn=sleeps.append)
    assert client.post.call_count == 3
    assert len(sleeps) == 2  # slept between attempts 1->2 and 2->3, not after the final failure


def test_gives_up_after_max_attempts_returns_final_retryable_response():
    """Unlike a transport error, a persistent 503 is returned (not
    raised) after retries are exhausted -- callers already have their
    own `if response.status_code != 200: raise ...` handling, which
    must still fire normally on this returned response."""
    client = _fake_client(_resp(503), _resp(503), _resp(503))
    sleeps = []
    response = post_with_retry(client, "https://x/y", headers={}, json={}, max_attempts=3, sleep_fn=sleeps.append)
    assert response.status_code == 503
    assert client.post.call_count == 3


def test_backoff_delay_grows_exponentially_and_is_capped():
    client = _fake_client(_resp(503), _resp(503), _resp(503), _resp(200))
    sleeps = []
    post_with_retry(
        client, "https://x/y", headers={}, json={}, max_attempts=4,
        base_delay_s=1.0, max_delay_s=2.5, sleep_fn=sleeps.append,
    )
    assert sleeps == [1.0, 2.0, 2.5]  # 1, 2, 4-capped-to-2.5


def test_recovered_after_retry_is_recorded_in_decision_trace_log():
    from orchestrator.decision_trace_log import DecisionTraceLog, read_records

    with tempfile.TemporaryDirectory() as d:
        trace_path = str(Path(d) / "decision_trace.jsonl")
        fresh_log = DecisionTraceLog(filepath=trace_path)
        with patch("orchestrator.http_retry.decision_trace_log", fresh_log):
            client = _fake_client(httpx.ConnectError("refused"), _resp(200))
            post_with_retry(
                client, "https://x/y", headers={}, json={}, sleep_fn=lambda s: None,
                caller_name="TestCaller", decision_trace_category="network_retry",
            )

        records = list(read_records(trace_path))
        assert len(records) == 1
        assert records[0]["decision"] == "recovered_after_retry"
        assert records[0]["backend"] == "TestCaller"


def test_gave_up_after_retries_is_recorded_in_decision_trace_log():
    from orchestrator.decision_trace_log import find_anomalies
    from orchestrator.decision_trace_log import DecisionTraceLog

    with tempfile.TemporaryDirectory() as d:
        trace_path = str(Path(d) / "decision_trace.jsonl")
        fresh_log = DecisionTraceLog(filepath=trace_path)
        with patch("orchestrator.http_retry.decision_trace_log", fresh_log):
            client = _fake_client(httpx.ConnectError("refused"), httpx.ConnectError("refused"), httpx.ConnectError("refused"))
            with pytest.raises(httpx.ConnectError):
                post_with_retry(
                    client, "https://x/y", headers={}, json={}, max_attempts=3, sleep_fn=lambda s: None,
                    caller_name="TestCaller", decision_trace_category="network_retry",
                )

        anomalies = find_anomalies(trace_path, category="network_retry")
        assert len(anomalies) == 1
        assert anomalies[0]["decision"] == "gave_up_after_retries"


# --------------------------------------------------------------------------
# Wiring into CloudLLMBackend and HermesAgentClient
# --------------------------------------------------------------------------

def test_cloud_llm_backend_recovers_from_transient_503(monkeypatch):
    from agents.planner.spec_generator import CloudLLMBackend
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "allowed_capability_hosts", None)
    backend = CloudLLMBackend(base_url="https://api.openai.com/v1", api_key="sk-test", model="gpt-4o-mini")

    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {
        "choices": [{"message": {"content": '{"test_id": "TC-RETRY-001", "steps": []}'}}]
    }
    fake_client = MagicMock()
    fake_client.post.side_effect = [MagicMock(status_code=503), fake_response]

    with patch("httpx.Client", return_value=fake_client):
        with patch("time.sleep"):  # this test would otherwise really wait ~1s
            result = backend.generate("some requirement text")

    assert result == {"test_id": "TC-RETRY-001", "steps": []}
    assert fake_client.post.call_count == 2


def test_hermes_agent_client_recovers_from_connection_refused_then_succeeds(monkeypatch):
    from orchestrator.hermes_client import HermesAgentClient
    from config.settings import settings as global_settings

    monkeypatch.setattr(global_settings, "allowed_capability_hosts", None)
    client_obj = HermesAgentClient(base_url="http://localhost:8642", api_key="k")

    fake_response = MagicMock(status_code=200)
    fake_response.json.return_value = {"choices": [{"message": {"content": "some spec text"}}]}
    fake_httpx_client = MagicMock()
    fake_httpx_client.post.side_effect = [httpx.ConnectError("refused"), fake_response]

    with patch("httpx.Client", return_value=fake_httpx_client):
        with patch("time.sleep"):
            result = client_obj.chat("system prompt", "user prompt")

    assert result == "some spec text"
    assert fake_httpx_client.post.call_count == 2
