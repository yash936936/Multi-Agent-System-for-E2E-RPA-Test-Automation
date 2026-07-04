"""
Phase 13 tests — capability schema foundation.

Covers:
  1. Schema-level contract (TestStep.capability_type validator, CapabilityCheckResult shape)
  2. CapabilityAdapterRegistry (register/get/not-found)
  3. FakeAdapter satisfies the CapabilityAdapter protocol
  4. The kernel can dispatch "Capability.check" end to end with a real trace record
  5. RunEngine routes a CAPABILITY_CHECK step to the adapter path and a
     VISUAL_CLICK step to the existing Vision path, in the same spec/run
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from orchestrator.capability_adapter import (
    CapabilityAdapter,
    CapabilityAdapterNotFoundError,
    CapabilityAdapterRegistry,
)
from orchestrator.capability_router import check_capability
from orchestrator.kernel import OrchestratorKernel, ToolRegistry
from orchestrator.memory import RunMemoryStore
from orchestrator.run_engine import RunEngine
from orchestrator.schemas import (
    ActionType,
    CapabilityCheckInput,
    CapabilityCheckResult,
    CapabilityType,
    TestStep,
    ToolCall,
)
from agents.capability.fake_adapter import FakeAdapter


# --------------------------------------------------------------------------
# Schema-level contract
# --------------------------------------------------------------------------

def test_capability_type_rejected_on_non_capability_check_step():
    with pytest.raises(Exception):
        TestStep(step_id=1, action=ActionType.VISUAL_CLICK, capability_type=CapabilityType.FAKE)


def test_capability_check_step_round_trips():
    step = TestStep(
        step_id=1,
        action=ActionType.CAPABILITY_CHECK,
        capability_type=CapabilityType.FAKE,
        capability_params={"query": "SELECT 1"},
    )
    assert step.capability_type == CapabilityType.FAKE
    assert step.capability_params == {"query": "SELECT 1"}


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

def test_registry_register_and_get():
    registry = CapabilityAdapterRegistry()
    adapter = FakeAdapter()
    registry.register(adapter)
    assert registry.get(CapabilityType.FAKE) is adapter
    assert CapabilityType.FAKE in registry.registered_types()


def test_registry_raises_for_unregistered_type():
    registry = CapabilityAdapterRegistry()
    with pytest.raises(CapabilityAdapterNotFoundError):
        registry.get(CapabilityType.API)


def test_fake_adapter_satisfies_protocol():
    adapter = FakeAdapter()
    assert isinstance(adapter, CapabilityAdapter)


def test_fake_adapter_returns_canned_result_and_echoes_params():
    adapter = FakeAdapter()
    payload = CapabilityCheckInput(
        capability=CapabilityType.FAKE, target="mock_target", params={"foo": "bar"}
    )
    result = adapter.run(payload)
    assert isinstance(result, CapabilityCheckResult)
    assert result.passed is True
    assert result.escalate is False
    assert result.capability == CapabilityType.FAKE
    assert result.evidence["echoed_params"] == {"foo": "bar"}


# --------------------------------------------------------------------------
# Router / kernel dispatch
# --------------------------------------------------------------------------

def test_check_capability_router_dispatches_to_fake_adapter():
    payload = CapabilityCheckInput(capability=CapabilityType.FAKE, target="mock_target", params={})
    result = check_capability(payload)
    assert result.capability == CapabilityType.FAKE
    assert result.passed is True


def test_check_capability_router_raises_without_capability_type():
    with pytest.raises(ValueError):
        CapabilityCheckInput(capability=None, target="mock_target", params={})


def test_kernel_routes_capability_check_tool_with_audit_trace(tmp_path, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)
    registry = ToolRegistry().load()
    kernel = OrchestratorKernel(registry=registry, run_id="capabilitytest")

    call = ToolCall(
        name="Capability.check",
        arguments=CapabilityCheckInput(
            capability=CapabilityType.FAKE, target="mock_target", params={"k": "v"}
        ).model_dump(mode="json"),
    )
    response = kernel.call_tool(call)

    assert response.ok is True
    assert response.result["passed"] is True
    assert response.result["capability"] == "fake"

    trace = kernel.read_trace()
    assert len(trace) == 1
    assert trace[0]["tool_call"]["name"] == "Capability.check"
    assert trace[0]["tool_response"]["ok"] is True


# --------------------------------------------------------------------------
# RunEngine routing: CAPABILITY_CHECK vs VISION_ACTION in the same spec
# --------------------------------------------------------------------------

class _FakePlannerTool:
    """Stand-in Planner.generate_spec that returns a fixed mixed spec, so
    this test doesn't depend on heuristic/local_llm NLP parsing -- it's
    purely testing RunEngine's routing, not spec generation."""

    def __init__(self, spec):
        self.spec = spec

    def __call__(self, payload):
        return self.spec


@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def test_run_engine_routes_capability_and_vision_steps_in_one_spec(tmp_dir, monkeypatch):
    from config.settings import settings
    from orchestrator.schemas import TestSpec
    from target_app.demo_login_app import render_login_screen

    monkeypatch.setattr(settings, "project_root", tmp_dir)

    spec = TestSpec(
        test_id="TC-MIXED-001",
        requirement_ref="REQ-PHASE13",
        steps=[
            TestStep(
                step_id=1,
                action=ActionType.CAPABILITY_CHECK,
                capability_type=CapabilityType.FAKE,
                capability_params={"check": "row_exists"},
            ),
            TestStep(
                step_id=2,
                action=ActionType.VISUAL_CLICK,
                target_description="Login button",
            ),
        ],
    )

    def provider(run_id: str, step_id: int) -> str:
        path = tmp_dir / f"{run_id}_{step_id}.png"
        if not path.exists():
            render_login_screen("initial", path)
        return str(path)

    engine = RunEngine(screenshot_provider=provider, memory=RunMemoryStore())
    engine.registry.register_manual = None  # no-op guard, keep default YAML-loaded registry

    seen_actions: list[str] = []
    engine.on_step_result = lambda step_id, step, result: seen_actions.append(result.action_taken)

    # Bypass Planner NLP entirely -- register a manual tool override for
    # Planner.generate_spec so this test asserts routing, not parsing.
    from orchestrator.kernel import RegisteredTool
    from orchestrator.schemas import RequirementInput

    engine.registry.register(
        RegisteredTool(
            name="Planner.generate_spec",
            entrypoint=lambda payload: spec,
            input_schema=RequirementInput,
            output_schema=TestSpec,
        )
    )

    result = engine.run(requirement_text="irrelevant -- Planner tool is overridden above")

    assert seen_actions[0] == "capability_check"
    assert seen_actions[1] in ("click", "none")  # Vision Core's real action label
    assert result.report.total_steps == 2
