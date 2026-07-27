"""Merged test file: test_automation_anywhere.py
Consolidated from: test_automation_anywhere.py, test_phase_n_automation_anywhere.py, test_phase_p_automation_anywhere.py, test_bot_validation_cross_check.py
All original test functions preserved 1:1. Colliding fixture/helper names
renamed with a source-file suffix to avoid silent shadowing across sections.
"""
from __future__ import annotations
from unittest.mock import patch, MagicMock
from orchestrator.schemas import CapabilityCheckInput, CapabilityType
from orchestrator.capability_adapter import default_registry
from agents.capability.automation_anywhere_adapter import AutomationAnywhereAdapter
from agents.capability.playwright_validator import PlaywrightValidator
import tempfile
from pathlib import Path
import pytest
from agents.capability.db_adapter import DbAdapter
from orchestrator.memory import RunMemoryStore
from orchestrator.run_engine import RunEngine
from orchestrator.schemas import (
    ActionType,
    CapabilityCheckInput,
    CapabilityCheckResult,
    CapabilityType,
    RunStatus,
    TestSpec,
    TestStep,
)
from orchestrator.skill_store import SkillStore


# ============================================================================
# ---- from test_automation_anywhere.py ----
# ============================================================================
# --- Registry wiring ---

def test_registry_includes_phase21_adapters():
    registry = default_registry()
    assert CapabilityType.AUTOMATION_ANYWHERE in registry.registered_types()
    assert CapabilityType.WEB_VALIDATION in registry.registered_types()
    assert isinstance(registry.get(CapabilityType.AUTOMATION_ANYWHERE), AutomationAnywhereAdapter)
    assert isinstance(registry.get(CapabilityType.WEB_VALIDATION), PlaywrightValidator)


# --- Automation Anywhere adapter: REST mode ---

def test_aa_adapter_rest_mode_completed():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="bot-12345",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.my.automationanywhere.digital",
            "bot_id": "12345",
            "run_as_user_id": "67890",
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
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.side_effect = [deploy_response, status_response]
        mock_client_cls.return_value = mock_client

        result = adapter.run(payload)

    assert result.passed is True
    assert result.evidence["terminal_status"] == "COMPLETED"
    assert result.evidence["deployment_id"] == "dep-1"


def test_aa_adapter_rest_mode_failed_status():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="bot-12345",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.my.automationanywhere.digital",
            "bot_id": "12345",
            "poll_interval_seconds": 0,
            "timeout_seconds": 5,
        },
        expected={"terminal_status": "COMPLETED"},
    )

    deploy_response = MagicMock(status_code=200, content=b'{"deploymentId": "dep-2"}')
    deploy_response.json.return_value = {"deploymentId": "dep-2"}

    status_response = MagicMock(status_code=200)
    status_response.json.return_value = {"list": [{"deploymentId": "dep-2", "status": "FAILED"}]}

    with patch("agents.capability.automation_anywhere_adapter.httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.post.side_effect = [deploy_response, status_response]
        mock_client_cls.return_value = mock_client

        result = adapter.run(payload)

    assert result.passed is False
    assert result.escalate is True
    assert result.evidence["terminal_status"] == "FAILED"


def test_aa_adapter_rest_mode_missing_params():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="bot-12345",
        params={"mode": "rest"},
        expected={},
    )
    result = adapter.run(payload)
    assert result.passed is False
    assert "control_room_url" in result.evidence["error"]


# --- Automation Anywhere adapter: CLI mode ---

def test_aa_adapter_cli_mode_success():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="local-bot",
        params={"mode": "cli", "command": ["echo", "ok"], "timeout_seconds": 5},
        expected={"exit_code": 0},
    )

    fake_completed = MagicMock(returncode=0, stdout="ok\n", stderr="")
    with patch("agents.capability.automation_anywhere_adapter.subprocess.run", return_value=fake_completed):
        result = adapter.run(payload)

    assert result.passed is True
    assert result.evidence["exit_code"] == 0


def test_aa_adapter_cli_mode_nonzero_exit():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="local-bot",
        params={"mode": "cli", "command": "false", "timeout_seconds": 5},
        expected={"exit_code": 0},
    )

    fake_completed = MagicMock(returncode=1, stdout="", stderr="boom")
    with patch("agents.capability.automation_anywhere_adapter.subprocess.run", return_value=fake_completed):
        result = adapter.run(payload)

    assert result.passed is False
    assert result.escalate is True
    assert result.evidence["exit_code"] == 1


def test_aa_adapter_cli_mode_missing_command():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="local-bot",
        params={"mode": "cli"},
        expected={},
    )
    result = adapter.run(payload)
    assert result.passed is False
    assert "command" in result.evidence["error"]


