import pytest
from unittest.mock import patch, MagicMock
from orchestrator.schemas import CapabilityCheckInput, CapabilityType
from agents.capability.api_adapter import ApiAdapter
from agents.capability.db_adapter import DbAdapter
from agents.capability.email_adapter import EmailAdapter

@pytest.fixture
def api_payload():
    return CapabilityCheckInput(
        capability=CapabilityType.API,
        target="https://api.test.com/1",
        params={"method": "GET", "url": "https://api.test.com/1"},
        expected={"status": 200, "json": {"id": 1}}
    )

@pytest.fixture
def db_payload():
    return CapabilityCheckInput(
        capability=CapabilityType.DATABASE,
        target="sqlite:///:memory:",
        params={"connection_string": "sqlite:///:memory:", "query": "SELECT 1 as id, 'test' as name"},
        expected={"row_count": 1, "values": {"id": 1, "name": "test"}}
    )

@pytest.fixture
def email_payload():
    return CapabilityCheckInput(
        capability=CapabilityType.EMAIL,
        target="imap.test.com",
        params={"action": "poll", "imap_server": "imap.test.com", "username": "u", "password": "p"},
        expected={"subject": "Test"}
    )

# --- API Adapter Tests ---
def test_api_adapter_success(api_payload):
    adapter = ApiAdapter()
    with patch("httpx.Client") as mock_client:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.elapsed.total_seconds.return_value = 0.1
        mock_response.json.return_value = {"id": 1, "name": "Test"}
        mock_client.return_value.__enter__.return_value.request.return_value = mock_response
        
        result = adapter.run(api_payload)
        assert result.passed is True
        assert result.evidence["status_code"] == 200

def test_api_adapter_missing_url():
    adapter = ApiAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.API, target="", params={}, expected={}
    )
    result = adapter.run(payload)
    assert result.passed is False
    assert "Missing 'url'" in result.evidence.get("error", "")

# --- DB Adapter Tests ---
def test_db_adapter_success(db_payload):
    adapter = DbAdapter()
    result = adapter.run(db_payload)
    assert result.passed is True
    assert result.evidence["row_count"] == 1

def test_db_adapter_failure_values():
    adapter = DbAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.DATABASE,
        target="sqlite:///:memory:",
        params={"connection_string": "sqlite:///:memory:", "query": "SELECT 1 as id, 'wrong' as name"},
        expected={"values": {"name": "test"}}
    )
    result = adapter.run(payload)
    assert result.passed is False
    assert "value_mismatch_name" in result.evidence

# --- Email Adapter Tests ---
def test_email_adapter_poll_success(email_payload):
    adapter = EmailAdapter()
    with patch("imaplib.IMAP4_SSL") as mock_imap:
        mock_mail = MagicMock()
        mock_imap.return_value = mock_mail
        mock_mail.login.return_value = ("OK", [b""])
        mock_mail.select.return_value = ("OK", [b"1"])
        mock_mail.search.return_value = ("OK", [b"1"])
        
        raw_email = b"From: sender@test.com\r\nSubject: Test Email\r\n\r\nBody text"
        mock_mail.fetch.return_value = ("OK", [(b"1", raw_email)])
        
        result = adapter.run(email_payload)
        assert result.passed is True

def test_email_adapter_send_success():
    adapter = EmailAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.EMAIL,
        target="smtp.test.com",
        params={"action": "send", "smtp_server": "smtp.test.com", "username": "u", "password": "p", "to": "r@test.com"},
        expected={}
    )
    with patch("smtplib.SMTP") as mock_smtp:
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        result = adapter.run(payload)
        assert result.passed is True