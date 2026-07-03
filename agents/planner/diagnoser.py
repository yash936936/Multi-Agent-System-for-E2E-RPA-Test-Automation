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
    backend = backend or LocalHeuristicDiagnoser()
    raw = backend.diagnose(payload)
    return SkillRecord.model_validate(raw)
