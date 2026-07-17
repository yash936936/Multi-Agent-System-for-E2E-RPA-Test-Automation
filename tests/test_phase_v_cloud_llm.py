"""
Phase V tests — dual API + local LLM generic backend (decisions.md D-044)

Covers:
  - CloudLLMBackend: config errors, egress-allowlist reuse, a real HTTP
    call against a mocked httpx.Client (OpenAI-compat request/response
    shape), non-200 handling.
  - `_default_backend()` resolving "cloud_llm" (registry wiring).
  - Settings' auto-detection matrix (local_first/cloud_first,
    require_llm_backend fail-fast) via a fresh Settings() construction,
    not the module-level singleton (so it doesn't depend on this
    sandbox's actual filesystem/.env state).
  - generate_spec's escalation policy: primary backend fails -> logged
    escalation to CloudLLMBackend if enabled, no escalation if disabled,
    no escalation at all when an explicit backend is passed in.

See docs/Roadmap.md's fourth remediation roadmap, Phase V, and
docs/decisions.md D-044.
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


def test_generate_spec_logs_when_escalation_also_fails(monkeypatch, caplog):
    monkeypatch.setattr(global_settings, "planner_backend", "heuristic")
    monkeypatch.setattr(global_settings, "enable_cloud_planner", True)

    class _AlsoFailsBackend:
        def generate(self, requirement_text: str) -> dict:
            raise RuntimeError("cloud also down")

    with patch("agents.planner.spec_generator._default_backend", return_value=_AlwaysFailsBackend()):
        with patch("agents.planner.spec_generator.CloudLLMBackend", return_value=_AlsoFailsBackend()):
            with caplog.at_level(logging.WARNING):
                with pytest.raises(RuntimeError, match="cloud also down"):
                    generate_spec(RequirementInput(requirement_text="click the button"))

    assert any("escalation to CloudLLMBackend also failed" in r.message for r in caplog.records)
    monkeypatch.setattr(global_settings, "enable_cloud_planner", False)
