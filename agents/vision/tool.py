"""
Vision tool registration.

Resolved by the kernel via config/tool_registry.yaml:
    Vision.execute_step -> agents.vision.tool.execute_step
"""
from __future__ import annotations

from agents.vision.executor import execute_step as _execute_step
from orchestrator.schemas import VisionActionResult, VisionStepInput


def execute_step(payload: VisionStepInput) -> VisionActionResult:
    return _execute_step(payload)
