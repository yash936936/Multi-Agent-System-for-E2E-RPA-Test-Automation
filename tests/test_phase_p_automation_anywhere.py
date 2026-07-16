"""
Phase P tests — agents/capability/automation_anywhere_adapter.py

P1: Control Room audit log retrieval (opt-in, read-only, best-effort,
    non-fatal on failure, one 401 re-auth retry).
P2: merge into evidence under `control_room_audit` (per-target and
    single-target back-compat top-level key).

See docs/Roadmap.md §10 (Phase P) and docs/decisions.md D-037.
"""
from unittest.mock import patch, MagicMock

from orchestrator.schemas import CapabilityCheckInput, CapabilityType
from agents.capability.automation_anywhere_adapter import AutomationAnywhereAdapter


def _mock_client(post_side_effect):
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.post.side_effect = post_side_effect
    return mock_client


def test_p1_off_by_default_no_extra_call():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="bot-1",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.example",
            "bot_id": "1",
            "poll_interval_seconds": 0,
            "timeout_seconds": 5,
        },
        expected={"terminal_status": "COMPLETED"},
    )
    deploy_response = MagicMock(status_code=201, content=b'{"deploymentId": "dep-1"}')
    deploy_response.json.return_value = {"deploymentId": "dep-1"}
    status_response = MagicMock(status_code=200)
    status_response.json.return_value = {"list": [{"deploymentId": "dep-1", "status": "COMPLETED"}]}

    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value = _mock_client([deploy_response, status_response])
        result = adapter.run(payload)

    assert result.passed is True
    assert "control_room_audit" not in result.evidence
    calls = mock_client_cls.return_value.post.call_args_list
    assert len(calls) == 2  # deploy + poll only, no auditlog call
    assert not any(c.args[0].endswith("/v2/auditlog/list") for c in calls)


def test_p1_fetches_audit_log_when_requested():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="bot-1",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.example",
            "bot_id": "1",
            "include_control_room_audit": True,
            "poll_interval_seconds": 0,
            "timeout_seconds": 5,
        },
        expected={"terminal_status": "COMPLETED"},
    )
    deploy_response = MagicMock(status_code=201, content=b'{"deploymentId": "dep-1"}')
    deploy_response.json.return_value = {"deploymentId": "dep-1"}
    status_response = MagicMock(status_code=200)
    status_response.json.return_value = {"list": [{"deploymentId": "dep-1", "status": "COMPLETED"}]}
    audit_response = MagicMock(status_code=200)
    audit_response.json.return_value = {"list": [{"auditId": "a-1", "action": "DEPLOY"}]}

    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value = _mock_client([deploy_response, status_response, audit_response])
        result = adapter.run(payload)

    assert result.passed is True
    assert result.evidence["control_room_audit"]["entries"] == [{"auditId": "a-1", "action": "DEPLOY"}]
    assert result.evidence["control_room_audit"]["fetch_error"] is None
    assert result.evidence["targets"]["dep-1"]["control_room_audit"]["entries"] == [
        {"auditId": "a-1", "action": "DEPLOY"}
    ]
    calls = mock_client_cls.return_value.post.call_args_list
    assert calls[2].args[0].endswith("/v2/auditlog/list")
    assert calls[2].kwargs["json"]["filter"]["value"] == "dep-1"


def test_p1_fetch_failure_is_non_fatal_and_recorded():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="bot-1",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.example",
            "bot_id": "1",
            "include_control_room_audit": True,
            "poll_interval_seconds": 0,
            "timeout_seconds": 5,
        },
        expected={"terminal_status": "COMPLETED"},
    )
    deploy_response = MagicMock(status_code=201, content=b'{"deploymentId": "dep-1"}')
    deploy_response.json.return_value = {"deploymentId": "dep-1"}
    status_response = MagicMock(status_code=200)
    status_response.json.return_value = {"list": [{"deploymentId": "dep-1", "status": "COMPLETED"}]}
    audit_response = MagicMock(status_code=500, content=b"")

    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value = _mock_client([deploy_response, status_response, audit_response])
        result = adapter.run(payload)

    # The trigger's own verdict is untouched by an audit-fetch failure --
    # the bot itself completed successfully, so this is still passed=True.
    assert result.passed is True
    assert result.evidence["control_room_audit"]["entries"] == []
    assert "500" in result.evidence["control_room_audit"]["fetch_error"]


def test_p1_reauthenticates_on_401_during_audit_fetch():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="bot-1",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.example",
            "bot_id": "1",
            "api_key": "some-key",
            "include_control_room_audit": True,
            "poll_interval_seconds": 0,
            "timeout_seconds": 5,
        },
        expected={"terminal_status": "COMPLETED"},
    )
    auth_response = MagicMock(status_code=200, content=b'{"token": "tok-1", "expiresIn": 3600}')
    auth_response.json.return_value = {"token": "tok-1", "expiresIn": 3600}
    deploy_response = MagicMock(status_code=201, content=b'{"deploymentId": "dep-1"}')
    deploy_response.json.return_value = {"deploymentId": "dep-1"}
    status_response = MagicMock(status_code=200)
    status_response.json.return_value = {"list": [{"deploymentId": "dep-1", "status": "COMPLETED"}]}
    audit_401 = MagicMock(status_code=401, content=b"")
    reauth_response = MagicMock(status_code=200, content=b'{"token": "tok-2", "expiresIn": 3600}')
    reauth_response.json.return_value = {"token": "tok-2", "expiresIn": 3600}
    audit_ok = MagicMock(status_code=200)
    audit_ok.json.return_value = {"list": [{"auditId": "a-2"}]}

    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value = _mock_client(
            [auth_response, deploy_response, status_response, audit_401, reauth_response, audit_ok]
        )
        result = adapter.run(payload)

    assert result.passed is True
    assert result.evidence["control_room_audit"]["entries"] == [{"auditId": "a-2"}]
    calls = mock_client_cls.return_value.post.call_args_list
    assert calls[5].kwargs["headers"]["X-Authorization"] == "tok-2"


def test_p2_multi_target_audit_breakdown_per_target():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="multi",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.example",
            "bot_id": ["101", "102"],
            "include_control_room_audit": True,
            "poll_interval_seconds": 0,
            "timeout_seconds": 5,
        },
        expected={"terminal_status": "COMPLETED"},
    )
    deploy_response = MagicMock(status_code=201, content=b'{"deploymentIds": ["dep-101", "dep-102"]}')
    deploy_response.json.return_value = {"deploymentIds": ["dep-101", "dep-102"]}
    status_response = MagicMock(status_code=200)
    status_response.json.return_value = {
        "list": [
            {"deploymentId": "dep-101", "status": "COMPLETED"},
            {"deploymentId": "dep-102", "status": "COMPLETED"},
        ]
    }
    audit_101 = MagicMock(status_code=200)
    audit_101.json.return_value = {"list": [{"auditId": "a-101"}]}
    audit_102 = MagicMock(status_code=200)
    audit_102.json.return_value = {"list": [{"auditId": "a-102"}]}

    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value = _mock_client(
            [deploy_response, status_response, audit_101, audit_102]
        )
        result = adapter.run(payload)

    assert result.passed is True
    assert "control_room_audit" not in result.evidence  # multi-target: no single top-level key
    assert result.evidence["targets"]["dep-101"]["control_room_audit"]["entries"] == [{"auditId": "a-101"}]
    assert result.evidence["targets"]["dep-102"]["control_room_audit"]["entries"] == [{"auditId": "a-102"}]
