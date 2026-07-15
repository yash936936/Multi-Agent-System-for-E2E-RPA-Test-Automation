"""
Phase N tests — agents/capability/automation_anywhere_adapter.py

N1: Control Room authentication (login step, token cache, 401 re-auth,
    auth_token override back-compat).
N2: Multi-bot / multi-runner trigger (list bot_id/run_as_user_id fan-out,
    per-target status map, all_must_complete/any_must_complete rollup,
    per-target evidence breakdown).

See docs/Roadmap.md §10 (Phase N) and docs/decisions.md D-035.
"""
from unittest.mock import patch, MagicMock

from orchestrator.schemas import CapabilityCheckInput, CapabilityType
from agents.capability.automation_anywhere_adapter import AutomationAnywhereAdapter


def _mock_client(post_side_effect):
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.post.side_effect = post_side_effect
    return mock_client


# --- N1: Control Room authentication ---

def test_n1_logs_in_with_username_password_and_caches_token():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="bot-1",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.my.automationanywhere.digital",
            "bot_id": "1",
            "username": "svc-account",
            "password": "hunter2",
            "poll_interval_seconds": 0,
            "timeout_seconds": 5,
        },
        expected={"terminal_status": "COMPLETED"},
    )

    auth_response = MagicMock(status_code=200, content=b'{"token": "tok-abc", "expiresIn": 3600}')
    auth_response.json.return_value = {"token": "tok-abc", "expiresIn": 3600}
    deploy_response = MagicMock(status_code=201, content=b'{"deploymentId": "dep-1"}')
    deploy_response.json.return_value = {"deploymentId": "dep-1"}
    status_response = MagicMock(status_code=200)
    status_response.json.return_value = {"list": [{"deploymentId": "dep-1", "status": "COMPLETED"}]}

    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value = _mock_client([auth_response, deploy_response, status_response])
        result = adapter.run(payload)

    assert result.passed is True
    # Login happened, and the deploy call carried the token it returned.
    calls = mock_client_cls.return_value.post.call_args_list
    assert calls[0].args[0].endswith("/v1/authentication")
    assert calls[1].kwargs["headers"]["X-Authorization"] == "tok-abc"

    # Second call on the same adapter instance reuses the cached token —
    # no second /v1/authentication call.
    deploy_response_2 = MagicMock(status_code=201, content=b'{"deploymentId": "dep-2"}')
    deploy_response_2.json.return_value = {"deploymentId": "dep-2"}
    status_response_2 = MagicMock(status_code=200)
    status_response_2.json.return_value = {"list": [{"deploymentId": "dep-2", "status": "COMPLETED"}]}
    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls2:
        mock_client_cls2.return_value = _mock_client([deploy_response_2, status_response_2])
        result2 = adapter.run(payload)
    assert result2.passed is True
    calls2 = mock_client_cls2.return_value.post.call_args_list
    assert not calls2[0].args[0].endswith("/v1/authentication")


def test_n1_reauthenticates_on_401_instead_of_failing_the_run():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="bot-1",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.my.automationanywhere.digital",
            "bot_id": "1",
            "api_key": "some-api-key",
            "poll_interval_seconds": 0,
            "timeout_seconds": 5,
        },
        expected={"terminal_status": "COMPLETED"},
    )

    auth_response = MagicMock(status_code=200, content=b'{"token": "tok-1", "expiresIn": 3600}')
    auth_response.json.return_value = {"token": "tok-1", "expiresIn": 3600}
    deploy_401 = MagicMock(status_code=401, content=b"")
    reauth_response = MagicMock(status_code=200, content=b'{"token": "tok-2", "expiresIn": 3600}')
    reauth_response.json.return_value = {"token": "tok-2", "expiresIn": 3600}
    deploy_ok = MagicMock(status_code=201, content=b'{"deploymentId": "dep-9"}')
    deploy_ok.json.return_value = {"deploymentId": "dep-9"}
    status_response = MagicMock(status_code=200)
    status_response.json.return_value = {"list": [{"deploymentId": "dep-9", "status": "COMPLETED"}]}

    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value = _mock_client(
            [auth_response, deploy_401, reauth_response, deploy_ok, status_response]
        )
        result = adapter.run(payload)

    assert result.passed is True
    calls = mock_client_cls.return_value.post.call_args_list
    # First deploy failed with 401, second deploy (after re-auth) carried the new token.
    assert calls[3].kwargs["headers"]["X-Authorization"] == "tok-2"


