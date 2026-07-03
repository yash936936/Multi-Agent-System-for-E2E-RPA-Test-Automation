"""
Capability adapter contract — orchestrator/capability_adapter.py

Phase 13 foundation. This is the interface every non-visual adapter
(api_adapter, db_adapter, email_adapter in Phase 14; file/excel/pdf in
Phase 15; cloud in Phase 16) implements. Defining it once, now, means those
later phases each write one class instead of each inventing their own
routing/registration shape.

Deliberately minimal: a CapabilityAdapter is anything with a
`capability_type` and a `run(CapabilityCheckInput) -> CapabilityResult`
method. No adapter beyond FakeAdapter (agents/capability/fake_adapter.py)
exists yet -- that's the point of this phase being schema/protocol-only.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from orchestrator.schemas import CapabilityCheckInput, CapabilityResult, CapabilityType


@runtime_checkable
class CapabilityAdapter(Protocol):
    """
    Structural interface (not an ABC) so adapters don't need to import and
    subclass anything from this module -- they just need the right shape.
    Matches the pattern already used for tool entrypoints in
    orchestrator/kernel.py (plain functions, not registered classes).
    """

    capability_type: CapabilityType

    def run(self, payload: CapabilityCheckInput) -> CapabilityResult:
        ...


class CapabilityAdapterNotFoundError(Exception):
    pass


class CapabilityAdapterRegistry:
    """
    In-process registry mapping CapabilityType -> CapabilityAdapter
    instance. Kept separate from orchestrator.kernel.ToolRegistry
    deliberately: the kernel's registry maps *tool names* (Planner.*,
    Vision.*, DataSynth.*, Capability.check) to entrypoints declared in
    config/tool_registry.yaml, one static file. This registry sits one
    layer below the single "Capability.check" kernel tool and maps
    *capability types* to adapter instances -- it will grow by
    registration calls in Phase 14-16 (one per new adapter module),
    not by editing the YAML file each time.
    """

    def __init__(self) -> None:
        self._adapters: dict[CapabilityType, CapabilityAdapter] = {}

    def register(self, adapter: CapabilityAdapter) -> None:
        self._adapters[adapter.capability_type] = adapter

    def get(self, capability_type: CapabilityType) -> CapabilityAdapter:
        if capability_type not in self._adapters:
            raise CapabilityAdapterNotFoundError(
                f"No adapter registered for capability_type '{capability_type.value}'"
            )
        return self._adapters[capability_type]

    def registered_types(self) -> list[CapabilityType]:
        return list(self._adapters.keys())


def default_registry() -> CapabilityAdapterRegistry:
    """
    Builds the registry used by orchestrator/capability_router.py at
    runtime. Phase 13 registers only FakeAdapter; Phase 14-16 each add one
    more `registry.register(...)` line here as their adapter modules land.
    """
    from agents.capability.fake_adapter import FakeAdapter

    registry = CapabilityAdapterRegistry()
    registry.register(FakeAdapter())
    return registry
