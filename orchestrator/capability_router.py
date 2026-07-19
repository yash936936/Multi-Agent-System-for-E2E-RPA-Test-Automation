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

from datetime import datetime, timezone
from urllib.parse import urlparse

from config.settings import settings
from orchestrator.audit_logger import audit_logger
from orchestrator.capability_adapter import CapabilityAdapterRegistry, default_registry
from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

_registry: CapabilityAdapterRegistry | None = None

# Phase D (decisions.md D-020): parameter keys, across the existing capability
# adapters, that carry a URL/connection-string/host the adapter will actually
# reach out to. Verified against each adapter's own `params.get(...)` calls
# (agents/capability/*.py) rather than assumed -- see decisions.md D-020 for
# the per-adapter audit this list is drawn from.
_URL_PARAM_KEYS = ("url", "webhook_url", "account_url", "endpoint", "control_room_url", "base_url")
_CONN_STRING_PARAM_KEYS = ("connection_string", "conn_str")
_BARE_HOST_PARAM_KEYS = ("smtp_server", "imap_server", "host")

# Capabilities with no real network host to check -- purely local
# filesystem/canned-result adapters. Exempt from allowlist matching (there
# is nothing to match), but a kill-switch rejection still applies to all of
# them for a genuinely uniform "one flag disables the whole layer" story.
_NO_HOST_CAPABILITIES = {CapabilityType.FAKE}


def _get_registry() -> CapabilityAdapterRegistry:
    global _registry
    if _registry is None:
        _registry = default_registry()
    return _registry


def _parse_azure_connection_string_host(conn_str: str) -> str | None:
    """
    Phase Y3 (decisions.md D-050): Azure Storage connection strings are
    `Key1=Value1;Key2=Value2;...` pairs, NOT a URL -- `urlparse(conn_str)
    .hostname` silently returns None for them even when a connection
    string genuinely was supplied, which is why AZURE_BLOB egress hosts
    were falling through to `None` (unblockable by the allowlist) even in
    the *common* case, not just the SDK-default-credential-chain case the
    original docstring described. Real fix: parse the key=value pairs
    Azure's own connection-string format uses and reconstruct the blob
    endpoint host the same way `BlobServiceClient.from_connection_string`
    does internally (AccountName + EndpointSuffix, or BlobEndpoint
    directly if present).
    """
    fields: dict[str, str] = {}
    for part in conn_str.split(";"):
        if "=" in part:
            key, _, value = part.partition("=")
            fields[key.strip()] = value.strip()

    if fields.get("BlobEndpoint"):
        host = urlparse(fields["BlobEndpoint"]).hostname
        if host:
            return host

    account_name = fields.get("AccountName")
    if account_name:
        endpoint_suffix = fields.get("EndpointSuffix", "core.windows.net")
        return f"{account_name}.blob.{endpoint_suffix}"

    return None


# Phase Y3 (decisions.md D-050): Google Cloud Storage's default JSON API
# endpoint -- true regardless of which credential path (service-account
# JSON file, Application Default Credentials, attached service account)
# the GCP adapter authenticates with, since none of those change *where*
# the request goes, only *how* it's authorized. A custom/private endpoint
# override, if the adapter ever grows one, would still take precedence via
# the existing `endpoint` key in _URL_PARAM_KEYS, checked first.
_GCS_DEFAULT_HOST = "storage.googleapis.com"


