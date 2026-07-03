import imaplib
import smtplib
import email
from email.message import EmailMessage
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

class EmailAdapter:
    """
    Phase 14: Validates email automation.
    Params: action ('send' or 'poll'), credentials, server details
    Expected (for poll): subject, body_contains
    """
    capability_type: CapabilityType = CapabilityType.EMAIL

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params
        expected = payload.expected or {}
        action = params.get("action", "poll")
        
        if action == "send":
            return self._send_email(params)
        elif action == "poll":
            return self._poll_email(params, expected)
        else:
            return CapabilityCheckResult(
                capability=self.capability_type, passed=False, confidence=1.0,
                evidence={"error": f"Unknown action: {action}"}, escalate=False
            )
            
    def _send_email(self, params):
        smtp_server = params.get("smtp_server")
        smtp_port = params.get("smtp_port", 587)
        username = params.get("username")
        password = params.get("password")
        to = params.get("to")
        subject = params.get("subject", "")
        body = params.get("body", "")
        
        if not all([smtp_server, username, password, to]):
            return CapabilityCheckResult(
                capability=self.capability_type, passed=False, confidence=1.0,
                evidence={"error": "Missing SMTP credentials or recipient"}, escalate=False
            )
        try:
            msg = EmailMessage()
            msg.set_content(body)
            msg["Subject"] = subject
            msg["From"] = username
            msg["To"] = to
            
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(username, password)
                server.send_message(msg)
                
            return CapabilityCheckResult(
                capability=self.capability_type, passed=True, confidence=1.0,
                evidence={"action": "send", "to": to}, escalate=False
            )
        except Exception as e:
            return CapabilityCheckResult(
                capability=self.capability_type, passed=False, confidence=0.0,
                evidence={"exception": str(e)}, escalate=False
            )
            
    def _poll_email(self, params, expected):
        imap_server = params.get("imap_server")
        imap_port = params.get("imap_port", 993)
        username = params.get("username")
        password = params.get("password")
        expected_subject = expected.get("subject")
        expected_body_contains = expected.get("body_contains")
        
        if not all([imap_server, username, password]):
            return CapabilityCheckResult(
                capability=self.capability_type, passed=False, confidence=1.0,
                evidence={"error": "Missing IMAP credentials"}, escalate=False
            )
        try:
            mail = imaplib.IMAP4_SSL(imap_server, imap_port)
            mail.login(username, password)
            mail.select("inbox")
            
            status, messages = mail.search(None, "ALL")
            if status != "OK": raise Exception("Failed to search emails")
                
            passed = False
            evidence = {"action": "poll", "checked_emails": 0}
            
            # messages[0] is a space-separated byte string of email IDs
            email_ids = messages[0].split()
            
            for num in reversed(email_ids):
                evidence["checked_emails"] += 1
                status, msg_data = mail.fetch(num, "(RFC822)")
                if status != "OK": continue
                    
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                
                if expected_subject and expected_subject not in msg.get("Subject", ""):
                    continue
                    
                if expected_body_contains:
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                payload = part.get_payload(decode=True)
                                if payload: body += payload.decode("utf-8", errors="ignore")
                    else:
                        payload = msg.get_payload(decode=True)
                        if payload: body = payload.decode("utf-8", errors="ignore")
                    if expected_body_contains not in body: continue
                    
                passed = True
                break
                        
                if evidence["checked_emails"] >= 20: break # Limit search for performance
                    
            mail.close()
            mail.logout()
            
            return CapabilityCheckResult(
                capability=self.capability_type, passed=passed, 
                confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False
            )
        except Exception as e:
            return CapabilityCheckResult(
                capability=self.capability_type, passed=False, confidence=0.0,
                evidence={"exception": str(e)}, escalate=False
            )