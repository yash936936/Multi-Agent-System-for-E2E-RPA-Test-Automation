"""
Planner tool registration.

The kernel (orchestrator/kernel.py) resolves tools by importing this
module and calling `getattr(module, entrypoint)` per config/tool_registry.yaml:

    Planner.generate_spec -> agents.planner.tool.generate_spec
    Planner.diagnose      -> agents.planner.tool.diagnose

Both functions take exactly one validated pydantic input object and return
exactly one pydantic output object, matching the kernel's dispatch contract.
"""
from __future__ import annotations

from agents.planner.diagnoser import diagnose as _diagnose
from agents.planner.spec_generator import generate_spec as _generate_spec
from orchestrator.schemas import DiagnosisInput, RequirementInput, SkillRecord, TestSpec


def generate_spec(payload: RequirementInput) -> TestSpec:
    return _generate_spec(payload)


def diagnose(payload: DiagnosisInput) -> SkillRecord:
    return _diagnose(payload)
