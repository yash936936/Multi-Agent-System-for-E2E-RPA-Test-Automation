"""
Tests for agents/capability/email_adapter.py

Covers the poll path's IMAP interaction via a mocked imaplib.IMAP4_SSL,
including a regression test for a bug found during the Phase 5c debug
pass: the "checked_emails >= 20" search-limit was written *after* an
unconditional `break`, making it unreachable dead code. Fixed to check
the limit before processing each message.
"""
from unittest.mock import MagicMock, patch

from agents.capability.email_adapter import EmailAdapter
from orchestrator.schemas import CapabilityCheckInput, CapabilityType


def _make_mail_mock(num_messages: int, matching_subject: str = None):
    """Builds a mock imaplib.IMAP4_SSL whose mailbox has `num_messages`
    messages, none of which match unless `matching_subject` is given and
    happens to be the requested subject (kept simple -- these tests only
    care about the checked_emails counter/loop behavior, not real IMAP
    message parsing)."""
    mail = MagicMock()
    mail.login.return_value = ("OK", [b""])
    mail.select.return_value = ("OK", [b""])

    email_ids = [str(i).encode() for i in range(1, num_messages + 1)]
    mail.search.return_value = ("OK", [b" ".join(email_ids)])

    raw_email = (
        b"Subject: Something else\r\n"
        b"Content-Type: text/plain\r\n\r\nbody text\r\n"
    )

    def fetch_side_effect(num, spec):
        return ("OK", [(b"1 (RFC822 {123}", raw_email)])

    mail.fetch.side_effect = fetch_side_effect
    return mail


def test_poll_stops_after_20_messages_when_nothing_matches():
    """Regression test: the 20-message search cap must actually apply.
    Before the fix, the cap check was unreachable dead code and every
    message in the mailbox would be scanned."""
    mail = _make_mail_mock(num_messages=50)
    with patch("agents.capability.email_adapter.imaplib.IMAP4_SSL", return_value=mail):
        adapter = EmailAdapter()
        payload = CapabilityCheckInput(
            capability=CapabilityType.EMAIL,
            target="inbox",
            params={
                "action": "poll",
                "imap_server": "imap.example.com",
                "username": "user@example.com",
                "password": "secret",
            },
            expected={"subject": "Never Matches This Subject"},
        )
        result = adapter.run(payload)

    assert result.passed is False
    assert result.evidence["checked_emails"] == 20


def test_poll_finds_match_before_hitting_cap():
    """A match found within the first 20 messages should short-circuit
    normally, well before the cap is reached."""
    mail = _make_mail_mock(num_messages=50)
    with patch("agents.capability.email_adapter.imaplib.IMAP4_SSL", return_value=mail):
        adapter = EmailAdapter()
        payload = CapabilityCheckInput(
            capability=CapabilityType.EMAIL,
            target="inbox",
            params={
                "action": "poll",
                "imap_server": "imap.example.com",
                "username": "user@example.com",
                "password": "secret",
            },
            expected={"subject": "Something else"},
        )
        result = adapter.run(payload)

    assert result.passed is True
    assert result.evidence["checked_emails"] == 1
