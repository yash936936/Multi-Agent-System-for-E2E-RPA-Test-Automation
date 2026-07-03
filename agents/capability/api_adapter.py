import httpx
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

class ApiAdapter:
    """
    Phase 14: Validates REST/GraphQL endpoints.
    Params: method, url, headers, json
    Expected: status (int), json (dict)
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
            return CapabilityCheckResult(
                capability=self.capability_type, passed=False, confidence=1.0,
                evidence={"error": "Missing 'url' in params"}, escalate=False
            )
            
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.request(method, url, headers=headers, json=json_data)
                
            passed = response.status_code == expected_status
            evidence = {
                "status_code": response.status_code,
                "response_time_ms": response.elapsed.total_seconds() * 1000,
            }
            
            if expected_json and passed:
                try:
                    resp_json = response.json()
                    match = all(resp_json.get(k) == v for k, v in expected_json.items())
                    if not match:
                        passed = False
                        evidence["json_mismatch"] = True
                        evidence["expected_json"] = expected_json
                        evidence["actual_json"] = resp_json
                except Exception as e:
                    passed = False
                    evidence["json_parse_error"] = str(e)
                    
            return CapabilityCheckResult(
                capability=self.capability_type, passed=passed, 
                confidence=1.0 if passed else 0.0, evidence=evidence, escalate=False
            )
        except Exception as e:
            return CapabilityCheckResult(
                capability=self.capability_type, passed=False, confidence=0.0,
                evidence={"exception": str(e)}, escalate=False
            )