def test_aa_adapter_unknown_mode():
    adapter = AutomationAnywhereAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="x", params={"mode": "carrier_pigeon"}, expected={},
    )
    result = adapter.run(payload)
    assert result.passed is False
    assert "Unknown mode" in result.evidence["error"]


# --- Playwright validator ---

def test_playwright_validator_missing_url():
    validator = PlaywrightValidator()
    payload = CapabilityCheckInput(
        capability=CapabilityType.WEB_VALIDATION, target="", params={}, expected={},
    )
    result = validator.run(payload)
    assert result.passed is False
    assert "url" in result.evidence["error"]


def test_playwright_validator_not_installed():
    validator = PlaywrightValidator()
    payload = CapabilityCheckInput(
        capability=CapabilityType.WEB_VALIDATION,
        target="https://example.com",
        params={}, expected={"contains_text": "hello"},
    )
    with patch.dict("sys.modules", {"playwright.sync_api": None}):
        result = validator.run(payload)
    assert result.passed is False
    assert "playwright" in result.evidence["error"].lower()


def test_playwright_validator_contains_text_pass():
    validator = PlaywrightValidator()
    payload = CapabilityCheckInput(
        capability=CapabilityType.WEB_VALIDATION,
        target="https://example.com/order/42",
        params={}, expected={"contains_text": "Order Complete"},
    )

    mock_page = MagicMock()
    mock_page.url = "https://example.com/order/42"
    mock_page.content.return_value = "<html>Order Complete</html>"

    mock_browser = MagicMock()
    mock_browser.new_page.return_value = mock_page

    mock_chromium = MagicMock()
    mock_chromium.launch.return_value = mock_browser

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium = mock_chromium

    mock_sync_playwright_cm = MagicMock()
    mock_sync_playwright_cm.__enter__.return_value = mock_pw_instance

    fake_module = MagicMock()
    fake_module.sync_playwright.return_value = mock_sync_playwright_cm

    with patch.dict("sys.modules", {"playwright.sync_api": fake_module}):
        result = validator.run(payload)

    assert result.passed is True
    assert result.evidence["contains_text_check"]["found"] is True
    mock_browser.close.assert_called_once()


def test_playwright_validator_contains_text_fail():
    validator = PlaywrightValidator()
    payload = CapabilityCheckInput(
        capability=CapabilityType.WEB_VALIDATION,
        target="https://example.com/order/42",
        params={}, expected={"contains_text": "Order Complete"},
    )

    mock_page = MagicMock()
    mock_page.url = "https://example.com/order/42"
    mock_page.content.return_value = "<html>Order Pending</html>"

    mock_browser = MagicMock()
    mock_browser.new_page.return_value = mock_page

    mock_chromium = MagicMock()
    mock_chromium.launch.return_value = mock_browser

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium = mock_chromium

    mock_sync_playwright_cm = MagicMock()
    mock_sync_playwright_cm.__enter__.return_value = mock_pw_instance

    fake_module = MagicMock()
    fake_module.sync_playwright.return_value = mock_sync_playwright_cm

    with patch.dict("sys.modules", {"playwright.sync_api": fake_module}):
        result = validator.run(payload)

    assert result.passed is False
    assert result.escalate is True
    assert result.evidence["contains_text_check"]["found"] is False


# --- End-to-end trigger/validate pattern (registry-level, mocked) ---

def test_full_trigger_and_validate_pattern_via_registry():
    """
    Exercises the full diagram from docs/TRD.md §11: trigger the AA bot,
    then independently validate the Web App leg via the Playwright
    validator, both routed through the same CapabilityAdapterRegistry used
    by orchestrator/capability_router.py.
    """
    registry = default_registry()
    aa_adapter = registry.get(CapabilityType.AUTOMATION_ANYWHERE)
    web_validator = registry.get(CapabilityType.WEB_VALIDATION)

    trigger_payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="bot-999",
        params={"mode": "cli", "command": ["echo", "done"], "timeout_seconds": 5},
        expected={"exit_code": 0},
    )
    fake_completed = MagicMock(returncode=0, stdout="done\n", stderr="")
    with patch("agents.capability.automation_anywhere_adapter.subprocess.run", return_value=fake_completed):
        trigger_result = aa_adapter.run(trigger_payload)
    assert trigger_result.passed is True

    # Bot reports success — but per TRD §11.6, that alone must not be
    # sufficient; the web-validation leg is checked independently.
    validate_payload = CapabilityCheckInput(
        capability=CapabilityType.WEB_VALIDATION,
        target="https://example.com/order/999",
        params={}, expected={"contains_text": "Order Complete"},
    )

    mock_page = MagicMock()
    mock_page.url = "https://example.com/order/999"
    mock_page.content.return_value = "<html>Order Complete</html>"
    mock_browser = MagicMock()
    mock_browser.new_page.return_value = mock_page
    mock_chromium = MagicMock()
    mock_chromium.launch.return_value = mock_browser
    mock_pw_instance = MagicMock(chromium=mock_chromium)
    mock_sync_playwright_cm = MagicMock()
    mock_sync_playwright_cm.__enter__.return_value = mock_pw_instance
    fake_module = MagicMock()
    fake_module.sync_playwright.return_value = mock_sync_playwright_cm

    with patch.dict("sys.modules", {"playwright.sync_api": fake_module}):
        validate_result = web_validator.run(validate_payload)

    assert validate_result.passed is True
    run_passed = trigger_result.passed and validate_result.passed
    assert run_passed is True


