"""
Loop guardrails — TRD.md §5.4.

Tracks two failure signals per test-step retry loop:
  - exact_failure: the identical error occurred again (same failure_signature)
  - same_tool_failure: the same tool failed again, regardless of error identity
  - idempotent_no_progress: tool succeeded (no error) but state didn't change

Returns one of: CONTINUE / WARN / HARD_STOP, per the warn_after /
hard_stop_after thresholds in config/settings.py::GuardrailSettings.

This is deliberately independent of any specific LLM/agent framework so it
can be dropped in as-is if the project ever swaps the orchestration layer
(see decisions.md D-006).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from config.settings import GuardrailSettings, settings


class GuardrailVerdict(str, Enum):
    CONTINUE = "continue"
    WARN = "warn"
    HARD_STOP = "hard_stop"


def compute_evidence_fingerprint(verification_source: Optional[str], raw_evidence: Optional[dict[str, Any]]) -> Optional[str]:
    """
    AD2 (docs/decisions.md D-062) -- the "trace-comparison plumbing"
    D-057/D-060 both flagged as AD2's real dependency: a stable
    fingerprint of AA1's own audit fields (`verification_source`,
    `raw_evidence` -- see `VisionActionResult` in orchestrator/schemas.py),
    so two retry attempts can be compared on what was actually observed
    (OCR text found, DOM snapshot hash, adapter response), not just on a
    coarse proxy like confidence score or a hand-built failure-signature
    string.

    Returns None when `raw_evidence` itself is None -- i.e. no
    verification ran for this step at all (a bare SCROLL/NAVIGATE_URL
    with no expected_state, matching AA1's own "None is only valid when
    no verification was applicable" convention). None deliberately means
    "nothing to compare," not "identical to everything" -- callers must
    never short-circuit on two None fingerprints.
    """
    if raw_evidence is None:
        return None
    payload = {"verification_source": verification_source, "raw_evidence": raw_evidence}
    normalized = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class StepLoopState:
    """Per-step retry bookkeeping. One instance per (run_id, step_id)."""

    exact_failure_count: int = 0
    same_tool_failure_count: int = 0
    no_progress_count: int = 0
    last_failure_signature: str | None = None
    last_tool_name: str | None = None
    warned: bool = False
    # AD2 -- the previous attempt's evidence fingerprint for this step,
    # used by record_evidence() below to detect a retry that produced
    # literally the same raw evidence as the attempt before it.
    last_evidence_fingerprint: str | None = None
    identical_evidence_short_circuited: bool = False


class LoopGuardrail:
    """
    Stateful guardrail evaluator for a single run.

    Usage:
        g = LoopGuardrail()
        verdict = g.record_failure(step_id=3, tool_name="Vision.execute_step",
                                    failure_signature="login_button_not_found")
        if verdict is GuardrailVerdict.HARD_STOP:
            ...escalate...

    Phase J concurrency note (decisions.md D-031): `self._states` is keyed
    by `step_id` alone, not `(run_id, step_id)`. This was flagged as a
    risk in the Phase G-M roadmap's original Phase J plan, but on review
    it is *not* a live bug: `orchestrator/run_engine.py::run_spec()`
    constructs a brand-new `LoopGuardrail()` as a local variable on every
    call and never shares one instance across two concurrent `run_spec()`
    invocations (there is no module-level or `RunEngine.self`-level
    guardrail instance). So a `step_id`-only key is safe today because
    each run already gets its own isolated `LoopGuardrail`. This is called
    out explicitly rather than silently reworking the key, per
    docs/debug.md's "verify, don't assume" rule -- if a future change ever
    makes `RunEngine` share one `LoopGuardrail` across calls (e.g. to
    track guardrail state across runs), this key must be revisited to
    `(run_id, step_id)` at that point, not before.
    """

    def __init__(self, config: GuardrailSettings | None = None) -> None:
        self.config = config or settings.guardrails
        self._states: dict[int, StepLoopState] = {}

    def _state_for(self, step_id: int) -> StepLoopState:
        return self._states.setdefault(step_id, StepLoopState())

    def reset(self, step_id: int) -> None:
        """Call when a step finally succeeds — clears its retry history."""
        self._states.pop(step_id, None)

    def record_evidence(self, step_id: int, tool_name: str, evidence_fingerprint: str | None) -> GuardrailVerdict:
        """
        AD2 (docs/decisions.md D-062). Call once per retry attempt with
        `compute_evidence_fingerprint()`'s output for that attempt's
        `VisionActionResult`. If this fingerprint is byte-identical to
        the immediately preceding attempt's fingerprint for the same
        step -- i.e. the retry observed literally the same OCR/DOM/
        adapter evidence as before, meaning the diagnosis+retry made
        zero measurable difference to the screen -- this short-circuits
        straight to HARD_STOP, bypassing exact_failure_count/
        same_tool_failure_count's thresholds entirely (per
        `GuardrailSettings.short_circuit_on_identical_evidence`, on by
        default). A count-based threshold answers "how many times has
        this failed," which can still tolerate a few more attempts even
        when the *evidence itself* already proves further retries are
        pointless -- exactly the D-055 incident this exists to close
        (three identical-result retries before the count-based
        hard_stop finally fired).

        `evidence_fingerprint=None` (no verification ran for this
        attempt) always returns CONTINUE without touching stored state
        -- there's nothing to compare, and a run of None values must
        never be treated as "identical" to each other.
        """
        st = self._state_for(step_id)
        st.last_tool_name = tool_name

        if evidence_fingerprint is None:
            return GuardrailVerdict.CONTINUE

        if (
            self.config.short_circuit_on_identical_evidence
            and st.last_evidence_fingerprint is not None
            and evidence_fingerprint == st.last_evidence_fingerprint
        ):
            st.identical_evidence_short_circuited = True
            return GuardrailVerdict.HARD_STOP

        st.last_evidence_fingerprint = evidence_fingerprint
        return GuardrailVerdict.CONTINUE

    def record_failure(
        self,
        step_id: int,
        tool_name: str,
        failure_signature: str,
    ) -> GuardrailVerdict:
        st = self._state_for(step_id)

        # exact-failure tracking (identical signature repeats)
        if failure_signature == st.last_failure_signature:
            st.exact_failure_count += 1
        else:
            st.exact_failure_count = 1
            st.last_failure_signature = failure_signature

        # same-tool-failure tracking (same tool fails again, any reason)
        if tool_name == st.last_tool_name:
            st.same_tool_failure_count += 1
        else:
            st.same_tool_failure_count = 1
            st.last_tool_name = tool_name

        return self._evaluate(st)

    def record_no_progress(self, step_id: int, tool_name: str) -> GuardrailVerdict:
        """Tool call succeeded (no error) but the observed state didn't change."""
        st = self._state_for(step_id)
        st.no_progress_count += 1
        st.last_tool_name = tool_name
        return self._evaluate(st)

    def _evaluate(self, st: StepLoopState) -> GuardrailVerdict:
        cfg = self.config

        if cfg.hard_stop_enabled and (
            st.exact_failure_count >= cfg.hard_stop_after_exact_failure
            or st.same_tool_failure_count >= cfg.hard_stop_after_same_tool_failure
        ):
            return GuardrailVerdict.HARD_STOP

        if cfg.warnings_enabled and (
            st.exact_failure_count >= cfg.warn_after_exact_failure
            or st.same_tool_failure_count >= cfg.warn_after_same_tool_failure
            or st.no_progress_count >= cfg.warn_after_idempotent_no_progress
        ):
            st.warned = True
            return GuardrailVerdict.WARN

        return GuardrailVerdict.CONTINUE

    def state_snapshot(self, step_id: int) -> dict:
        st = self._state_for(step_id)
        return {
            "exact_failure_count": st.exact_failure_count,
            "same_tool_failure_count": st.same_tool_failure_count,
            "no_progress_count": st.no_progress_count,
            "warned": st.warned,
            "identical_evidence_short_circuited": st.identical_evidence_short_circuited,
        }
