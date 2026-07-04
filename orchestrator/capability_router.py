"""
Capability router — orchestrator/capability_router.py

Resolved by the kernel via config/tool_registry.yaml:
    Capability.check -> orchestrator.capability_router.check_capability

This is the single kernel-facing entrypoint for every CapabilityAdapter.
Keeping ONE tool-registry entry (rather than one per adapter type) means
Phase 14-16 don't touch config/tool_registry.yaml at all when they add
api_adapter/db_adapter/email_adapter/etc. -- they only add a
`registry.register(...)` call in capability_adapter.default_registry().

The registry is built lazily and cached at module scope: tests that only
need FakeAdapter shouldn't pay for real adapters' import costs once those
exist in Phase 14+, and this mirrors RunEngine's own "load once, reuse
across runs" treatment of ToolRegistry.
"""
from __future__ import annotations

from orchestrator.capability_adapter import CapabilityAdapterRegistry, default_registry
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult

_registry: CapabilityAdapterRegistry | None = None


def _get_registry() -> CapabilityAdapterRegistry:
    global _registry
    if _registry is None:
        _registry = default_registry()
    return _registry


def route_capability(payload: CapabilityCheckInput) -> CapabilityCheckResult:
    if payload.capability is None:
        # A genuine spec-authoring error, not a runtime adapter failure --
        # let the kernel's existing "tool execution error" handling in
        # OrchestratorKernel.call_tool surface it (it already wraps
        # entrypoint exceptions into a failed ToolResponse + trace record),
        # rather than inventing a CapabilityCheckResult with no real
        # capability to report.
        raise ValueError(
            "CapabilityCheckInput.capability is required to route a CAPABILITY_CHECK step"
        )

    adapter = _get_registry().get(payload.capability)
    return adapter.run(payload)


# Backward-compatible alias: earlier code/tests referred to this function
# as `check_capability` before it was renamed to `route_capability`.
check_capability = route_capability