# --------------------------------------------------------------------------
# Phase E closure (decisions.md D-021): Phase D egress controls must cover
# the Automation Anywhere REST trigger's control_room_url, not just the
# generic "url" param key used by other adapters.
# --------------------------------------------------------------------------

def test_control_room_url_is_covered_by_egress_host_extraction():
    from orchestrator.capability_router import _extract_egress_host

    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="bot-12345",
        params={
            "mode": "rest",
            "control_room_url": "https://tenant.my.automationanywhere.digital",
            "bot_id": "12345",
        },
    )
    assert _extract_egress_host(payload) == "tenant.my.automationanywhere.digital"


def test_control_room_url_respects_allowlist_via_router():
    from config.settings import settings
    from orchestrator.capability_router import route_capability

    orig = settings.allowed_capability_hosts
    try:
        settings.allowed_capability_hosts = ["automationanywhere.digital"]
        result = route_capability(
            CapabilityCheckInput(
                capability=CapabilityType.AUTOMATION_ANYWHERE,
                target="bot-12345",
                params={
                    "mode": "rest",
                    "control_room_url": "https://evil.other-domain.example",
                    "bot_id": "12345",
                },
            )
        )
        assert result.passed is False
        assert result.evidence.get("rejected") is True
    finally:
        settings.allowed_capability_hosts = orig


def test_web_validation_url_is_covered_by_egress_host_extraction():
    from orchestrator.capability_router import _extract_egress_host

    payload = CapabilityCheckInput(
        capability=CapabilityType.WEB_VALIDATION,
        target="",
        params={"url": "https://portal.example.com/order/999"},
    )
    assert _extract_egress_host(payload) == "portal.example.com"


def test_cli_mode_has_no_host_and_is_not_blocked_by_allowlist():
    """CLI mode is a local subprocess invocation, not a network call -- it
    should have no extractable host (fails open against any allowlist),
    but remains fully covered by the Phase D kill switch."""
    from config.settings import settings
    from orchestrator.capability_router import _extract_egress_host, route_capability

    payload = CapabilityCheckInput(
        capability=CapabilityType.AUTOMATION_ANYWHERE,
        target="bot-local",
        params={"mode": "cli", "command": ["true"]},
    )
    assert _extract_egress_host(payload) is None

    orig_enabled = settings.capability_adapters_enabled
    try:
        settings.capability_adapters_enabled = False
        result = route_capability(payload)
        assert result.passed is False
        assert result.evidence.get("rejected") is True
    finally:
        settings.capability_adapters_enabled = orig_enabled

# ============================================================================
# ---- from test_phase_n_automation_anywhere.py ----
# ============================================================================
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