def _extract_egress_host(payload: CapabilityCheckInput) -> str | None:
    """
    Best-effort extraction of the network host a capability call will reach
    out to, for allowlist-checking and audit logging.

    Phase Y3 (decisions.md D-050) closed two real gaps here: Azure
    connection strings weren't being parsed correctly at all (see
    `_parse_azure_connection_string_host`'s docstring), and GCP_STORAGE
    calls always resolve to a fixed, well-known host
    (`storage.googleapis.com`) regardless of credential path, so there was
    no reason to treat that capability as unresolvable. `sharepoint_adapter`
    (SDK-managed, tenant-specific, no fixed host) remains a genuine
    fail-open case -- documented, not silently pretended away.
    """
    params = payload.params or {}

    for key in _URL_PARAM_KEYS:
        value = params.get(key)
        if value:
            host = urlparse(str(value)).hostname
            if host:
                return host

    for key in _CONN_STRING_PARAM_KEYS:
        value = params.get(key)
        if value:
            host = urlparse(str(value)).hostname
            if host:
                return host
            # Not a URL-shaped connection string -- try Azure's real
            # Key1=Value1;Key2=Value2 format before giving up on this key.
            azure_host = _parse_azure_connection_string_host(str(value))
            if azure_host:
                return azure_host

    for key in _BARE_HOST_PARAM_KEYS:
        value = params.get(key)
        if value:
            return str(value)

    if payload.capability == CapabilityType.AZURE_BLOB:
        import os

        env_conn_str = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
        if env_conn_str:
            azure_host = _parse_azure_connection_string_host(env_conn_str)
            if azure_host:
                return azure_host

    if payload.capability == CapabilityType.GCP_STORAGE:
        # No 'endpoint' param override was found above -- GCS always talks
        # to its fixed default host regardless of credential path.
        return _GCS_DEFAULT_HOST

    if payload.target:
        host = urlparse(str(payload.target)).hostname
        if host:
            return host

    return None


def _host_allowed(host: str | None, allowed_hosts: list[str] | None) -> bool:
    if not allowed_hosts:
        return True
    if host is None:
        # Nothing resolvable to check against the allowlist -- fail open
        # rather than blocking every SDK-managed adapter outright; the
        # kill switch remains the hard backstop for those cases.
        return True
    host = host.lower()
    for entry in allowed_hosts:
        entry = entry.lower().lstrip(".")
        if host == entry or host.endswith("." + entry):
            return True
    return False


def is_egress_host_allowed(host: str | None) -> bool:
    """
    Public wrapper around `_host_allowed`, checked against the live
    `settings.allowed_capability_hosts` allowlist. Phase V (decisions.md
    D-044, `agents/planner/spec_generator.py::CloudLLMBackend`) reuses this
    exact function for the cloud-LLM egress check rather than building a
    second allowlist mechanism -- the roadmap's own explicit instruction.
    Same semantics as every capability adapter's egress check: an unset
    allowlist means "allow everything" (opt-in restriction), and an
    unresolvable host fails open (the kill switches are the hard backstop).
    """
    return _host_allowed(host, settings.allowed_capability_hosts)


def _rejected_result(capability: CapabilityType, reason: str, host: str | None) -> CapabilityCheckResult:
    return CapabilityCheckResult(
        capability=capability,
        passed=False,
        confidence=0.0,
        evidence={"rejected": True, "reason": reason, "host": host},
        escalate=True,
    )


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

    # Phase D hard kill switch: reject before any adapter runs, or even
    # before the registry is touched, so a fully air-gapped operator gets
    # a clean, uniform rejection regardless of which capability was asked
    # for -- no adapter-specific code path to remember to also disable.
    if not settings.capability_adapters_enabled:
        return _rejected_result(
            payload.capability,
            "capability_adapters_enabled is False -- outbound capability checks are disabled",
            host=None,
        )

    host = None if payload.capability in _NO_HOST_CAPABILITIES else _extract_egress_host(payload)

    if not _host_allowed(host, settings.allowed_capability_hosts):
        return _rejected_result(
            payload.capability,
            f"host '{host}' is not in settings.allowed_capability_hosts",
            host=host,
        )

    # Audit trail (decisions.md D-020): log the outbound target host and
    # timestamp for every permitted capability call -- never the payload
    # contents (params may carry credentials/secrets), matching the same
    # audit_logger.log() sink already used for run-level auditing in
    # api/routers/runs.py, so operators have one place to review both
    # request-level and capability-egress activity.
    audit_logger.log(
        tenant_id="system",
        user_id="system",
        action="CAPABILITY_EGRESS",
        resource=payload.capability.value,
        details={
            "host": host,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

    adapter = _get_registry().get(payload.capability)
    return adapter.run(payload)


# Backward-compatible alias: earlier code/tests referred to this function
# as `check_capability` before it was renamed to `route_capability`.
check_capability = route_capability
