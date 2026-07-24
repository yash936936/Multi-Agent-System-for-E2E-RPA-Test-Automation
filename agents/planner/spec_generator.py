"""
Spec generator — Planner.generate_spec

Converts normalized requirement text into a schema-valid TestSpec
(orchestrator/schemas.py). Backend is pluggable:

  - LocalHeuristicBackend (default): pure-Python sentence-pattern parser.
    No network call, no model weights — matches decisions.md D-002
    (fully offline) and D-004 (agents defined by contract, not by a
    specific model). Always available with zero dependencies; the
    guaranteed last-resort backend unless settings.require_llm_backend
    says otherwise (see CloudLLMBackend below).

  - LocalLLMBackend (opt-in): a small local GGUF model (llama-cpp-python),
    run fully on-device. No network call is made at any point.

  - CloudLLMBackend (opt-in, Phase V, decisions.md D-044): a generic
    OpenAI-compatible HTTP client — no vendor SDK, no hardcoded provider.
    Works against a real cloud endpoint or an operator's own local
    OpenAI-compat server (Ollama, llama.cpp server mode, etc.) equally;
    "cloud" names the code path, not a requirement that the endpoint be
    remote. Off by default (settings.enable_cloud_planner); every
    outbound call is checked against the same egress allowlist Phase D
    built for capability adapters
    (orchestrator.capability_router.is_egress_host_allowed), reused
    rather than duplicated.

2026-07-13 (decisions.md D-018, roadmap Phase B): AnthropicBackend and the
`allow_network_calls` setting were removed entirely, not just disabled —
there was no network-capable code path left anywhere in the planner as of
that phase, not "off by default," genuinely absent, so there was no
residual attack surface, no accidental-enable risk via a config flag, and
no dependency on an external API being reachable or funded.

2026-07-17 (decisions.md D-044, roadmap Phase V): a network-capable path
was deliberately reintroduced, but on much stricter terms than
AnthropicBackend's — see CloudLLMBackend above. `generate_spec` now
resolves among three backends via a local-first (or cloud-first, via
settings.planner_priority) auto-detection matrix at Settings-construction
time, plus a logged local-to-cloud escalation policy at call time if the
auto-detected primary backend fails — see generate_spec's own docstring
below for the exact contract.

Every backend must return data that validates against TestSpec; if it
doesn't, generate_spec re-prompts that same backend once (WORKFLOW.md Step
1.3, decisions.md D-039) before either raising (explicit-backend callers)
or escalating (the default auto-resolved path).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Protocol

from config.settings import settings
from orchestrator.decision_trace_log import decision_trace_log
from orchestrator.schemas import (
    ActionType,
    AssertionType,
    CapabilityType,
    RequirementInput,
    TestSpec,
    TestStep,
)


def infer_test_id(text: str) -> str:
    """
    Derives a TC-<SLUG>-001 test_id from a requirement doc's first `#`
    heading (falling back to "GENERATED"/"FLOW" if none is found).

    Module-level (not just a backend-internal method) so callers that need
    to know a doc's test_id *without* running the full spec-generation
    pipeline -- e.g. Phase H2's `aura execute --all` quarantine skip-check,
    which needs the id before deciding whether to generate a spec at all --
    can reuse this exact logic instead of re-deriving it with a
    hand-copied regex that could silently drift out of sync over time.
    """
    heading_match = re.search(r"^#+\s*(.+)$", text, re.MULTILINE)
    base = heading_match.group(1) if heading_match else "GENERATED"
    slug = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").upper()
    slug = slug[:24] if slug else "FLOW"
    return f"TC-{slug}-001"


def extract_navigate_url(text: str) -> str | None:
    """
    Finds the first "navigate to <url>"-shaped phrase in a requirement
    doc, if any. Module-level (like infer_test_id above, and for the same
    reason its docstring gives) so callers that need a doc's target URL
    *without* running full spec generation -- e.g.
    aura/cli/execute_cmd.py's grounding step (agents/planner/page_grounding.py),
    which needs the URL before generate_spec() is even called -- can reuse
    this exact matching logic instead of a hand-copied, driftable regex.
    """
    for pattern in _NAVIGATE_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(1).rstrip(').,;"\'')
    return None


class SpecBackend(Protocol):
    def generate(self, requirement_text: str) -> dict:
        """Return a dict shaped like TestSpec (pre-validation)."""
        ...


# --------------------------------------------------------------------------
# Default offline backend
# --------------------------------------------------------------------------

_CLICK_PATTERNS = [
    re.compile(r"\bclick(?:s|ed|ing)?\s+(?:on\s+)?(?:the\s+)?(.+?)(?:\.|$)", re.IGNORECASE),
    re.compile(r"\btap(?:s|ped|ping)?\s+(?:on\s+)?(?:the\s+)?(.+?)(?:\.|$)", re.IGNORECASE),
]
_TYPE_PATTERNS = [
    re.compile(r"\b(?:enter|enters|type|types|input|inputs)\s+(?:a\s+|the\s+|their\s+)?(.+?)\s+(?:into|in)\s+(?:the\s+)?(.+?)(?:\.|$)", re.IGNORECASE),
]
_ASSERT_PATTERNS = [
    re.compile(r"\b(?:should see|sees|is shown|is redirected to|expects?|verify|verifies)\s+(?:the\s+)?(.+?)(?:\.|$)", re.IGNORECASE),
]
# AD1 (docs/decisions.md D-060) -- explicit negative-assertion phrasing.
# Checked before _ASSERT_PATTERNS since "should not see X" would otherwise
# also match "should see"'s pattern on the wrong substring boundary.
_NEGATIVE_ASSERT_PATTERNS = [
    re.compile(r"\b(?:should not|shouldn't|must not|mustn't|does not|doesn't)\s+(?:see|show|display)\s+(?:the\s+)?(.+?)(?:\.|$)", re.IGNORECASE),
]
_NAVIGATE_PATTERNS = [
    re.compile(r"\bnavigate(?:s|d)?\s+to\s+(https?://\S+)", re.IGNORECASE),
    re.compile(r"\bgo(?:es|ing)?\s+to\s+(https?://\S+)", re.IGNORECASE),
    re.compile(r"\bopen(?:s|ed|ing)?\s+(?:the\s+(?:browser|site|page|url)\s+(?:at|to)\s+)?(https?://\S+)", re.IGNORECASE),
    re.compile(r"browser\s+is\s+open\s+at\s+(https?://\S+)", re.IGNORECASE),
    re.compile(r"\btarget[\s_-]?url\s*:?\s*(https?://\S+)", re.IGNORECASE),
    # Matches the literal "Target: <url>" line the API builds for autonomous
    # runs (see api/routers/runs.py create_run) -- without this, an
    # autonomous run's requirement_text ("Target: https://example.com\n\n
    # check homepage loads") never matched any of the patterns above
    # (they all require the word "url" or a verb like navigate/go/open),
    # so no NAVIGATE_URL step was ever produced.
    re.compile(r"^\s*target\s*:\s*(https?://\S+)", re.IGNORECASE | re.MULTILINE),
]
_LINK_CHECK_PATTERN = re.compile(
    r"\b(links?|buttons?)\b.{0,40}\b(working|functional|broken|valid|active|clickable|not\s+working)\b"
    r"|\b(broken|dead)\s+links?\b"
    r"|\bcheck\b.{0,40}\blinks?\b",
    re.IGNORECASE | re.DOTALL,
)
_LINK_SCOPE_PATTERN = re.compile(r"\b(footer|nav(?:igation)?|header)\b", re.IGNORECASE)
_PRECONDITION_MARKERS = re.compile(r"^\s*(?:given|precondition|assumes?)\s*:?\s*(.+)$", re.IGNORECASE)
_DATA_FIELD_HINTS = re.compile(r"\b(username|password|email|phone|name|address|date of birth|dob|zip|postal code|credit card)\b", re.IGNORECASE)
_EDGE_CASE_HINTS = re.compile(r"\b(unicode|max(?:imum)? length|boundary|edge case|malformed|special character)\b", re.IGNORECASE)


class LocalHeuristicBackend:
    """
    Deterministic, offline requirement-text -> TestSpec parser.

    Not a substitute for real language understanding, but sufficient to
    turn well-structured requirement docs (like requirements_input/example_login_flow.md)
    into a valid, testable TestSpec without any network dependency —
    which is exactly what's needed to keep this pipeline runnable end to
    end in an offline sandbox.
    """

    def generate(self, requirement_text: str) -> dict:
        lines = [line.strip("-* \t") for line in requirement_text.splitlines() if line.strip()]

        test_id = self._infer_test_id(requirement_text)
        preconditions = self._extract_preconditions(lines)
        steps = self._extract_steps(lines)
        nav_url = self._extract_navigate_url(requirement_text)

        # A request like "check if the footer service links are working"
        # matches none of the click/type patterns above (there's no literal
        # "click X" phrasing) -- previously that meant it silently fell
        # through to the generic "assert page_loaded" fallback further
        # down, which never looks at a single link and reports "passed"
        # regardless of what's actually on the page. Recognize this intent
        # explicitly and emit a real CAPABILITY_CHECK(LINK_CHECK) step
        # instead, which makes actual HTTP requests against every link in
        # scope (agents/capability/link_checker.py).
        link_check_step = None
        if nav_url and _LINK_CHECK_PATTERN.search(requirement_text):
            scope_match = _LINK_SCOPE_PATTERN.search(requirement_text)
            scope = "footer" if scope_match and scope_match.group(1).lower() == "footer" else (
                "nav" if scope_match and scope_match.group(1).lower().startswith("nav") else "all"
            )
            link_check_step = TestStep(
                step_id=1,
                action=ActionType.CAPABILITY_CHECK,
                target_description=f"link check ({scope}) on {nav_url}",
                capability_type=CapabilityType.LINK_CHECK,
                capability_params={"url": nav_url, "scope": scope},
            )

        if nav_url:
            steps = self._prepend_navigate_step(steps, nav_url)
        assertions = self._extract_assertions(lines)
        data_requirements = self._extract_data_requirements(requirement_text)

        if link_check_step is not None:
            # Insert right after the navigate step (or at the front if
            # there wasn't one) and renumber everything sequentially.
            insert_at = 1 if steps else 0
            combined = [*steps[:insert_at], link_check_step, *steps[insert_at:]]
            steps = [s.model_copy(update={"step_id": i}) for i, s in enumerate(combined, start=1)]

        # Fallback: free-text prompts (most commonly autonomous-mode runs,
        # e.g. "check homepage loads" with no explicit "click"/"type"/
        # "navigate to" phrasing) can legitimately match none of the
        # patterns above. Previously that meant `steps` stayed [], which
        # fails TestSpec's "must contain at least one step" validator and
        # crashed the whole run with a 500 before a single action ever
        # executed. Treat an unmatched prompt as an implicit "assert the
        # page loaded" check instead of raising -- this is what an
        # undirected exploration prompt means in practice, and it keeps
        # the offline heuristic backend able to always produce a valid
        # spec.
        if not steps:
            steps = [TestStep(step_id=1, action=ActionType.ASSERT, expected_state="page_loaded", assertion_kind="page_rendered")]
        if not assertions:
            assertions = [{"type": AssertionType.VISUAL_STATE.value, "expected": "page_loaded", "assertion_kind": "page_rendered"}]

        return {
            "test_id": test_id,
            "requirement_ref": test_id,
            "preconditions": preconditions,
            "steps": [s.model_dump() for s in steps] if steps and isinstance(steps[0], TestStep) else steps,
            "assertions": assertions,
            "data_requirements": data_requirements,
        }

    def _infer_test_id(self, text: str) -> str:
        return infer_test_id(text)

    def _extract_preconditions(self, lines: list[str]) -> list[str]:
        out = []
        for line in lines:
            m = _PRECONDITION_MARKERS.match(line)
            if m:
                out.append(re.sub(r"\s+", "_", m.group(1).strip().lower()))
        return out

    def _extract_steps(self, lines: list[str]) -> list[TestStep]:
        steps: list[TestStep] = []
        step_id = 1
        for line in lines:
            m = _TYPE_PATTERNS[0].search(line)
            if m:
                value_desc, field_desc = m.group(1).strip(), m.group(2).strip()
                steps.append(
                    TestStep(
                        step_id=step_id,
                        action=ActionType.TYPE_TEXT,
                        field_description=field_desc,
                        value_ref=f"synthetic.{self._slug(value_desc)}",
                    )
                )
                step_id += 1
                continue

            for pattern in _CLICK_PATTERNS:
                m = pattern.search(line)
                if m:
                    steps.append(
                        TestStep(
                            step_id=step_id,
                            action=ActionType.VISUAL_CLICK,
                            target_description=m.group(1).strip(),
                        )
                    )
                    step_id += 1
                    break
        return steps

    def _extract_navigate_url(self, text: str) -> str | None:
        return extract_navigate_url(text)

    def _prepend_navigate_step(self, steps: list[TestStep], url: str) -> list[TestStep]:
        # Inserts a NAVIGATE_URL step as step 1 (closes the gap where a
        # browser had to already be open at the right page before
        # `aura execute` started). Every other extracted step is
        # renumbered to follow it, keeping step_ids contiguous.
        nav_step = TestStep(
            step_id=1,
            action=ActionType.NAVIGATE_URL,
            url=url,
            target_description=f"navigate to {url}",
        )
        renumbered = [s.model_copy(update={"step_id": i}) for i, s in enumerate(steps, start=2)]
        return [nav_step, *renumbered]

    def _extract_assertions(self, lines: list[str]) -> list[dict]:
        out = []
        for line in lines:
            negative_matched = False
            for pattern in _NEGATIVE_ASSERT_PATTERNS:
                m = pattern.search(line)
                if m:
                    out.append({
                        "type": AssertionType.VISUAL_STATE.value,
                        "expected": self._slug(m.group(1)),
                        "assertion_kind": "negative",
                    })
                    negative_matched = True
            if negative_matched:
                # A line matching the negative pattern (e.g. "should not
                # see the error banner") would also match _ASSERT_PATTERNS'
                # broader "should see"-style regex on an overlapping
                # substring -- skip the positive patterns for this line so
                # one real assertion doesn't get emitted twice with
                # contradictory kinds.
                continue
            for pattern in _ASSERT_PATTERNS:
                m = pattern.search(line)
                if m:
                    out.append({
                        "type": AssertionType.VISUAL_STATE.value,
                        "expected": self._slug(m.group(1)),
                        "assertion_kind": "literal_text",
                    })
        return out

    def _extract_data_requirements(self, text: str) -> list[str]:
        fields = {m.lower().replace(" ", "_") for m in _DATA_FIELD_HINTS.findall(text)}
        edge_cases = {f"edge_case_{m.lower().replace(' ', '_')}" for m in _EDGE_CASE_HINTS.findall(text)}
        return sorted(fields | edge_cases)

    @staticmethod
    def _slug(text: str) -> str:
        return re.sub(r"\s+", "_", text.strip().lower())


# --------------------------------------------------------------------------
# Local, fully-offline LLM backend (decisions.md D-010)
# --------------------------------------------------------------------------

class LocalLLMModelNotFoundError(RuntimeError):
    pass


class LocalLLMBackend:
    """
    Runs spec generation through a small local LLM (any GGUF-format model,
    e.g. a quantized Llama/Mistral/Phi variant) entirely on-device via
    llama-cpp-python. No network call is made at any point, so this stays
    compatible with the offline guarantee in decisions.md D-002 -- this is
    now the *only* LLM-backed planner path (AnthropicBackend was removed
    entirely, decisions.md D-018).

    This is intentionally *not* wired up to download a model automatically:
    per D-002/D-005 (no fixed hardware baseline, no silent network calls),
    the operator must explicitly place a .gguf file on disk and point
    settings.local_llm_model_path (or AURA_LOCAL_LLM_MODEL_PATH / .env) at
    it. This keeps model provenance and size fully within the operator's
    control, which matters for the compliance persona in PRD.md.

    The model is loaded lazily on first use (not at import time) and
    cached on the instance, since construction is the expensive part
    (reading weights into memory) -- repeated .generate() calls on the
    same backend instance reuse the loaded model.
    """

    def __init__(self, model_path: str | None = None) -> None:
        self.model_path = model_path or settings.local_llm_model_path
        self._llm = None

    def _load(self):
        if self._llm is not None:
            return self._llm

        if not self.model_path:
            raise LocalLLMModelNotFoundError(
                "LocalLLMBackend requires settings.local_llm_model_path (or "
                "AURA_LOCAL_LLM_MODEL_PATH / a .env entry) to point at a local "
                ".gguf model file. AURA does not download models automatically "
                "-- place one on disk and point this setting at it. Small "
                "instruction-tuned models (1-4B parameters, Q4/Q5 quantized) "
                "are sufficient for this structured-extraction task."
            )

        model_file = Path(self.model_path)
        if not model_file.exists():
            raise LocalLLMModelNotFoundError(
                f"local_llm_model_path is set to '{self.model_path}' but no file exists there."
            )

        try:
            from llama_cpp import Llama
        except ImportError as e:
            raise RuntimeError(
                "LocalLLMBackend requires the optional 'llm' dependency group. "
                "Install it with: pip install -e '.[llm]'"
            ) from e

        self._llm = Llama(
            model_path=str(model_file),
            n_ctx=settings.local_llm_context_size,
            verbose=False,
        )
        return self._llm

    def generate(self, requirement_text: str) -> dict:
        from agents.planner.prompts import SPEC_GENERATION_SYSTEM_PROMPT, SPEC_GENERATION_USER_TEMPLATE

        llm = self._load()
        completion = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": SPEC_GENERATION_SYSTEM_PROMPT},
                {"role": "user", "content": SPEC_GENERATION_USER_TEMPLATE.format(requirement_text=requirement_text)},
            ],
            max_tokens=settings.local_llm_max_tokens,
            temperature=settings.local_llm_temperature,
        )
        text = completion["choices"][0]["message"]["content"]
        return _extract_json_object(text)


def _extract_json_object(text: str) -> dict:
    """
    Small local models don't always follow "JSON only, no prose" perfectly
    even when instructed to -- strip markdown code fences and grab the
    outermost {...} block before parsing, rather than failing outright on
    a stray "Here is the JSON:" preamble.
    """
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"LocalLLMBackend output did not contain a JSON object: {text[:200]!r}")
    return json.loads(text[start : end + 1])


# --------------------------------------------------------------------------
# Generic OpenAI-compatible cloud/remote-server LLM backend (Phase V, D-044)
# --------------------------------------------------------------------------

class CloudLLMConfigError(RuntimeError):
    pass


class CloudLLMEgressBlockedError(RuntimeError):
    pass


class CloudLLMBackend:
    """
    Runs spec generation through any server implementing the OpenAI
    Chat Completions HTTP shape (`POST {base_url}/chat/completions`) --
    no vendor SDK, no hardcoded provider. This covers actual cloud
    providers (OpenAI, and any other OpenAI-compat cloud endpoint) *and*
    local OpenAI-compat servers (Ollama, llama.cpp's own server mode,
    vLLM, etc.) equally -- "cloud" names this code path's origin
    (decisions.md D-044, as opposed to LocalLLMBackend's in-process
    llama-cpp-python), not a hard requirement that the endpoint be remote.

    Configuration is entirely settings/env-driven
    (AURA_CLOUD_LLM_BASE_URL / AURA_CLOUD_LLM_API_KEY / AURA_CLOUD_LLM_MODEL),
    same provenance-stays-with-the-operator posture as
    LocalLLMBackend.model_path -- AURA never bundles or defaults to a
    specific vendor.

    Egress control (decisions.md D-044): before every request, the target
    host is checked against `settings.allowed_capability_hosts` via
    `orchestrator.capability_router.is_egress_host_allowed()` -- the exact
    same allowlist mechanism Phase D built for capability adapters, reused
    here rather than duplicated. `settings.enable_cloud_planner` is a
    second, separate, off-by-default gate (checked first) -- this class
    can be constructed and used directly in tests without either gate
    (callers that explicitly instantiate CloudLLMBackend are assumed to
    know what they're doing, same as LocalLLMBackend); the gates are
    enforced by `generate_spec`'s backend-resolution/escalation path, not
    inside this class's constructor.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.base_url = base_url or settings.cloud_llm_base_url
        self.api_key = api_key or settings.cloud_llm_api_key
        self.model = model or settings.cloud_llm_model
        self._client = None

    def _get_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=60.0)
        return self._client

    def generate(self, requirement_text: str) -> dict:
        from urllib.parse import urlparse

        from agents.planner.prompts import SPEC_GENERATION_SYSTEM_PROMPT, SPEC_GENERATION_USER_TEMPLATE
        from orchestrator.capability_router import is_egress_host_allowed

        if not self.base_url:
            raise CloudLLMConfigError(
                "CloudLLMBackend requires settings.cloud_llm_base_url (or "
                "AURA_CLOUD_LLM_BASE_URL / a .env entry) -- e.g. "
                "'https://api.openai.com/v1' or a local OpenAI-compat server's URL."
            )
        if not self.model:
            raise CloudLLMConfigError(
                "CloudLLMBackend requires settings.cloud_llm_model (or "
                "AURA_CLOUD_LLM_MODEL / a .env entry) -- the model name the "
                "target server expects in the request body."
            )

        host = urlparse(self.base_url).hostname
        if not is_egress_host_allowed(host):
            raise CloudLLMEgressBlockedError(
                f"CloudLLMBackend: host '{host}' (from cloud_llm_base_url) is not in "
                "settings.allowed_capability_hosts. Add it to the allowlist (or leave "
                "the allowlist unset to allow all hosts) before enabling the cloud planner."
            )

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SPEC_GENERATION_SYSTEM_PROMPT},
                {"role": "user", "content": SPEC_GENERATION_USER_TEMPLATE.format(requirement_text=requirement_text)},
            ],
            "temperature": settings.local_llm_temperature,
            "max_tokens": settings.local_llm_max_tokens,
        }

        client = self._get_client()
        from orchestrator.http_retry import post_with_retry

        response = post_with_retry(
            client, url, headers=headers, json=body,
            caller_name="CloudLLMBackend", decision_trace_category="network_retry",
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"CloudLLMBackend request to {url} failed with status {response.status_code}: "
                f"{response.text[:500]}"
            )

        response_body = response.json()
        text = response_body["choices"][0]["message"]["content"]
        return _extract_json_object(text)


