"""
Hermes Agent client — Phase W (docs/decisions.md D-047).

`docs/PROJECT_OVERVIEW.md` has always described AURA as "orchestrated via
the Hermes Agent API," but no code path to a real Hermes Agent instance
ever existed -- decisions.md D-006 replaced that idea early on with the
in-repo `orchestrator/kernel.py`, which keeps the same external tool-call
contract without depending on an external service being installed. That
architectural decision stands: this module does NOT make Hermes Agent a
required dependency, and it does not change how `OrchestratorKernel`
dispatches tools.

What this module *does* do is make the Hermes Agent integration real
rather than aspirational prose: Hermes Agent (https://github.com/
NousResearch/hermes-agent) exposes a genuine OpenAI-compatible HTTP
surface --

    POST {base_url}/v1/chat/completions
    Authorization: Bearer <API_SERVER_KEY>
    X-Hermes-Session-Id: <optional, for multi-turn continuity>

-- confirmed against Hermes Agent's own docs (website/docs/user-guide/
features/api-server.md, api-server.md's `.plans/openai-api-server.md`).
`HermesAgentClient` is a thin, dependency-free (stdlib httpx only) wrapper
around that endpoint, reusing the exact same egress-allowlist mechanism
Phase D built for capability adapters and Phase V reused for
CloudLLMBackend (`orchestrator.capability_router.is_egress_host_allowed`)
-- no new security surface, no duplicated allowlist logic.

Two ways this gets used elsewhere in the codebase:
  1. `agents/planner/spec_generator.py::HermesAgentBackend` -- an
     opt-in planner backend (`settings.planner_backend = "hermes_agent"`)
     that asks a running Hermes Agent instance to produce a TestSpec,
     instead of talking to a raw OpenAI-compatible completion endpoint
     directly (CloudLLMBackend) -- this gets you Hermes's own tool use,
     memory, and skill recall for free if you're already running it.
  2. `agents/vision/llm_verifier.py` -- semantic tie-break verification
     (see that module's docstring) can be pointed at a Hermes Agent
     instance the same way it can at a raw cloud/local OpenAI-compat
     endpoint.

Off by default. Nothing in the existing execution path calls this module
unless the operator explicitly configures AURA_ENABLE_HERMES_AGENT=true
and a base URL.
"""
from __future__ import annotations

from urllib.parse import urlparse

from config.settings import settings


class HermesAgentConfigError(RuntimeError):
    pass


class HermesAgentEgressBlockedError(RuntimeError):
    pass


class HermesAgentClient:
    """
    Talks to a running Hermes Agent instance's API server
    (started via `hermes gateway` -- not `hermes api-server`, which
    doesn't exist in the real CLI, see docs/debug_report.md's Phase 5
    entry) via its OpenAI-compatible `/v1/chat/completions` endpoint.

    Deliberately NOT a general Hermes SDK -- AURA only needs one call
    shape (send messages, get back the final assistant message), so this
    stays a minimal client rather than reimplementing Hermes's session
    management, streaming, or tool-gateway features. Session continuity
    (X-Hermes-Session-Id) is supported because it's a single extra header
    and genuinely useful for multi-step spec-generation conversations, but
    is optional and stateless by default (one-shot per call).
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        session_id: str | None = None,
        timeout_s: float = 90.0,
    ) -> None:
        self.base_url = base_url or settings.hermes_agent_base_url
        self.api_key = api_key or settings.hermes_agent_api_key
        # Hermes's own docs note the `model` field in requests is cosmetic
        # (the real model is configured server-side in Hermes's config.yaml)
        # -- still accepted here for forward-compat / clarity in logs, not
        # because Hermes actually switches models based on it.
        self.model = model or settings.hermes_agent_model or "hermes-agent"
        self.session_id = session_id
        self.timeout_s = timeout_s
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=self.timeout_s)
        return self._client

    def _check_egress(self) -> None:
        from orchestrator.capability_router import is_egress_host_allowed

        if not self.base_url:
            raise HermesAgentConfigError(
                "HermesAgentClient requires settings.hermes_agent_base_url "
                "(or AURA_HERMES_AGENT_BASE_URL / a .env entry) -- the base "
                "URL of a running Hermes Agent API server, e.g. "
                "'http://localhost:8642' (Hermes Agent's own default "
                "API_SERVER_PORT -- start it with `hermes gateway` after "
                "setting API_SERVER_ENABLED=true/API_SERVER_KEY in "
                "~/.hermes/.env; there is no `hermes api-server` command)."
            )
        host = urlparse(self.base_url).hostname
        if not is_egress_host_allowed(host):
            raise HermesAgentEgressBlockedError(
                f"HermesAgentClient: host '{host}' (from hermes_agent_base_url) "
                "is not in settings.allowed_capability_hosts. Add it to the "
                "allowlist (or leave the allowlist unset to allow all hosts) "
                "before enabling the Hermes Agent backend."
            )

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        """
        Sends a single system+user turn to Hermes Agent's chat-completions
        endpoint and returns the assistant's text content. Raises on any
        transport/HTTP-status failure -- callers (HermesAgentBackend,
        the LLM semantic verifier) are responsible for retry/escalation
        policy, matching CloudLLMBackend's contract.
        """
        self._check_egress()

        url = f"{self.base_url.rstrip('/')}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.session_id:
            headers["X-Hermes-Session-Id"] = self.session_id

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": settings.local_llm_temperature,
            "max_tokens": settings.local_llm_max_tokens,
            "stream": False,
        }

        client = self._get_client()
        from orchestrator.http_retry import post_with_retry

        response = post_with_retry(
            client, url, headers=headers, json=body,
            caller_name="HermesAgentClient", decision_trace_category="network_retry",
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"HermesAgentClient request to {url} failed with status "
                f"{response.status_code}: {response.text[:500]}"
            )

        response_body = response.json()
        return response_body["choices"][0]["message"]["content"]
