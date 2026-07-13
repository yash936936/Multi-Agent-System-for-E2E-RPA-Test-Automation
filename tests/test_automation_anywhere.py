from unittest.mock import patch, MagicMock

from orchestrator.schemas import CapabilityCheckInput, CapabilityType
from orchestrator.capability_adapter import default_registry
from agents.capability.automation_anywhere_adapter import AutomationAnywhereAdapter
from agents.capability.playwright_validator import PlaywrightValidator


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
