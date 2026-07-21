"""
Backend router — orchestrator/backend_router.py (next-phase plan, Phase 4).

Decides which configured text-LLM backend (Hermes Agent or a generic
OpenAI-compat "cloud" endpoint) handles a given cross-cutting task, with a
per-task priority override and a real reachability check before a task is
committed to a backend.

Scope, deliberately narrow (see the conversation that shaped this file --
this was a genuine judgment call, not something to hardcode without
checking first): this router covers exactly the two tasks that had no
routing logic of their own before this phase --

  - "semantic_tie_break" (agents/vision/llm_verifier.py) -- fires
    potentially on every OCR/DOM disagreement, i.e. frequently, so
    latency matters more here.
  - "continuous_audit" (agents/auditor/run_monitor.py, Phase 1) -- fires
    at most once per step and only when explicitly enabled, so it can
    tolerate a slower/higher-quality backend more easily.

`agents/planner/spec_generator.py`'s own backend selection
(settings.planner_backend / planner_priority) is deliberately NOT folded
into this router. It already has a real, shipped, tested selection +
runtime-escalation system of its own, tightly coupled to
generate_spec()'s specific retry/escalation mechanics -- replacing it with
a generic pre-task selector here would be a behavior change to something
that isn't broken, for a system this phase doesn't need to touch. If a
third cross-cutting (not-generate_spec-shaped) task shows up later, it
belongs here; Planner's own system stays as-is.

Per-task priority (settings.semantic_tie_break_backend_priority /
continuous_audit_backend_priority) defaults to None, meaning "inherit
settings.backend_router_priority" -- so nobody's existing config has to
change for this phase to exist; the per-task override is there for when
someone actually wants the two tasks to diverge.

Reachability check: a real minimal chat call with a short, dedicated
timeout (settings.backend_router_health_check_timeout_s), not a bare TCP/
HTTP ping. Neither Hermes Agent nor an arbitrary OpenAI-compat endpoint is
guaranteed to expose a dedicated /health route, so the only way to
honestly verify "this backend will actually answer a chat request" is to
send one -- a raw connection check could pass while the actual
/v1/chat/completions contract still fails (wrong model name, auth
misconfigured, etc.). This costs a small amount of real latency/tokens
per task, which is exactly the tradeoff that was chosen over the cheaper
config-only check.

Reuses, rather than re-implements: settings._hermes_agent_available() /
_cloud_llm_available() for the "is this configured at all" check (same
config-only semantics those already have elsewhere), HermesAgentClient
(orchestrator/hermes_client.py) as-is, and orchestrator.capability_router
.is_egress_host_allowed() for the cloud path's egress check (same
allowlist mechanism CloudLLMBackend/HermesAgentClient/llm_verifier's old
private adapter all already used -- see _CloudChatClient below, which
replaces that adapter so there's exactly one implementation of this HTTP
+ security logic instead of two).
"""
from __future__ import annotations

import logging

from config.settings import settings

_logger = logging.getLogger(__name__)

_PRIORITY_CHOICES = ("hermes_first", "cloud_first")

_HEALTH_CHECK_SYSTEM = "You are a health check. Reply with exactly one word."
_HEALTH_CHECK_USER = "Reply with exactly: ok"


class _CloudChatClient:
    """
    Generic `.chat(system, user) -> str` wrapper around a configured
    cloud_llm_* endpoint. Replaces the private `_ChatAdapter` class that
    used to live inside agents/vision/llm_verifier.py -- same egress
    check, same request shape, just centralized here so
    agents/auditor/run_monitor.py doesn't have to reach into another
    module's private helper to get one (as it did before this phase).
    """

    def __init__(self, timeout_s: float | None = None) -> None:
        self.base_url = settings.cloud_llm_base_url
        self.api_key = settings.cloud_llm_api_key
        self.model = settings.cloud_llm_model
        self._timeout_s = timeout_s if timeout_s is not None else 60.0
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=self._timeout_s)
        return self._client

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        from urllib.parse import urlparse

        from orchestrator.capability_router import is_egress_host_allowed

        host = urlparse(self.base_url or "").hostname
        if not is_egress_host_allowed(host):
            raise RuntimeError(
                f"backend_router: host '{host}' (from cloud_llm_base_url) is not in "
                "settings.allowed_capability_hosts -- refusing to call it."
            )

        client = self._get_client()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{(self.base_url or '').rstrip('/')}/chat/completions"
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 200,
        }
        response = client.post(url, headers=headers, json=body)
        if response.status_code != 200:
            raise RuntimeError(
                f"backend_router: cloud chat request to {url} failed with "
                f"status {response.status_code}: {response.text[:300]}"
            )
        return response.json()["choices"][0]["message"]["content"]


def _priority_for_task(task_type: str) -> str:
    override = getattr(settings, f"{task_type}_backend_priority", None)
    priority = override or settings.backend_router_priority
    if priority not in _PRIORITY_CHOICES:
        _logger.warning(
            "backend_router: unrecognized priority %r for task %r, falling back to 'hermes_first'. "
            "Valid choices: %s.",
            priority, task_type, ", ".join(_PRIORITY_CHOICES),
        )
        priority = "hermes_first"
    return priority


def _candidate_order(priority: str) -> list[str]:
    return ["hermes", "cloud"] if priority == "hermes_first" else ["cloud", "hermes"]


def _is_configured(name: str) -> bool:
    if name == "hermes":
        return settings._hermes_agent_available()
    return settings._cloud_llm_available()


def _build_client(name: str, timeout_s: float | None = None):
    if name == "hermes":
        from orchestrator.hermes_client import HermesAgentClient

        return HermesAgentClient(timeout_s=timeout_s or 90.0)
    return _CloudChatClient(timeout_s=timeout_s)


def _health_check(client) -> bool:
    try:
        reply = client.chat(_HEALTH_CHECK_SYSTEM, _HEALTH_CHECK_USER)
        return bool(reply and reply.strip())
    except Exception as e:  # noqa: BLE001 - a failed health check just means "try the next candidate"
        _logger.info("backend_router: health check failed for %s: %s", type(client).__name__, e)
        return False


def select_backend(task_type: str):
    """
    Returns a ready-to-use `.chat(system, user) -> str` client for
    `task_type` ("semantic_tie_break" or "continuous_audit"), or None if
    nothing configured is actually reachable right now. Never raises --
    every failure (not configured, health check failed, unrecognized
    priority) just means "try the next candidate, or give up and return
    None," matching the fail-soft contract both call sites already relied
    on before this phase existed.
    """
    priority = _priority_for_task(task_type)
    for name in _candidate_order(priority):
        if not _is_configured(name):
            continue
        client = _build_client(name, timeout_s=settings.backend_router_health_check_timeout_s)
        if _health_check(client):
            _logger.info("backend_router: selected %s for task %r.", name, task_type)
            # Health check used a short dedicated timeout -- rebuild with
            # the backend's normal timeout for the actual task call that
            # follows, rather than making the real call race the probe's
            # deliberately tight budget.
            return _build_client(name)
        _logger.warning(
            "backend_router: %s is configured but failed its health check for "
            "task %r -- trying the next candidate.", name, task_type,
        )
    return None
