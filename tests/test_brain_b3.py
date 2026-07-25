"""
tests/test_brain_b3.py

Phase B3 (docs/decisions.md D-075) regression tests: the five
previously-unmigrated intent kinds (execute_spec, execute_prompt,
execute_interactive, ui_audit, capability_check) each reach the exact
subsystem call the pre-migration CLI code made, with the CLI-supplied
callback closures forwarded unchanged -- Router never calls live_view
itself anywhere in these paths.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from orchestrator.brain import AuraBrain, Intent


def test_execute_requirement_intent_reaches_engine_run_with_callbacks_forwarded():
    fake_spec = MagicMock(test_id="TC-FAKE-001")
    fake_engine_result = MagicMock(run_id="tc-fake-001", validation_warnings=[])
    captured_callbacks = {}

    def fake_engine_ctor(**kwargs):
        captured_callbacks.update(kwargs)
        engine = MagicMock()
        engine.run.return_value = fake_engine_result
        return engine

    with patch("agents.planner.tool.generate_spec", return_value=fake_spec), \
         patch("agents.planner.page_grounding.snapshot_page_elements", return_value=None), \
         patch("orchestrator.run_engine.RunEngine", side_effect=fake_engine_ctor):
        on_step_start = MagicMock()
        intent = Intent(
            kind="execute_spec",
            params={
                "requirement_text": "Given: navigate to http://example.test",
                "auto_approve": True,
                "screenshot_provider": MagicMock(),
                "on_step_start": on_step_start,
            },
        )
        result = AuraBrain().handle(intent)

    # The exact closure passed in must be the one RunEngine received --
    # not a Router-owned rendering call.
    assert captured_callbacks["on_step_start"] is on_step_start
    assert result.data["spec"] is fake_spec
    assert result.data["result"] is fake_engine_result
    assert result.data["cancelled"] is False


def test_execute_requirement_intent_calls_approve_spec_before_generating_data():
    fake_spec = MagicMock(test_id="TC-FAKE-002")
    approve_calls = []

    def approve_spec(spec):
        approve_calls.append(spec)
        return False  # reject

    with patch("agents.planner.tool.generate_spec", return_value=fake_spec), \
         patch("agents.planner.page_grounding.snapshot_page_elements", return_value=None):
        intent = Intent(
            kind="execute_prompt",
            params={
                "requirement_text": "Check something",
                "auto_approve": False,
                "screenshot_provider": MagicMock(),
                "approve_spec": approve_spec,
            },
        )
        result = AuraBrain().handle(intent)

    assert approve_calls == [fake_spec]
    assert result.data["cancelled"] is True


def test_execute_interactive_intent_reaches_run_spec_with_on_waiting_forwarded():
    fake_result = MagicMock(report=MagicMock(escalated_steps=0), validation_warnings=[])
    captured = {}

    def fake_engine_ctor(**kwargs):
        captured.update(kwargs)
        engine = MagicMock()
        engine.run_spec.return_value = fake_result
        return engine

    on_waiting = MagicMock()
    with patch("orchestrator.run_engine.RunEngine", side_effect=fake_engine_ctor):
        intent = Intent(
            kind="execute_interactive",
            params={"prompt": "click the button", "url": None, "timeout": 0, "screenshot_provider": MagicMock(), "on_waiting": on_waiting},
        )
        result = AuraBrain().handle(intent)

    assert captured["on_waiting_for_human"] is on_waiting
    assert result.data["result"] is fake_result


def test_ui_audit_intent_reaches_run_ui_audit_with_expected_params():
    fake_report = MagicMock(has_nav=True)
    with patch("orchestrator.ui_audit_runner.run_ui_audit", return_value=fake_report) as mock_run_ui_audit, \
         patch("runtime.hooks.browser.open_url"), \
         patch("runtime.hooks.browser.normalize_url", side_effect=lambda u: u), \
         patch("time.sleep"):
        intent = Intent(kind="ui_audit", params={"url": "http://example.test", "max_elements": 5, "link_scope": "footer"})
        result = AuraBrain().handle(intent)

    _, kwargs = mock_run_ui_audit.call_args
    assert kwargs["max_elements"] == 5
    assert kwargs["page_url"] == "http://example.test"
    assert kwargs["link_check_scope"] == "footer"
    assert result.data["report"] is fake_report


def test_capability_check_intent_reaches_kernel_call_tool_with_expected_payload():
    from orchestrator.schemas import ToolResponse

    fake_response = ToolResponse(name="Capability.check", result={"capability": "api", "passed": True, "confidence": 1.0, "evidence": {}}, ok=True)

    with patch("orchestrator.kernel.OrchestratorKernel.call_tool", return_value=fake_response) as mock_call_tool, \
         patch("orchestrator.kernel.ToolRegistry.load", return_value=MagicMock(get=MagicMock(return_value=MagicMock(output_schema=__import__("orchestrator.schemas", fromlist=["CapabilityCheckResult"]).CapabilityCheckResult)))):
        intent = Intent(kind="capability_check", params={"capability_type": "api", "target": "http://example.test/health", "params": {}, "expected": {}})
        result = AuraBrain().handle(intent)

    assert mock_call_tool.called
    call_arg = mock_call_tool.call_args[0][0]
    assert call_arg.name == "Capability.check"
    assert result.data["error"] is None
    assert result.data["result"].passed is True
