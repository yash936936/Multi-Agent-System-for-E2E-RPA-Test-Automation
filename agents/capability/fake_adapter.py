"""
FakeAdapter — agents/capability/fake_adapter.py

Phase 13's only real adapter registration. It does no I/O and talks to
nothing; its entire job is proving that a TestStep with
action=CAPABILITY_CHECK, capability_type=CapabilityType.FAKE actually
reaches an adapter's run() method through the full path:

    RunEngine -> OrchestratorKernel.call_tool("Capability.check")
              -> orchestrator/capability_router.py
              -> CapabilityAdapterRegistry.get(CapabilityType.FAKE)
              -> FakeAdapter.run(...)

Real adapters (api_adapter, db_adapter, email_adapter -- Phase 14 onward)
follow this exact same shape, just with real logic in run().
"""
from __future__ import annotations

from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType


class FakeAdapter:
    capability_type: CapabilityType = CapabilityType.FAKE

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        # Canned result. `params` is echoed back into `evidence` so tests
        # can assert the payload actually made it all the way through the
        # kernel's schema validation round-trip, not just that *some*
        # result came back.
        return CapabilityCheckResult(
            capability=payload.capability,
            passed=True,
            confidence=1.0,
            evidence={"canned": True, "echoed_params": payload.params},
            escalate=False,
        )
