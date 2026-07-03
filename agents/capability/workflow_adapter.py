import httpx
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

class WorkflowAdapter:
    """
    Phase 16: Triggers external workflows (Fire-and-Forget).
    """
    capability_type: CapabilityType = CapabilityType.WORKFLOW

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params
        expected = payload.expected or {}
        
        url = params.get("url")
        headers = params.get("headers", {})
        json_data = params.get("payload", {})
        method = params.get("method", "POST").upper() # Debug Fix: Allow method override
        accepted_codes = expected.get("accepted_status_codes", [200, 201, 202, 204])
        
        if not url:
            return self._fail("Missing 'url' for workflow trigger")
            
        try:
            with httpx.Client(timeout=15.0) as client:
                # Debug Fix: Use the configurable method
                response = client.request(method, url, headers=headers, json=json_data)
                
            passed = response.status_code in accepted_codes
            evidence = {
                "triggered_url": url,
                "method": method,
                "status_code": response.status_code,
                "response_time_ms": response.elapsed.total_seconds() * 1000
            }
            
            return CapabilityCheckResult(
                capability=self.capability_type, passed=passed, 
                confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False
            )
        except Exception as e:
            return self._fail(f"Workflow trigger error: {str(e)}")

    def _fail(self, msg):
        return CapabilityCheckResult(
            capability=self.capability_type, passed=False, confidence=1.0,
            evidence={"error": msg}, escalate=False
        )