def test_n1_auth_token_override_skips_login_entirely():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="bot-1",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.my.automationanywhere.digital",
            "bot_id": "1",
            "auth_token": "pre-supplied-token",
            "username": "ignored",
            "password": "ignored",
            "poll_interval_seconds": 0,
            "timeout_seconds": 5,
        },
        expected={"terminal_status": "COMPLETED"},
    )

    deploy_response = MagicMock(status_code=201, content=b'{"deploymentId": "dep-3"}')
    deploy_response.json.return_value = {"deploymentId": "dep-3"}
    status_response = MagicMock(status_code=200)
    status_response.json.return_value = {"list": [{"deploymentId": "dep-3", "status": "COMPLETED"}]}

    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value = _mock_client([deploy_response, status_response])
        result = adapter.run(payload)

    assert result.passed is True
    calls = mock_client_cls.return_value.post.call_args_list
    assert len(calls) == 2  # no /v1/authentication call at all
    assert calls[0].kwargs["headers"]["X-Authorization"] == "pre-supplied-token"


def test_n1_no_credentials_at_all_proceeds_unauthenticated():
    """Pre-Phase-N behavior preserved: no auth_token, no username/password,
    no api_key -> deploy proceeds without an X-Authorization header."""
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="bot-1",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.my.automationanywhere.digital",
            "bot_id": "1",
            "poll_interval_seconds": 0,
            "timeout_seconds": 5,
        },
        expected={"terminal_status": "COMPLETED"},
    )
    deploy_response = MagicMock(status_code=201, content=b'{"deploymentId": "dep-4"}')
    deploy_response.json.return_value = {"deploymentId": "dep-4"}
    status_response = MagicMock(status_code=200)
    status_response.json.return_value = {"list": [{"deploymentId": "dep-4", "status": "COMPLETED"}]}

    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value = _mock_client([deploy_response, status_response])
        result = adapter.run(payload)

    assert result.passed is True
    calls = mock_client_cls.return_value.post.call_args_list
    assert calls[0].kwargs["headers"] == {}


# --- N2: multi-bot / multi-runner trigger ---

def test_n2_fans_out_to_multiple_bot_ids_and_tracks_each_independently():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="multi",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.my.automationanywhere.digital",
            "bot_id": ["101", "102"],
            "run_as_user_id": ["1", "2"],
            "poll_interval_seconds": 0,
            "timeout_seconds": 5,
        },
        expected={"terminal_status": "COMPLETED"},  # default rollup: all_must_complete
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

    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value = _mock_client([deploy_response, status_response])
        result = adapter.run(payload)

    assert result.passed is True
    assert set(result.evidence["deployment_ids"]) == {"dep-101", "dep-102"}
    assert result.evidence["targets"]["dep-101"]["passed"] is True
    assert result.evidence["targets"]["dep-102"]["passed"] is True
    # deploy request actually carried the full fan-out list.
    deploy_call = mock_client_cls.return_value.post.call_args_list[0]
    assert deploy_call.kwargs["json"]["fileId"] == ["101", "102"]
    assert deploy_call.kwargs["json"]["runAsUserIds"] == ["1", "2"]


def test_n2_all_must_complete_fails_if_any_target_fails():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="multi",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.my.automationanywhere.digital",
            "bot_id": ["201", "202"],
            "poll_interval_seconds": 0,
            "timeout_seconds": 5,
        },
        expected={"terminal_status": "COMPLETED", "rollup": "all_must_complete"},
    )
    deploy_response = MagicMock(status_code=201, content=b'{"deploymentIds": ["dep-201", "dep-202"]}')
    deploy_response.json.return_value = {"deploymentIds": ["dep-201", "dep-202"]}
    status_response = MagicMock(status_code=200)
    status_response.json.return_value = {
        "list": [
            {"deploymentId": "dep-201", "status": "COMPLETED"},
            {"deploymentId": "dep-202", "status": "FAILED"},
        ]
    }

    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value = _mock_client([deploy_response, status_response])
        result = adapter.run(payload)

    assert result.passed is False
    assert result.escalate is True
    # The failing target is still visible, not swallowed by an aggregate status.
    assert result.evidence["targets"]["dep-201"]["passed"] is True
    assert result.evidence["targets"]["dep-202"]["passed"] is False


