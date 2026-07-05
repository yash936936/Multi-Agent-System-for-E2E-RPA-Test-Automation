import re
from orchestrator.schemas import TestStep, CapabilityCheckResult, CapabilityType

class CrossModalDiagnoser:
    """
    Phase 18: Diagnoses and heals non-UI (backend) test failures.
    Uses lightweight heuristics first, falling back to the local LLM if configured.
    """
    
    def diagnose(self, step: TestStep, result: CapabilityCheckResult) -> TestStep | None:
        """Attempts to heal a failed capability check. Returns a patched TestStep or None."""
        hints = result.evidence.get("healing_hints", {})
        if not hints:
            return None # No hints means we can't heuristically heal it
            
        if step.capability_type == CapabilityType.API:
            return self._heal_api_drift(step, hints)
        elif step.capability_type == CapabilityType.DATABASE:
            return self._heal_db_drift(step, hints)
            
        return None

    def _heal_api_drift(self, step: TestStep, hints: dict) -> TestStep | None:
        """Heals API JSON schema drift (e.g., snake_case to camelCase)."""
        expected_keys = hints.get("expected_keys", [])
        actual_keys = hints.get("actual_keys", [])
        
        if not expected_keys or not actual_keys:
            return None
            
        # Heuristic: Check for simple casing shifts (snake_case -> camelCase)
        key_mapping = {}
        for exp_key in expected_keys:
            # Convert snake_case to camelCase
            camel_key = re.sub(r'_([a-z])', lambda m: m.group(1).upper(), exp_key)
            if camel_key in actual_keys and camel_key != exp_key:
                key_mapping[exp_key] = camel_key
                
        if key_mapping:
            # Apply the patch to the step's expected payload
            patched_expected = dict(step.expected)
            if "json" in patched_expected:
                new_json = {}
                for k, v in patched_expected["json"].items():
                    new_key = key_mapping.get(k, k)
                    new_json[new_key] = v
                patched_expected["json"] = new_json
                
            # Return a cloned step with patched expectations
            healed_step = step.model_copy(update={"expected": patched_expected})
            return healed_step
            
        return None # Fallback to LLM or escalate

    def _heal_db_drift(self, step: TestStep, hints: dict) -> TestStep | None:
        """
        Heals DB schema drift (e.g., column renamed).

        Unlike _heal_api_drift, db_adapter.py's healing_hints only ever
        carries `query_failed` and `error_type` (see agents/capability/
        db_adapter.py) -- there's no list of actual/available columns to
        diff against, so even when we can pattern-match the missing
        column out of the exception text, there is nothing to safely
        rename it *to* without querying information_schema (out of scope
        for a heuristic diagnoser). We still detect the pattern so this
        stays easy to extend once that lookup exists, but today it can
        only confirm "this looks like a column-drift error" and escalate
        rather than fabricate a guess.
        """
        # Heuristic: Look for standard "column does not exist" errors
        # e.g., PostgreSQL: "column users.user_name does not exist"
        match = re.search(r'column\s+([a-zA-Z0-9_\.]+)\s+does not exist', str(hints.get("exception", "")), re.IGNORECASE)
        if match:
            # Confirmed a column-drift error, but with no candidate
            # replacement name available, escalate to the LLM/human
            # rather than guess.
            return None

        return None  # DB structural changes are highly contextual; escalate to human/LLM