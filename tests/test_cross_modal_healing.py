import pytest
from orchestrator.schemas import (
    ActionType, CapabilityType, TestStep, CapabilityCheckResult
)
from agents.planner.cross_modal_diagnoser import CrossModalDiagnoser

def test_api_healer_snake_to_camel_case():
    """Proves the heuristic can automatically fix snake_case -> camelCase drift."""
    diagnoser = CrossModalDiagnoser()
    
    # Original step expected snake_case
    original_step = TestStep(
        step_id=1, action=ActionType.CAPABILITY_CHECK, 
        capability_type=CapabilityType.API,
        expected={"json": {"user_id": 123, "first_name": "Yash"}}
    )
    
    # Adapter failed because the API shifted to camelCase
    failed_result = CapabilityCheckResult(
        capability=CapabilityType.API, passed=False, confidence=0.0,
        evidence={
            "json_mismatch": True,
            "healing_hints": {
                "expected_keys": ["user_id", "first_name"],
                "actual_keys": ["userId", "firstName"],
                "actual_payload_sample": {"userId": 123, "firstName": "Yash"}
            }
        }
    )
    
    healed_step = diagnoser.diagnose(original_step, failed_result)
    
    assert healed_step is not None
    assert "userId" in healed_step.expected["json"]
    assert "firstName" in healed_step.expected["json"]
    assert "user_id" not in healed_step.expected["json"]

def test_api_healer_no_drift_returns_none():
    """Proves the healer doesn't mutate steps if the keys match but values differ."""
    diagnoser = CrossModalDiagnoser()
    
    original_step = TestStep(
        step_id=1, action=ActionType.CAPABILITY_CHECK, 
        capability_type=CapabilityType.API,
        expected={"json": {"user_id": 123}}
    )
    
    failed_result = CapabilityCheckResult(
        capability=CapabilityType.API, passed=False, confidence=0.0,
        evidence={
            "json_mismatch": True,
            "healing_hints": {
                "expected_keys": ["user_id"],
                "actual_keys": ["user_id"], # Keys match, values don't
                "actual_payload_sample": {"user_id": 999}
            }
        }
    )
    
    healed_step = diagnoser.diagnose(original_step, failed_result)
    assert healed_step is None # Cannot heal a data mismatch, only a schema drift