def test_n2_any_must_complete_passes_if_one_target_succeeds():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="multi",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.my.automationanywhere.digital",
            "bot_id": ["301", "302"],
            "poll_interval_seconds": 0,
            "timeout_seconds": 5,
        },
        expected={"terminal_status": "COMPLETED", "rollup": "any_must_complete"},
    )
    deploy_response = MagicMock(status_code=201, content=b'{"deploymentIds": ["dep-301", "dep-302"]}')
    deploy_response.json.return_value = {"deploymentIds": ["dep-301", "dep-302"]}
    status_response = MagicMock(status_code=200)
    status_response.json.return_value = {
        "list": [
            {"deploymentId": "dep-301", "status": "FAILED"},
            {"deploymentId": "dep-302", "status": "COMPLETED"},
        ]
    }

    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value = _mock_client([deploy_response, status_response])
        result = adapter.run(payload)

    assert result.passed is True
    assert result.evidence["targets"]["dep-301"]["passed"] is False
    assert result.evidence["targets"]["dep-302"]["passed"] is True


def test_n2_unknown_rollup_fails_cleanly():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="multi",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.my.automationanywhere.digital",
            "bot_id": ["1"],
        },
        expected={"rollup": "majority_vote"},
    )
    result = adapter.run(payload)
    assert result.passed is False
    assert "rollup" in result.evidence["error"]


def test_n2_single_bot_id_stays_scalar_shaped_for_back_compat():
    """A single bot_id (str, not list) must still produce the pre-Phase-N
    evidence shape (deployment_id / terminal_status / activity_record at
    the top level), not force every existing caller onto the new
    per-target dict."""
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="bot-single",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.my.automationanywhere.digital",
            "bot_id": "999",
            "poll_interval_seconds": 0,
            "timeout_seconds": 5,
        },
        expected={"terminal_status": "COMPLETED"},
    )
    deploy_response = MagicMock(status_code=201, content=b'{"deploymentId": "dep-999"}')
    deploy_response.json.return_value = {"deploymentId": "dep-999"}
    status_response = MagicMock(status_code=200)
    status_response.json.return_value = {"list": [{"deploymentId": "dep-999", "status": "COMPLETED"}]}

    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls:
        mock_client_cls.return_value = _mock_client([deploy_response, status_response])
        result = adapter.run(payload)

    assert result.passed is True
    assert result.evidence["deployment_id"] == "dep-999"
    assert result.evidence["terminal_status"] == "COMPLETED"
    assert "deployment_ids" not in result.evidence
    # deploy request sent a scalar fileId, not a single-element list, for a scalar bot_id.
    deploy_call = mock_client_cls.return_value.post.call_args_list[0]
    assert deploy_call.kwargs["json"]["fileId"] == "999"


def test_n2_timed_out_target_reported_independently_of_completed_target():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="multi",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.my.automationanywhere.digital",
            "bot_id": ["401", "402"],
            "poll_interval_seconds": 0,
            "timeout_seconds": 0.05,
        },
        expected={"terminal_status": "COMPLETED"},
    )
    deploy_response = MagicMock(status_code=201, content=b'{"deploymentIds": ["dep-401", "dep-402"]}')
    deploy_response.json.return_value = {"deploymentIds": ["dep-401", "dep-402"]}
    status_response = MagicMock(status_code=200)
    status_response.json.return_value = {
        "list": [{"deploymentId": "dep-401", "status": "COMPLETED"}]
    }

    # dep-401 completes immediately; dep-402 never shows up in any poll
    # response, so it must time out independently rather than blocking
    # or masking dep-401's real result. A long, repeated side_effect list
    # (rather than a fixed 2-3 entry one) tolerates however many poll
    # iterations the short timeout actually produces.
    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.side_effect = [deploy_response] + [status_response] * 200
        mock_client_cls.return_value = mock_client
        result = adapter.run(payload)

    assert result.evidence["targets"]["dep-401"]["terminal_status"] == "COMPLETED"
    assert result.evidence["targets"]["dep-402"]["terminal_status"] == "TIMED_OUT"
    assert result.passed is False  # all_must_complete default -> dep-402 drags it down
