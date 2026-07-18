"""
Tests for agents/capability/composio_adapter.py (proposed D-046).

Covers: the settings.enable_composio gate (independent of the router's
general capability_adapters_enabled switch, same two-layer shape
test_db_seed_adapter.py exercises for allow_db_seeding), missing-param
validation, and a successful call against a mocked `composio` package --
the real package is never installed in this test environment (same
constraint as every other external-service adapter's tests in this
codebase; the composio.Composio class is injected via sys.modules rather
than actually pip-installed), so this only proves ComposioAdapter's own
logic (gating, param validation, request shape, result/evidence
construction, audit logging), not Composio's live API behavior.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from agents.capability.composio_adapter import ComposioAdapter
from config.settings import settings
from orchestrator.schemas import CapabilityCheckInput, CapabilityType


@pytest.fixture
def composio_enabled():
    original_enabled = settings.enable_composio
    original_key = settings.composio_api_key
    original_account = settings.composio_connected_account_id
    settings.enable_composio = True
    settings.composio_api_key = "test-composio-key"
    settings.composio_connected_account_id = "ca_test_default"
    yield
    settings.enable_composio = original_enabled
    settings.composio_api_key = original_key
    settings.composio_connected_account_id = original_account


@pytest.fixture
def mock_composio_package():
    """
    Injects a fake `composio` module into sys.modules so
    ComposioAdapter's deferred `from composio import Composio` import
    (module docstring constraint 2) resolves to a controllable mock
    instead of raising ImportError. Removes it afterward so it doesn't
    leak into other tests.
    """
    fake_module = types.ModuleType("composio")
    mock_client_instance = MagicMock()
    mock_client_instance.tools.execute.return_value = {"status": "success", "data": {"updatedRange": "Sheet1!A2:C2"}}
    mock_composio_class = MagicMock(return_value=mock_client_instance)
    fake_module.Composio = mock_composio_class

    original = sys.modules.get("composio")
    sys.modules["composio"] = fake_module
    yield mock_composio_class, mock_client_instance
    if original is not None:
        sys.modules["composio"] = original
    else:
        sys.modules.pop("composio", None)


def _run(params, expected=None):
    adapter = ComposioAdapter()
    return adapter.run(
        CapabilityCheckInput(capability=CapabilityType.COMPOSIO_SHEETS, target="", params=params, expected=expected or {})
    )


def test_disabled_by_default_returns_clean_failure_not_a_crash():
    """settings.enable_composio defaults False -- confirms the actual
    default, not just that the gate exists."""
    assert settings.enable_composio is False
    result = _run({"spreadsheet_id": "sheet123", "values": [["a", "b"]]})
    assert result.passed is False
    assert "enable_composio" in result.evidence["error"]


def test_enabled_but_missing_api_key_fails_cleanly(composio_enabled):
    settings.composio_api_key = None
    result = _run({"spreadsheet_id": "sheet123", "values": [["a", "b"]]})
    assert result.passed is False
    assert "composio_api_key" in result.evidence["error"]


def test_missing_spreadsheet_id_fails(composio_enabled, mock_composio_package):
    result = _run({"values": [["a", "b"]]})
    assert result.passed is False
    assert "spreadsheet_id" in result.evidence["error"]


def test_missing_values_fails(composio_enabled, mock_composio_package):
    result = _run({"spreadsheet_id": "sheet123"})
    assert result.passed is False
    assert "values" in result.evidence["error"]


def test_missing_connected_account_id_fails_when_no_settings_default(composio_enabled, mock_composio_package):
    settings.composio_connected_account_id = None
    result = _run({"spreadsheet_id": "sheet123", "values": [["a", "b"]]})
    assert result.passed is False
    assert "connected_account_id" in result.evidence["error"]


def test_successful_append_uses_settings_default_connected_account(composio_enabled, mock_composio_package):
    mock_class, mock_client = mock_composio_package
    result = _run({"spreadsheet_id": "sheet123", "values": [["Run 42", "PASS", "2026-07-19"]], "range": "Results!A1"})

    assert result.passed is True
    assert result.evidence["spreadsheet_id"] == "sheet123"
    assert result.evidence["row_count"] == 1

    mock_class.assert_called_once_with(api_key="test-composio-key")
    mock_client.tools.execute.assert_called_once()
    call_args = mock_client.tools.execute.call_args
    assert call_args.kwargs["connected_account_id"] == "ca_test_default"
    assert call_args.kwargs["arguments"]["spreadsheet_id"] == "sheet123"
    assert call_args.kwargs["arguments"]["values"] == [["Run 42", "PASS", "2026-07-19"]]
    assert call_args.kwargs["arguments"]["range"] == "Results!A1"


def test_per_call_connected_account_id_overrides_settings_default(composio_enabled, mock_composio_package):
    mock_class, mock_client = mock_composio_package
    result = _run({"spreadsheet_id": "sheet123", "values": [["x"]], "connected_account_id": "ca_override"})

    assert result.passed is True
    call_args = mock_client.tools.execute.call_args
    assert call_args.kwargs["connected_account_id"] == "ca_override"


def test_custom_tool_slug_is_honored_not_hardcoded(composio_enabled, mock_composio_package):
    """Design constraint 3: caller can override the tool slug rather than
    the adapter guessing/hardcoding Composio's exact registry naming."""
    mock_class, mock_client = mock_composio_package
    _run({"spreadsheet_id": "sheet123", "values": [["x"]], "tool_slug": "GOOGLESHEETS_APPEND_VALUES"})

    call_args = mock_client.tools.execute.call_args
    assert call_args.args[0] == "GOOGLESHEETS_APPEND_VALUES"


def test_composio_execution_error_is_caught_and_reported(composio_enabled, mock_composio_package):
    mock_class, mock_client = mock_composio_package
    mock_client.tools.execute.side_effect = RuntimeError("connection expired")

    result = _run({"spreadsheet_id": "sheet123", "values": [["x"]]})
    assert result.passed is False
    assert "connection expired" in result.evidence["error"]


def test_missing_composio_package_reports_clean_failure_not_a_crash(composio_enabled):
    """If settings.enable_composio is True but the composio package
    genuinely isn't installed, this must fail cleanly (ImportError caught),
    not propagate a raw traceback -- confirms the deferred-import path's
    own error handling, not just that the import is deferred."""
    sys.modules.pop("composio", None)  # ensure it's genuinely absent for this one test
    result = _run({"spreadsheet_id": "sheet123", "values": [["x"]]})
    assert result.passed is False
    assert "composio" in result.evidence["error"].lower()


def test_successful_call_is_audit_logged(composio_enabled, mock_composio_package):
    from orchestrator.audit_logger import audit_logger

    with pytest.MonkeyPatch.context() as mp:
        logged = []
        mp.setattr(audit_logger, "log", lambda **kwargs: logged.append(kwargs))
        _run({"spreadsheet_id": "sheet123", "values": [["x"]]})

    assert len(logged) == 1
    assert logged[0]["action"] == "COMPOSIO_SHEETS_APPEND"
    assert logged[0]["resource"] == "sheet123"
