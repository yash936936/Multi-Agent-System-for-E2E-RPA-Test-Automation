"""
tests/test_http_retry.py

AF5 (docs/decisions.md, Phase AF) regression tests for
orchestrator/http_retry.py's post_with_retry(), plus its wiring into
CloudLLMBackend.generate() and HermesAgentClient.chat().
"""
from __future__ import annotations

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
