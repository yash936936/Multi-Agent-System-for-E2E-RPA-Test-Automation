"""
Phase W tests — real Hermes Agent integration + LLM semantic tie-break
(decisions.md D-047).

Covers:
  - HermesAgentClient: config errors, egress-allowlist reuse (same
    mechanism as CloudLLMBackend), a real HTTP call against a mocked
    httpx.Client (OpenAI-compat request/response shape), non-200 handling.
  - HermesAgentBackend: registry wiring, config error surfaced with a
    helpful message, generate() round-trips through HermesAgentClient.
  - agents/vision/llm_verifier.semantic_verify(): disabled-by-default
    fail-soft behavior, no-backend-configured fail-soft behavior, a real
    call round trip against a mocked client, and unparseable-response
    fail-soft behavior.
  - agents/vision/executor._apply_tie_break's new "llm_semantic" mode:
    falls through to highest_confidence when the verifier has no opinion,
    and honors the verifier's opinion when it does.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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
from orchestrator.schemas import RequirementInput
from config.settings import Settings


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
