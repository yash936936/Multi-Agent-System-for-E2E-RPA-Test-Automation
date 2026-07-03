"""
Spec generator — Planner.generate_spec

Converts normalized requirement text into a schema-valid TestSpec
(orchestrator/schemas.py). Backend is pluggable:

  - LocalHeuristicBackend (default): pure-Python sentence-pattern parser.
    No network call, no model weights — matches decisions.md D-002
    (fully offline) and D-004 (agents defined by contract, not by a
    specific model). This is what actually runs in this sandbox.

  - AnthropicBackend (optional, off by default): if the caller sets
    settings.allow_network_calls = True and an API key is available,
    spec generation can be delegated to a real LLM using the prompts in
    prompts.py. Not used unless explicitly enabled — kept here so the
    architecture is swappable per D-004/D-006 without changing the tool
    contract.

Either backend must return data that validates against TestSpec; if it
doesn't, generate_spec re-prompts once (WORKFLOW.md Step 1.3) before
raising.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Protocol

from config.settings import settings
from orchestrator.schemas import (
    ActionType,
    AssertionType,
    RequirementInput,
    TestSpec,
    TestStep,
)


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
_NAVIGATE_PATTERNS = [
    re.compile(r"\bnavigate(?:s|d)?\s+to\s+(https?://\S+)", re.IGNORECASE),
    re.compile(r"\bgo(?:es|ing)?\s+to\s+(https?://\S+)", re.IGNORECASE),
    re.compile(r"\bopen(?:s|ed|ing)?\s+(?:the\s+(?:browser|site|page|url)\s+(?:at|to)\s+)?(https?://\S+)", re.IGNORECASE),
    re.compile(r"browser\s+is\s+open\s+at\s+(https?://\S+)", re.IGNORECASE),
    re.compile(r"\btarget[\s_-]?url\s*:?\s*(https?://\S+)", re.IGNORECASE),
]
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
        if nav_url:
            steps = self._prepend_navigate_step(steps, nav_url)
        assertions = self._extract_assertions(lines)
        data_requirements = self._extract_data_requirements(requirement_text)

        return {
            "test_id": test_id,
            "requirement_ref": test_id,
            "preconditions": preconditions,
            "steps": [s.model_dump() for s in steps] if steps and isinstance(steps[0], TestStep) else steps,
            "assertions": assertions,
            "data_requirements": data_requirements,
        }

    def _infer_test_id(self, text: str) -> str:
        heading_match = re.search(r"^#+\s*(.+)$", text, re.MULTILINE)
        base = heading_match.group(1) if heading_match else "GENERATED"
        slug = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").upper()
        slug = slug[:24] if slug else "FLOW"
        return f"TC-{slug}-001"

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
        for pattern in _NAVIGATE_PATTERNS:
            m = pattern.search(text)
            if m:
                return m.group(1).rstrip(').,;"\'')
        return None

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
            for pattern in _ASSERT_PATTERNS:
                m = pattern.search(line)
                if m:
                    out.append({"type": AssertionType.VISUAL_STATE.value, "expected": self._slug(m.group(1))})
        return out

    def _extract_data_requirements(self, text: str) -> list[str]:
        fields = {m.lower().replace(" ", "_") for m in _DATA_FIELD_HINTS.findall(text)}
        edge_cases = {f"edge_case_{m.lower().replace(' ', '_')}" for m in _EDGE_CASE_HINTS.findall(text)}
        return sorted(fields | edge_cases)

    @staticmethod
    def _slug(text: str) -> str:
        return re.sub(r"\s+", "_", text.strip().lower())


# --------------------------------------------------------------------------
# Optional network-backed LLM backend (off by default, D-002/D-004/D-006)
# --------------------------------------------------------------------------

class AnthropicBackend:
    """
    Delegates spec generation to a real LLM via the Anthropic API using the
    prompts in prompts.py. Disabled unless settings.allow_network_calls is
    explicitly set True by the caller — the default offline posture
    (decisions.md D-002) must be an opt-in override, never silent.
    """

    def __init__(self, model: str = "claude-sonnet-4-6") -> None:
        self.model = model

    def generate(self, requirement_text: str) -> dict:
        if not settings.allow_network_calls:
            raise RuntimeError(
                "AnthropicBackend requires settings.allow_network_calls=True. "
                "AURA defaults to fully offline operation (decisions.md D-002)."
            )
        import anthropic  # local import: optional dependency, only needed if this path is used

        from agents.planner.prompts import SPEC_GENERATION_SYSTEM_PROMPT, SPEC_GENERATION_USER_TEMPLATE

        client = anthropic.Anthropic()
        response = client.messages.create(
            model=self.model,
            max_tokens=2000,
            system=SPEC_GENERATION_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": SPEC_GENERATION_USER_TEMPLATE.format(requirement_text=requirement_text)}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return json.loads(text)


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
    compatible with the offline guarantee in decisions.md D-002 -- unlike
    AnthropicBackend above, which needs settings.allow_network_calls=True.

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
# Public entrypoint
# --------------------------------------------------------------------------

_BACKEND_REGISTRY: dict[str, type] = {
    "heuristic": LocalHeuristicBackend,
    "local_llm": LocalLLMBackend,
    "anthropic": AnthropicBackend,
}


def _default_backend() -> SpecBackend:
    """Resolves settings.planner_backend ('heuristic' | 'local_llm' | 'anthropic') to a backend instance."""
    backend_cls = _BACKEND_REGISTRY.get(settings.planner_backend)
    if backend_cls is None:
        raise ValueError(
            f"Unknown settings.planner_backend '{settings.planner_backend}'. "
            f"Valid options: {sorted(_BACKEND_REGISTRY)}"
        )
    return backend_cls()


def generate_spec(payload: RequirementInput, backend: SpecBackend | None = None) -> TestSpec:
    backend = backend or _default_backend()

    raw = backend.generate(payload.requirement_text)
    try:
        return TestSpec.model_validate(raw)
    except Exception:
        # WORKFLOW.md Step 1.3: one re-prompt/retry on validation failure.
        raw_retry = backend.generate(payload.requirement_text)
        return TestSpec.model_validate(raw_retry)