class HermesAgentConfigError(RuntimeError):
    pass


class HermesAgentBackend:
    """
    Phase W (decisions.md D-047): spec generation via a real, running
    Hermes Agent instance (https://github.com/NousResearch/hermes-agent),
    through orchestrator/hermes_client.py::HermesAgentClient.

    This is distinct from CloudLLMBackend in what it buys you: CloudLLMBackend
    talks to a bare OpenAI-compatible completion endpoint (no memory, no
    tools, no skills on the far end). HermesAgentBackend talks to an actual
    Hermes Agent process, which brings its own persistent memory, skill
    recall, and (if configured) tool/MCP access -- useful if an operator is
    already running Hermes Agent for other purposes and wants AURA's
    spec-generation to benefit from it, rather than standing up a second,
    separate LLM connection.

    Off by default (settings.enable_hermes_agent); same egress-allowlist
    enforcement as CloudLLMBackend, via HermesAgentClient itself (not
    duplicated here). Selectable explicitly via
    `AURA_PLANNER_BACKEND=hermes_agent` -- deliberately NOT added to the
    local_first/cloud_first auto-detection matrix in config/settings.py,
    since "a Hermes Agent instance happens to be reachable" is a much
    weaker signal of intent than "a .gguf file was deliberately placed in
    models/" or "cloud_llm_base_url was deliberately set" -- auto-selecting
    it could silently route spec generation through a shared/multi-tenant
    Hermes instance nobody meant to involve. Escalation (generate_spec's
    settings.enable_cloud_planner fallback) is also untouched -- Hermes
    Agent is a third, independent backend a caller opts into explicitly,
    not a silent additional rung on the existing local->cloud ladder.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.base_url = base_url or settings.hermes_agent_base_url
        self.api_key = api_key or settings.hermes_agent_api_key
        self.model = model or settings.hermes_agent_model

    def generate(self, requirement_text: str) -> dict:
        from agents.planner.prompts import SPEC_GENERATION_SYSTEM_PROMPT, SPEC_GENERATION_USER_TEMPLATE
        from orchestrator.hermes_client import HermesAgentClient

        if not self.base_url:
            raise HermesAgentConfigError(
                "HermesAgentBackend requires settings.hermes_agent_base_url "
                "(or AURA_HERMES_AGENT_BASE_URL / a .env entry) -- the base "
                "URL of a running Hermes Agent API server, e.g. "
                "'http://localhost:8642' (Hermes Agent's own default "
                "API_SERVER_PORT). Start it with `hermes gateway` after "
                "setting API_SERVER_ENABLED=true/API_SERVER_KEY in "
                "~/.hermes/.env -- there is no `hermes api-server` command "
                "(see https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server)."
            )

        client = HermesAgentClient(base_url=self.base_url, api_key=self.api_key, model=self.model)
        text = client.chat(
            SPEC_GENERATION_SYSTEM_PROMPT,
            SPEC_GENERATION_USER_TEMPLATE.format(requirement_text=requirement_text),
        )
        return _extract_json_object(text)


# --------------------------------------------------------------------------
# Public entrypoint
# --------------------------------------------------------------------------

_BACKEND_REGISTRY: dict[str, type] = {
    "heuristic": LocalHeuristicBackend,
    "local_llm": LocalLLMBackend,
    "cloud_llm": CloudLLMBackend,
    "hermes_agent": HermesAgentBackend,
}


def _default_backend() -> SpecBackend:
    """Resolves settings.planner_backend ('heuristic' | 'local_llm' | 'cloud_llm') to a backend instance."""
    backend_cls = _BACKEND_REGISTRY.get(settings.planner_backend)
    if backend_cls is None:
        raise ValueError(
            f"Unknown settings.planner_backend '{settings.planner_backend}'. "
            f"Valid options: {sorted(_BACKEND_REGISTRY)}"
        )
    return backend_cls()


_logger = logging.getLogger(__name__)


def _build_grounded_text(payload: RequirementInput) -> str:
    """
    Returns the text actually sent to a backend's .generate() -- the raw
    requirement_text, or (when payload.page_context was populated by
    agents/planner/page_grounding.py) that text plus a clearly-delimited
    block of real elements found on the target page.

    Deliberately builds this here rather than mutating
    payload.requirement_text itself: RequirementInput.requirement_text
    stays the raw, human-authored doc everywhere else it's used (stored
    on TestSpec.requirement_ref indirectly via the caller, shown in
    reports, etc.) -- only the string actually handed to the backend
    gains the grounding block.

    No SpecBackend.generate() signature change needed for this -- every
    backend already takes a single requirement_text string, so this stays
    backward compatible with every existing caller/test that constructs
    or mocks a backend directly. LocalHeuristicBackend's regex patterns
    (_CLICK_PATTERNS/_TYPE_PATTERNS/_ASSERT_PATTERNS) don't match this
    block's phrasing, so it degrades harmlessly to "extra lines the
    heuristic backend ignores" there rather than corrupting its parse --
    only the LLM backends, which read the whole prompt as context, benefit
    from it today.
    """
    if not payload.page_context:
        return payload.requirement_text
    elements_block = "\n".join(f"- {name}" for name in payload.page_context)
    return (
        f"{payload.requirement_text}\n\n"
        "---\n"
        "Elements actually found on the live target page just now "
        "(real accessible names/visible text, not a guess). When a step "
        "below requires clicking or filling in something, prefer an "
        "exact or close match from this list over inventing a "
        "plausible-sounding label. If nothing in the requirement above "
        "corresponds to anything in this list, say so via the step's "
        "target_description rather than fabricating one:\n"
        f"{elements_block}"
    )


def generate_spec(payload: RequirementInput, backend: SpecBackend | None = None) -> TestSpec:
    """
    Resolves a backend and produces a schema-valid TestSpec.

    If `backend` is passed explicitly, that exact instance is used with
    R3's one-retry-with-logged-reason behavior and nothing else -- no
    escalation, matching every existing caller/test that constructs its
    own backend. `backend=None` (the normal path) additionally applies
    Phase V's escalation policy (decisions.md D-044): if the
    auto-detected/configured primary backend fails (after its own retry)
    and `settings.enable_cloud_planner` is True and the primary wasn't
    already CloudLLMBackend, one escalation attempt is made against
    CloudLLMBackend before giving up -- logged the same way R3 logs a
    retry, so "why did this escalate" is never a black box.
    """
    if backend is not None:
        return _generate_with_retry(payload, backend)

    primary = _default_backend()
    decision_trace_log.log("planner_backend", "attempt", type(primary).__name__)
    try:
        result = _generate_with_retry(payload, primary)
        decision_trace_log.log("planner_backend", "success", type(primary).__name__)
        return result
    except Exception as primary_exc:
        # Deliberately checked via settings.planner_backend rather than
        # `isinstance(primary, CloudLLMBackend)`: an isinstance check
        # against a module-global class breaks the moment a caller/test
        # patches `agents.planner.spec_generator.CloudLLMBackend` (a
        # perfectly normal way to avoid a real network call in a test) --
        # patching replaces the name with a Mock, which isinstance() can't
        # accept as its second argument. Checking the *configured* backend
        # name instead is both more robust and more semantically correct:
        # "don't escalate to cloud if cloud is already what we were
        # configured to use."
        can_escalate = settings.enable_cloud_planner and settings.planner_backend != "cloud_llm"
        if not can_escalate:
            decision_trace_log.log(
                "planner_backend", "exhausted", type(primary).__name__,
                reason=f"{type(primary_exc).__name__}: {primary_exc}",
                detail={"can_escalate": False},
            )
            raise
        _logger.warning(
            "Planner.generate_spec: escalating from %s to CloudLLMBackend after retry "
            "also failed (reason=%s: %s)",
            type(primary).__name__,
            type(primary_exc).__name__,
            primary_exc,
        )
        decision_trace_log.log(
            "planner_backend", "escalate", "CloudLLMBackend",
            reason=f"{type(primary).__name__} failed: {type(primary_exc).__name__}: {primary_exc}",
        )
        try:
            result = _generate_with_retry(payload, CloudLLMBackend())
            decision_trace_log.log("planner_backend", "success", "CloudLLMBackend", detail={"escalated_from": type(primary).__name__})
            return result
        except Exception as escalation_exc:
            _logger.warning(
                "Planner.generate_spec: escalation to CloudLLMBackend also failed "
                "(reason=%s: %s) -- falling back to the fully-offline "
                "LocalHeuristicBackend as a last resort before giving up.",
                type(escalation_exc).__name__,
                escalation_exc,
            )
            # Bug fix, reported directly from a live run: Hermes was down
            # (connection refused) and Cloud returned a transient 503 --
            # every network-capable backend failed, and this previously
            # just re-raised, crashing the entire `aura execute` run
            # (losing the scroll-test/ui-audit work already completed
            # before spec generation, since the whole command has to be
            # re-run from scratch, not just the planning step). 
            # LocalHeuristicBackend has zero network dependency, so it
            # can't fail for the same reason -- degrading to it here
            # keeps the run alive with a lower-quality, regex-extracted
            # (rather than LLM-authored) spec instead of losing the run
            # entirely. Skipped when `primary` was already
            # LocalHeuristicBackend: retrying an identical deterministic
            # regex parse that already failed would just fail again
            # identically, so there's nothing to gain by trying it a
            # second time here.
            if isinstance(primary, LocalHeuristicBackend):
                decision_trace_log.log(
                    "planner_backend", "exhausted", "CloudLLMBackend",
                    reason=f"{type(escalation_exc).__name__}: {escalation_exc}",
                    detail={"primary_was_already_heuristic": True},
                )
                raise escalation_exc
            decision_trace_log.log(
                "planner_backend", "fallback", "LocalHeuristicBackend",
                reason=f"CloudLLMBackend failed: {type(escalation_exc).__name__}: {escalation_exc}",
            )
            try:
                result = _generate_with_retry(payload, LocalHeuristicBackend())
                decision_trace_log.log(
                    "planner_backend", "success", "LocalHeuristicBackend",
                    detail={"degraded": True, "reason": "every network-capable backend failed"},
                )
                return result
            except Exception as heuristic_exc:
                _logger.error(
                    "Planner.generate_spec: fallback to LocalHeuristicBackend also "
                    "failed (%s: %s) -- no backend could produce a spec.",
                    type(heuristic_exc).__name__, heuristic_exc,
                )
                decision_trace_log.log(
                    "planner_backend", "exhausted", "LocalHeuristicBackend",
                    reason=f"{type(heuristic_exc).__name__}: {heuristic_exc}",
                    detail={"original_failure": f"{type(escalation_exc).__name__}: {escalation_exc}"},
                )
                # Re-raise the original network failure, not the heuristic
                # parse failure -- "Hermes connection refused / Cloud 503"
                # is far more actionable to a person reading the error
                # than "the regex-based fallback also produced an invalid
                # spec," and the heuristic failure is chained on as the
                # __cause__ so it's still visible in the traceback for
                # anyone who needs that detail too.
                raise escalation_exc from heuristic_exc


def _generate_with_retry(payload: RequirementInput, backend: SpecBackend) -> TestSpec:
    # Bug fix, verified by direct reproduction (not just reasoned about):
    # LocalHeuristicBackend has no LLM to interpret instructions -- it
    # only regex-scans requirement_text line by line
    # (_CLICK_PATTERNS/_TYPE_PATTERNS/_ASSERT_PATTERNS). The grounding
    # block's own instructional wording ("...type into something, prefer
    # an exact or close match...") false-matched _TYPE_PATTERNS's
    # `type...into...` pattern, and the heuristic backend generated a
    # fabricated TYPE_TEXT step straight out of AURA's own prompt text
    # rather than anything the user actually asked for -- a real crash
    # seen in production, not a hypothetical. Grounding is fed only to
    # backends that can actually read prose as *context* rather than
    # *instructions-to-parse* (every LLM-backed one) -- the heuristic
    # backend always gets the pristine original text.
    text = payload.requirement_text if isinstance(backend, LocalHeuristicBackend) else _build_grounded_text(payload)
    try:
        raw = backend.generate(text)
        return TestSpec.model_validate(raw)
    except Exception as first_exc:
        # R3 (Roadmap Phase R, decisions.md D-039): WORKFLOW.md Step 1.3's
        # one re-prompt/retry on validation failure was previously silent --
        # no record of *why* a retry happened. Log the reason (schema
        # validation error vs. an exception raised by the backend itself,
        # e.g. a timeout) so this loop is auditable rather than a black box.
        # This is a prerequisite for Phase V's escalation policy to be
        # trustworthy: an opaque retry today would just become an opaque
        # escalation later.
        _logger.warning(
            "Planner.generate_spec: retrying %s after validation/backend "
            "failure (reason=%s: %s)",
            type(backend).__name__,
            type(first_exc).__name__,
            first_exc,
        )
        raw_retry = backend.generate(text)
        return TestSpec.model_validate(raw_retry)
