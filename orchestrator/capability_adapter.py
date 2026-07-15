from __future__ import annotations
from typing import Protocol, runtime_checkable
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType


@runtime_checkable
class CapabilityAdapter(Protocol):
    """
    Structural interface (not an ABC) so adapters don't need to import and
    subclass anything from this module -- they just need the right shape.
    Matches the pattern already used for tool entrypoints in
    orchestrator/kernel.py (plain functions, not registered classes).
    """

    capability_type: CapabilityType

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
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

    def get(self, capability_type: CapabilityType | None) -> CapabilityAdapter:
        if capability_type is None:
            raise CapabilityAdapterNotFoundError(
                "This step has no capability_type set, so there's no adapter to route it to "
                "(a capability_check step must specify one, e.g. 'api', 'database', 'file_system')."
            )
        if capability_type not in self._adapters:
            raise CapabilityAdapterNotFoundError(
                f"No adapter registered for capability_type '{capability_type.value}'"
            )
        return self._adapters[capability_type]

    def registered_types(self) -> list[CapabilityType]:
        return list(self._adapters.keys())


def default_registry() -> CapabilityAdapterRegistry:
    """
    Builds the registry used by orchestrator/capability_router.py at runtime.
    Phase 15 adds File, Excel, and PDF adapters.
    """
    from agents.capability.fake_adapter import FakeAdapter
    from agents.capability.api_adapter import ApiAdapter
    from agents.capability.db_adapter import DbAdapter
    from agents.capability.email_adapter import EmailAdapter
    from agents.capability.file_adapter import FileAdapter
    from agents.capability.excel_adapter import ExcelAdapter
    from agents.capability.pdf_adapter import PdfAdapter
    from agents.capability.cloud_adapter import CloudAdapter
    from agents.capability.workflow_adapter import WorkflowAdapter
    from agents.capability.azure_adapter import AzureBlobAdapter
    from agents.capability.gcp_adapter import GcpStorageAdapter
    from agents.capability.sharepoint_adapter import SharePointAdapter
    from agents.capability.chatops_adapter import ChatOpsAdapter
    from agents.capability.link_checker import LinkCheckAdapter
    from agents.capability.automation_anywhere_adapter import AutomationAnywhereAdapter
    from agents.capability.playwright_validator import PlaywrightValidator
    from agents.capability.accessibility_adapter import AccessibilityAdapter
    from agents.capability.security_headers_adapter import SecurityHeadersAdapter
    from agents.capability.performance_adapter import PerformanceAdapter

    registry = CapabilityAdapterRegistry()
    registry.register(FakeAdapter())
    registry.register(ApiAdapter())
    registry.register(DbAdapter())
    registry.register(EmailAdapter())
    registry.register(FileAdapter())
    registry.register(ExcelAdapter())
    registry.register(PdfAdapter())
    registry.register(CloudAdapter())
    registry.register(WorkflowAdapter())
    registry.register(AzureBlobAdapter())
    registry.register(GcpStorageAdapter())
    registry.register(LinkCheckAdapter())
    registry.register(SharePointAdapter())
    registry.register(ChatOpsAdapter())
    registry.register(AutomationAnywhereAdapter())
    registry.register(PlaywrightValidator())
    registry.register(AccessibilityAdapter())
    registry.register(SecurityHeadersAdapter())
    registry.register(PerformanceAdapter())
    return registry