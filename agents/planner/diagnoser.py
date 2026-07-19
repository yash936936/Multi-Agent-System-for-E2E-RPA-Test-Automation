"""
Diagnoser — Planner.diagnose

Analyzes a failed TestStep (plus screenshots/logs) and produces a
SkillRecord: a root-cause explanation and a proposed fix, classified as
either a `retry_strategy` (change how Vision searches/acts) or a
`spec_correction` (the TestSpec itself needs editing).

Like spec_generator.py, this ships with a deterministic offline backend
by default (DiagnosisBackend Protocol + LocalHeuristicDiagnoser) so the
whole pipeline runs without any network dependency. An LLM-backed path
can be swapped in later behind the same interface.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Protocol

from orchestrator.schemas import DiagnosisInput, FixType, SkillRecord


class DiagnosisBackend(Protocol):
    def diagnose(self, payload: DiagnosisInput) -> dict:
        """Return a dict shaped like SkillRecord (pre-validation)."""
        ...


_NOT_FOUND_HINTS = re.compile(r"\b(not found|no match|unable to locate|could not find)\b", re.IGNORECASE)
_LOW_CONFIDENCE_HINTS = re.compile(r"\b(low confidence|below threshold|ambiguous)\b", re.IGNORECASE)
_TIMEOUT_HINTS = re.compile(r"\b(timeout|timed out|did not load|still loading)\b", re.IGNORECASE)
_ASSERTION_HINTS = re.compile(r"\b(assertion failed|unexpected state|wrong screen)\b", re.IGNORECASE)


class LocalHeuristicDiagnoser:
    """
    Deterministic offline diagnosis backend. Classifies the failure by
    scanning execution_logs for known failure-pattern keywords, and
    proposes a fix template appropriate to that class. This is
    intentionally simple pattern-matching, not true reasoning — but it
    produces schema-valid, sensibly-typed SkillRecords without a model,
    which is what keeps the self-healing loop (Phase 5) runnable offline.
    """

    def diagnose(self, payload: DiagnosisInput) -> dict:
        joined_logs = " ".join(payload.execution_logs)
        target = payload.failed_step.target_description or payload.failed_step.field_description or "target element"

        if _NOT_FOUND_HINTS.search(joined_logs) or _LOW_CONFIDENCE_HINTS.search(joined_logs):
            root_cause = f"'{target}' could not be visually located with sufficient confidence — likely moved, relabeled, or restyled."
            proposed_fix = "Broaden the visual search region and retry with relaxed OCR/template matching before failing."
            fix_type = FixType.RETRY_STRATEGY
            confidence = 0.7
            signature_base = f"not_found::{self._slug(target)}"
        elif _TIMEOUT_HINTS.search(joined_logs):
            root_cause = f"Screen did not reach the expected state in time after interacting with '{target}' — likely a slow-loading UI transition."
            proposed_fix = "Insert a short wait-and-recheck before evaluating the post-action assertion."
            fix_type = FixType.RETRY_STRATEGY
            confidence = 0.65
            signature_base = f"timeout::{self._slug(target)}"
        elif _ASSERTION_HINTS.search(joined_logs):
            root_cause = f"Action on '{target}' succeeded but the resulting screen did not match expected_state — the spec's expected_state is likely stale."
            proposed_fix = f"Update the TestSpec step's expected_state to match the application's current post-action screen for '{target}'."
            fix_type = FixType.SPEC_CORRECTION
            confidence = 0.6
            signature_base = f"assertion_mismatch::{self._slug(target)}"
        else:
            root_cause = f"Step targeting '{target}' failed for an unclassified reason; logs did not match a known failure pattern."
            proposed_fix = "Escalate for human review — insufficient signal to auto-generate a fix."
            fix_type = FixType.RETRY_STRATEGY
            confidence = 0.3
            signature_base = f"unclassified::{self._slug(target)}"

        failure_signature = signature_base
        skill_id = self._make_skill_id(failure_signature)

        return {
            "skill_id": skill_id,
            "failure_signature": failure_signature,
            "root_cause": root_cause,
            "proposed_fix": proposed_fix,
            "fix_type": fix_type,
            "confidence": confidence,
            "applied_count": 0,
            "created_by": "planner_agent",
        }

    @staticmethod
    def _slug(text: str) -> str:
        return re.sub(r"\s+", "_", text.strip().lower())

    @staticmethod
    def _make_skill_id(signature: str) -> str:
        date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
        short_hash = hashlib.sha1(signature.encode()).hexdigest()[:6]
        return f"SKILL-{date_part}-{short_hash}"


def diagnose(payload: DiagnosisInput, backend: DiagnosisBackend | None = None) -> SkillRecord:
    backend = backend or _default_backend()
    raw = backend.diagnose(payload)
    return SkillRecord.model_validate(raw)


def _default_backend() -> DiagnosisBackend:
    """
    Phase X3 (decisions.md D-049): resolves settings.diagnosis_backend.
    Explicit opt-in only ("hermes_agent" must be set directly) -- no
    auto-detection matrix here, matching the conservative posture
    planner_backend="hermes_agent" already established (D-047): a
    reachable Hermes instance isn't a strong enough signal to silently
    change how failure diagnosis works. Unrecognized values fall back to
    the heuristic backend with a logged warning rather than crashing a
    self-healing pass over an unrelated config typo.
    """
    from config.settings import settings

    if settings.diagnosis_backend == "hermes_agent":
        return HermesAgentDiagnoser()
    if settings.diagnosis_backend != "heuristic":
        import logging

        logging.getLogger(__name__).warning(
            "Planner.diagnose: unrecognized settings.diagnosis_backend %r, "
            "falling back to 'heuristic'. Valid choices: 'heuristic', 'hermes_agent'.",
            settings.diagnosis_backend,
        )
    return LocalHeuristicDiagnoser()


class HermesAgentDiagnoser:
    """
    Phase X3 (decisions.md D-049): routes root-cause diagnosis through a
    real, running Hermes Agent instance (orchestrator/hermes_client.py),
    the same client Phase W's HermesAgentBackend uses for spec generation.
    Reusing that client (rather than a second implementation) means the
    egress-allowlist enforcement, auth headers, and error handling are
    identical between the two Hermes-backed paths.

    Unlike LocalHeuristicDiagnoser's keyword pattern-matching,
    this asks the model to actually reason over the failed step,
    execution logs, and (if available) a description of what changed
    between the before/after screenshots -- useful for failure modes the
    heuristic's regexes don't cover (e.g. a genuinely new failure class
    never seen before). Not a replacement for the heuristic path -- this
    is an explicit opt-in alternative (settings.diagnosis_backend =
    "hermes_agent"), and any transport/parse failure raises rather than
    silently falling back, since diagn()'s caller (the self-healing loop)
    already has its own retry/guardrail handling for backend failures
    (orchestrator/guardrails.py) -- swallowing the error here would just
    hide it one layer too early.
    """

    _SYSTEM_PROMPT = (
        "You are AURA's test-failure diagnosis assistant. You will be given "
        "a failed UI test step, its execution logs, and (if available) a "
        "network trace. Determine the most likely root cause and propose a "
        "concrete fix. Classify the fix as exactly one of two types: "
        '"retry_strategy" (Vision should search/act differently and retry '
        'the same step) or "spec_correction" (the test spec itself needs '
        "editing -- e.g. it describes a target that no longer exists). "
        'Respond with ONLY a JSON object: {"root_cause": "<one or two '
        'sentences>", "proposed_fix": "<one or two sentences, concrete>", '
        '"fix_type": "retry_strategy"|"spec_correction", "confidence": '
        '<float 0.0-1.0>}. No other text.'
    )

    _USER_TEMPLATE = (
        "Failed step target: {target}\n"
        "Step action type: {action_type}\n\n"
        "Execution logs:\n{execution_logs}\n\n"
        "Network trace: {network_trace}\n"
    )

    def __init__(self, client=None) -> None:
        self._client = client  # injectable for tests; defaults to a real HermesAgentClient below

    def _get_client(self):
        if self._client is None:
            from orchestrator.hermes_client import HermesAgentClient

            self._client = HermesAgentClient()
        return self._client

    def diagnose(self, payload: DiagnosisInput) -> dict:
        import json

        target = payload.failed_step.target_description or payload.failed_step.field_description or "target element"
        user_prompt = self._USER_TEMPLATE.format(
            target=target,
            action_type=payload.failed_step.action,
            execution_logs="\n".join(payload.execution_logs) or "(none provided)",
            network_trace=payload.network_trace or "(none provided)",
        )

        client = self._get_client()
        raw = client.chat(self._SYSTEM_PROMPT, user_prompt)
        parsed = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])

        signature_base = f"hermes_diagnosis::{LocalHeuristicDiagnoser._slug(target)}"
        return {
            "skill_id": LocalHeuristicDiagnoser._make_skill_id(signature_base),
            "failure_signature": signature_base,
            "root_cause": parsed["root_cause"],
            "proposed_fix": parsed["proposed_fix"],
            "fix_type": parsed.get("fix_type", "retry_strategy"),
            "confidence": float(parsed.get("confidence", 0.6)),
            "applied_count": 0,
            "created_by": "hermes_agent_diagnoser",
        }
