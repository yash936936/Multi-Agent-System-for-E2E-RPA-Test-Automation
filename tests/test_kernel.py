from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from orchestrator.kernel import OrchestratorKernel, RegisteredTool, ToolNotFoundError, ToolRegistry
from orchestrator.schemas import DataRequirements, SyntheticDataRecord, ToolCall


def fake_data_synth(args: DataRequirements) -> SyntheticDataRecord:
    return SyntheticDataRecord(test_id=args.test_id, values={f: f"synthetic_{f}" for f in args.fields})


def failing_tool(args: DataRequirements) -> SyntheticDataRecord:
    raise RuntimeError("boom")


@pytest.fixture()
def registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        RegisteredTool(
            name="DataSynth.generate",
            entrypoint=fake_data_synth,
            input_schema=DataRequirements,
            output_schema=SyntheticDataRecord,
        )
    )
    reg.register(
        RegisteredTool(
            name="DataSynth.failing",
            entrypoint=failing_tool,
            input_schema=DataRequirements,
            output_schema=SyntheticDataRecord,
        )
    )
    return reg


def test_kernel_dispatches_and_validates_output(registry: ToolRegistry, monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        from config.settings import settings as global_settings

        monkeypatch.setattr(global_settings, "project_root", Path(tmp))
        kernel = OrchestratorKernel(registry, run_id=str(uuid.uuid4())[:8])
        call = ToolCall(name="DataSynth.generate", arguments={"fields": ["username", "password"], "test_id": "TC-1"})
        response = kernel.call_tool(call)

        assert response.ok is True
        assert response.result["values"]["username"] == "synthetic_username"


def test_kernel_rejects_invalid_input(registry: ToolRegistry, monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        from config.settings import settings as global_settings

        monkeypatch.setattr(global_settings, "project_root", Path(tmp))
        kernel = OrchestratorKernel(registry, run_id="run1")
        call = ToolCall(name="DataSynth.generate", arguments={"not_a_valid_field": 123})
        response = kernel.call_tool(call)
        assert response.ok is False
        assert "input validation failed" in response.error


def test_kernel_catches_tool_exceptions(registry: ToolRegistry, monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        from config.settings import settings as global_settings

        monkeypatch.setattr(global_settings, "project_root", Path(tmp))
        kernel = OrchestratorKernel(registry, run_id="run2")
        call = ToolCall(name="DataSynth.failing", arguments={"fields": ["x"]})
        response = kernel.call_tool(call)
        assert response.ok is False
        assert "tool execution error" in response.error


def test_kernel_unknown_tool_raises(registry: ToolRegistry):
    kernel = OrchestratorKernel(registry, run_id="run3")
    with pytest.raises(ToolNotFoundError):
        kernel.registry.get("Nonexistent.tool")


def test_kernel_writes_audit_trace(registry: ToolRegistry, monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        from config.settings import settings as global_settings

        monkeypatch.setattr(global_settings, "project_root", Path(tmp))
        run_id = "run_trace_test"
        kernel = OrchestratorKernel(registry, run_id=run_id)
        kernel.call_tool(ToolCall(name="DataSynth.generate", arguments={"fields": ["a"]}))
        kernel.call_tool(ToolCall(name="DataSynth.generate", arguments={"fields": ["b"]}))

        trace = kernel.read_trace()
        assert len(trace) == 2
        assert trace[0]["tool_call"]["name"] == "DataSynth.generate"
        assert "duration_ms" in trace[0]
