import httpx
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

class ApiAdapter:
    """
    Phase 18: Validates REST/GraphQL endpoints with Cross-Modal Healing support.
    """
    capability_type: CapabilityType = CapabilityType.API

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        params = payload.params
        expected = payload.expected or {}
        
        method = params.get("method", "GET").upper()
        url = params.get("url")
        headers = params.get("headers", {})
        json_data = params.get("json")
        
        expected_status = expected.get("status", 200)
        expected_json = expected.get("json")
        
        if not url:
            return self._fail("Missing 'url' in params")
            
        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.request(method, url, headers=headers, json=json_data)
                
            passed = response.status_code == expected_status
            evidence = {
                "status_code": response.status_code,
                "response_time_ms": response.elapsed.total_seconds() * 1000,
            }
            
            if expected_json and passed:
                try:
                    resp_json = response.json()
                    
                    # Debug Fix: Ensure response is a dict before attempting key matching
                    if not isinstance(resp_json, dict):
                        passed = False
                        evidence["error"] = f"Expected JSON dict, got {type(resp_json).__name__}"
                    else:
                        match = all(resp_json.get(k) == v for k, v in expected_json.items())
                        if not match:
                            passed = False
                            evidence["json_mismatch"] = True
                            
                            # Generate structured hints for the Cross-Modal Diagnoser
                            evidence["healing_hints"] = {
                                "expected_keys": list(expected_json.keys()),
                                "actual_keys": list(resp_json.keys()),
                                "actual_payload_sample": {k: resp_json.get(k) for k in list(resp_json.keys())[:5]}
                            }
                except ValueError:
                    passed = False
                    evidence["json_parse_error"] = "Response is not valid JSON"
                    
            return CapabilityCheckResult(
                capability=self.capability_type, passed=passed, 
                confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False
            )
        except Exception as e:
            return self._fail(f"HTTP execution error: {str(e)}")

    def _fail(self, msg):
        return CapabilityCheckResult(
            capability=self.capability_type, passed=False, confidence=1.0,
            evidence={"error": msg}, escalate=False
        )