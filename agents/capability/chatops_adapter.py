import httpx
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType


class ChatOpsAdapter:
    """
    Phase 16b: Real Teams/Slack incoming-webhook posting with rich
    formatting -- distinct from the generic WorkflowAdapter (a bare
    JSON POST) because Teams and Slack each expect a specific payload
    shape (Adaptive Card vs Block Kit) to render as anything other than
    a raw JSON blob in the channel.

    params:
        platform: "slack" | "teams"
        webhook_url: the incoming webhook URL
        title: card/message title
        message: body text
        color: (teams only) accent color hex, default green
        fields: optional list of {"title": ..., "value": ...} pairs
    """

    capability_type: CapabilityType = CapabilityType.CHAT_OPS

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params
        expected = payload.expected or {}

        platform = params.get("platform", "slack").lower()
        webhook_url = params.get("webhook_url")
        if not webhook_url:
            return self._fail("Missing 'webhook_url'")

        message = params.get("message", "")
        title = params.get("title", "AURA Notification")
        fields = params.get("fields", [])

        try:
            body = self._slack_payload(title, message, fields) if platform == "slack" else self._teams_payload(
                title, message, fields, params.get("color", "1ED760")
            )

            with httpx.Client(timeout=15.0) as client:
                response = client.post(webhook_url, json=body)

            accepted_codes = expected.get("accepted_status_codes", [200, 201, 202, 204])
            passed = response.status_code in accepted_codes
            evidence = {
                "platform": platform, "status_code": response.status_code,
                "response_time_ms": response.elapsed.total_seconds() * 1000,
            }
            return CapabilityCheckResult(
                capability=self.capability_type, passed=passed,
                confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False,
            )
        except Exception as e:
            return self._fail(f"ChatOps post error: {str(e)}")

    @staticmethod
    def _slack_payload(title: str, message: str, fields: list) -> dict:
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": title}},
            {"type": "section", "text": {"type": "mrkdwn", "text": message}},
        ]
        if fields:
            blocks.append({
                "type": "section",
                "fields": [{"type": "mrkdwn", "text": f"*{f.get('title', '')}*\n{f.get('value', '')}"} for f in fields],
            })
        return {"blocks": blocks}

    @staticmethod
    def _teams_payload(title: str, message: str, fields: list, color: str) -> dict:
        facts = [{"name": f.get("title", ""), "value": str(f.get("value", ""))} for f in fields]
        return {
            "@type": "MessageCard",
            "@context": "https://schema.org/extensions",
            "themeColor": color,
            "title": title,
            "text": message,
            "sections": [{"facts": facts}] if facts else [],
        }

    def _fail(self, msg):
        return CapabilityCheckResult(
            capability=self.capability_type, passed=False, confidence=1.0,
            evidence={"error": msg}, escalate=False,
        )
