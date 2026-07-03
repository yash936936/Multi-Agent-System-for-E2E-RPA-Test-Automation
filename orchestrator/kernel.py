"""
Orchestrator kernel — the tool-calling dispatch layer.

This is the in-repo substitute for the "Hermes Agent API" referenced in
TRD.md (see decisions.md D-006 for why). It implements the exact same
external contract described in TRD.md §5.1:

    <tools>[...]</tools>
    <tool_call>{"name": ..., "arguments": {...}}</tool_call>
    <tool_response>{...}</tool_response>

Tools are declared in config/tool_registry.yaml (name -> module.entrypoint +
schemas). The kernel:
  1. loads the YAML at construction time
  2. dynamically imports each tool's module and resolves its entrypoint
  3. validates arguments against the declared input_schema
  4. calls the entrypoint
  5. validates the return value against the declared output_schema
  6. writes a verbatim JSONL audit record of every call (TRD §7 NFR)

Agents (Planner/Vision/DataSynth) don't need to know this class exists —
they just register a plain function. This keeps the tool contract stable
even if the dispatch backend changes later.
"""
from __future__ import annotations

import importlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import BaseModel, ValidationError

from config.settings import settings
from orchestrator import schemas as schema_module
from orchestrator.schemas import ToolCall, ToolResponse


class ToolNotFoundError(Exception):
    pass


class ToolValidationError(Exception):
    pass


@dataclass
class RegisteredTool:
    name: str
    entrypoint: Callable[..., Any]
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    description: str = ""


class ToolRegistry:
    """Loads config/tool_registry.yaml and resolves each declared tool."""

    def __init__(self, registry_path: Path | None = None) -> None:
        # Deliberately NOT settings.project_root: that setting is meant for
        # runtime output dirs (reports/, runtime/, memory/) and tests
        # monkeypatch it to a tmp dir to isolate those writes. This file is
        # a static repo asset that must always resolve to the real repo
        # layout regardless of that monkeypatching.
        self.registry_path = registry_path or (Path(__file__).resolve().parent.parent / "config" / "tool_registry.yaml")
        self._tools: dict[str, RegisteredTool] = {}

    def load(self) -> "ToolRegistry":
        raw = yaml.safe_load(self.registry_path.read_text(encoding="utf-8"))
        for entry in raw["tools"]:
            module = importlib.import_module(entry["module"])
            entrypoint = getattr(module, entry["entrypoint"])
            input_schema = getattr(schema_module, entry["input_schema"])
            output_schema = getattr(schema_module, entry["output_schema"])
            self._tools[entry["name"]] = RegisteredTool(
                name=entry["name"],
                entrypoint=entrypoint,
                input_schema=input_schema,
                output_schema=output_schema,
                description=entry.get("description", ""),
            )
        return self

    def register(self, tool: RegisteredTool) -> None:
        """Manual registration path — used heavily in tests to avoid importing real agents."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> RegisteredTool:
        if name not in self._tools:
            raise ToolNotFoundError(f"No tool registered under name '{name}'")
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools.keys())


class OrchestratorKernel:
    """
    Dispatches ToolCalls against a ToolRegistry, with schema validation and
    a verbatim JSONL audit trace per run — matching TRD.md §7's
    recoverability / auditability non-functional requirements.
    """

    def __init__(self, registry: ToolRegistry, run_id: str) -> None:
        self.registry = registry
        self.run_id = run_id
        self._trace_path = self._trace_file_for(run_id)
        self._trace_path.parent.mkdir(parents=True, exist_ok=True)

    def _trace_file_for(self, run_id: str) -> Path:
        return settings.reports_dir / f"run_{run_id}" / "trace.jsonl"

    def call_tool(self, call: ToolCall) -> ToolResponse:
        started = time.time()
        tool = self.registry.get(call.name)

        try:
            validated_args = tool.input_schema.model_validate(call.arguments)
        except ValidationError as e:
            response = ToolResponse(name=call.name, result={}, ok=False, error=f"input validation failed: {e}")
            self._append_trace(call, response, started)
            return response

        try:
            raw_result = tool.entrypoint(validated_args)
        except Exception as e:  # noqa: BLE001 - tool failures must not crash the kernel
            response = ToolResponse(name=call.name, result={}, ok=False, error=f"tool execution error: {e}")
            self._append_trace(call, response, started)
            return response

        try:
            if isinstance(raw_result, BaseModel):
                validated_output = tool.output_schema.model_validate(raw_result.model_dump())
            else:
                validated_output = tool.output_schema.model_validate(raw_result)
        except ValidationError as e:
            response = ToolResponse(name=call.name, result={}, ok=False, error=f"output validation failed: {e}")
            self._append_trace(call, response, started)
            return response

        response = ToolResponse(name=call.name, result=validated_output.model_dump(mode="json"), ok=True)
        self._append_trace(call, response, started)
        return response

    def _append_trace(self, call: ToolCall, response: ToolResponse, started_at: float) -> None:
        record = {
            "timestamp": time.time(),
            "duration_ms": round((time.time() - started_at) * 1000, 2),
            "tool_call": call.model_dump(),
            "tool_response": response.model_dump(),
        }
        with self._trace_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def read_trace(self) -> list[dict]:
        if not self._trace_path.exists():
            return []
        return [json.loads(line) for line in self._trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