# ============================================================================
# ---- from test_phase_p_automation_anywhere.py ----
# ============================================================================
def _mock_client__phase_p_automation_anywhere(post_side_effect):
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
        mock_client_cls.return_value = _mock_client__phase_p_automation_anywhere([deploy_response, status_response])
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
        mock_client_cls.return_value = _mock_client__phase_p_automation_anywhere([deploy_response, status_response, audit_response])
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
        mock_client_cls.return_value = _mock_client__phase_p_automation_anywhere([deploy_response, status_response, audit_response])
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
        mock_client_cls.return_value = _mock_client__phase_p_automation_anywhere(
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
        mock_client_cls.return_value = _mock_client__phase_p_automation_anywhere(
            [deploy_response, status_response, audit_101, audit_102]
        )
        result = adapter.run(payload)

    assert result.passed is True
    assert "control_room_audit" not in result.evidence  # multi-target: no single top-level key
    assert result.evidence["targets"]["dep-101"]["control_room_audit"]["entries"] == [{"auditId": "a-101"}]
    assert result.evidence["targets"]["dep-102"]["control_room_audit"]["entries"] == [{"auditId": "a-102"}]

# ============================================================================
# ---- from test_bot_validation_cross_check.py ----
# ============================================================================
@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def _engine(tmp_dir: Path) -> RunEngine:
    def provider(run_id: str, step_id: int) -> str:  # not used by capability_check steps
        raise AssertionError("screenshot_provider should not be called for capability_check-only specs")

    return RunEngine(
        screenshot_provider=provider,
        skill_store=SkillStore(db_path=tmp_dir / "skills.db"),
        memory=RunMemoryStore(db_path=tmp_dir / "memory.db"),
    )


def _patch_aa_adapter(monkeypatch, passed: bool):
    def fake_run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        return CapabilityCheckResult(
            capability=CapabilityType.AUTOMATION_ANYWHERE,
            passed=passed,
            confidence=1.0,
            evidence={"terminal_status": "COMPLETED" if passed else "FAILED"},
            escalate=not passed,
        )

    monkeypatch.setattr(AutomationAnywhereAdapter, "run", fake_run)


def _patch_web_validator(monkeypatch, passed: bool):
    def fake_run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        return CapabilityCheckResult(
            capability=CapabilityType.WEB_VALIDATION,
            passed=passed,
            confidence=1.0,
            evidence={"contains_text_check": {"found": passed}},
            escalate=not passed,
        )

    monkeypatch.setattr(PlaywrightValidator, "run", fake_run)


def _patch_db_adapter(monkeypatch, passed: bool):
    def fake_run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        return CapabilityCheckResult(
            capability=CapabilityType.DATABASE,
            passed=passed,
            confidence=1.0,
            evidence={"row_count": 1 if passed else 0},
            escalate=not passed,
        )

    monkeypatch.setattr(DbAdapter, "run", fake_run)


def _trigger_step(step_id: int, group: str) -> TestStep:
    return TestStep(
        step_id=step_id,
        action=ActionType.CAPABILITY_CHECK,
        capability_type=CapabilityType.AUTOMATION_ANYWHERE,
        capability_params={"mode": "rest", "control_room_url": "https://x", "bot_id": "1"},
        target="bot-1",
        expected={"terminal_status": "COMPLETED"},
        bot_validation_group=group,
    )


def _web_validation_step(step_id: int, group: str) -> TestStep:
    return TestStep(
        step_id=step_id,
        action=ActionType.CAPABILITY_CHECK,
        capability_type=CapabilityType.WEB_VALIDATION,
        capability_params={"url": "https://example.com/order/1"},
        target="https://example.com/order/1",
        expected={"contains_text": "Order Complete"},
        bot_validation_group=group,
    )


def _db_validation_step(step_id: int, group: str) -> TestStep:
    return TestStep(
        step_id=step_id,
        action=ActionType.CAPABILITY_CHECK,
        capability_type=CapabilityType.DATABASE,
        capability_params={"connection_string": "sqlite://", "query": "SELECT 1"},
        target="orders",
        expected={"row_count": 1},
        bot_validation_group=group,
    )


def test_bot_success_with_confirming_validation_leg_passes(tmp_dir, monkeypatch):
    """Bot COMPLETED + web validation confirms -> trigger step genuinely passes."""
    _patch_aa_adapter(monkeypatch, passed=True)
    _patch_web_validator(monkeypatch, passed=True)

    engine = _engine(tmp_dir)
    spec = TestSpec(
        test_id="TC-AA-001", requirement_ref="REQ-AA",
        steps=[
            _trigger_step(1, "grp1"),
            _web_validation_step(2, "grp1"),
        ],
    )
    result = engine.run_spec(spec, run_id="aa_pass_run")

    assert result.report.status == RunStatus.PASSED
    assert result.report.escalated_steps == 0


def test_bot_success_without_any_confirming_leg_is_escalated(tmp_dir, monkeypatch):
    """
    Bot reports COMPLETED, but the web-validation leg does NOT confirm --
    per TRD §11.6, the trigger step must be corrected to failed/escalated,
    not left passed just because the bot said so. (The validation leg's
    own failure is also independently escalated on its own merits -- that's
    correct and expected, separate from the trigger-step override.)
    """
    _patch_aa_adapter(monkeypatch, passed=True)
    _patch_web_validator(monkeypatch, passed=False)

    engine = _engine(tmp_dir)
    spec = TestSpec(
        test_id="TC-AA-002", requirement_ref="REQ-AA",
        steps=[
            _trigger_step(1, "grp1"),
            _web_validation_step(2, "grp1"),
        ],
    )
    result = engine.run_spec(spec, run_id="aa_fail_run")

    assert result.report.status == RunStatus.ESCALATED
    # Both the trigger step (cross-check override) and the validation leg
    # (its own genuine failure) end up escalated.
    assert result.report.escalated_steps == 2

    raw_path = Path(result.report.report_paths["raw_json"])
    raw = raw_path.read_text()
    assert "cross_check_failed" in raw


def test_bot_success_with_at_least_one_of_multiple_legs_confirming_passes(tmp_dir, monkeypatch):
    """
    Bot succeeds, web validation leg does NOT confirm, but the database leg
    DOES -- per TRD §11.6 ("at least one... must independently confirm"),
    the trigger step itself must NOT be overridden/downgraded in this case.
    (The web-validation leg still legitimately escalates on its own merits
    -- that's separate from whether the trigger step's cross-check passes.)
    """
    _patch_aa_adapter(monkeypatch, passed=True)
    _patch_web_validator(monkeypatch, passed=False)
    _patch_db_adapter(monkeypatch, passed=True)

    engine = _engine(tmp_dir)
    spec = TestSpec(
        test_id="TC-AA-003", requirement_ref="REQ-AA",
        steps=[
            _trigger_step(1, "grp1"),
            _web_validation_step(2, "grp1"),
            _db_validation_step(3, "grp1"),
        ],
    )
    result = engine.run_spec(spec, run_id="aa_partial_confirm_run")

    # Only the web-validation leg's own failure is escalated -- the trigger
    # step (step_id=1) must NOT have been downgraded, since the db leg
    # independently confirmed the bot's effect.
    assert result.report.escalated_steps == 1

    raw_path = Path(result.report.report_paths["raw_json"])
    raw = raw_path.read_text()
    assert "cross_check_failed" not in raw

    import json
    raw_data = json.loads(raw_path.read_text())
    trigger_result = next(r for r in raw_data["step_results"] if r["step_id"] == 1)
    assert trigger_result["assertion_passed"] is not False
    assert trigger_result["escalate"] is False


def test_bot_failure_is_unaffected_by_cross_check(tmp_dir, monkeypatch):
    """If the bot itself fails, the trigger step is already escalated -- the
    cross-check shouldn't need to (and doesn't) add anything extra."""
    _patch_aa_adapter(monkeypatch, passed=False)
    _patch_web_validator(monkeypatch, passed=True)

    engine = _engine(tmp_dir)
    spec = TestSpec(
        test_id="TC-AA-004", requirement_ref="REQ-AA",
        steps=[
            _trigger_step(1, "grp1"),
            _web_validation_step(2, "grp1"),
        ],
    )
    result = engine.run_spec(spec, run_id="aa_bot_failed_run")

    assert result.report.status == RunStatus.ESCALATED
    assert result.report.escalated_steps == 1


def test_trigger_with_no_bot_validation_group_is_unaffected(tmp_dir, monkeypatch):
    """Steps with no bot_validation_group behave exactly as before -- the
    cross-check must be opt-in, never applied implicitly."""
    _patch_aa_adapter(monkeypatch, passed=True)

    engine = _engine(tmp_dir)
    spec = TestSpec(
        test_id="TC-AA-005", requirement_ref="REQ-AA",
        steps=[
            TestStep(
                step_id=1,
                action=ActionType.CAPABILITY_CHECK,
                capability_type=CapabilityType.AUTOMATION_ANYWHERE,
                capability_params={"mode": "rest", "control_room_url": "https://x", "bot_id": "1"},
                target="bot-1",
                expected={"terminal_status": "COMPLETED"},
                # no bot_validation_group set
            ),
        ],
    )
    result = engine.run_spec(spec, run_id="aa_no_group_run")

    assert result.report.status == RunStatus.PASSED
    assert result.report.escalated_steps == 0


def test_trigger_group_with_no_validation_steps_present_is_escalated(tmp_dir, monkeypatch):
    """A group tag with only a trigger step and no validation legs anywhere
    in the spec still can't be trusted on the bot's word alone."""
    _patch_aa_adapter(monkeypatch, passed=True)

    engine = _engine(tmp_dir)
    spec = TestSpec(
        test_id="TC-AA-006", requirement_ref="REQ-AA",
        steps=[_trigger_step(1, "grp_orphan")],
    )
    result = engine.run_spec(spec, run_id="aa_orphan_group_run")

    assert result.report.status == RunStatus.ESCALATED
    assert result.report.escalated_steps == 1
