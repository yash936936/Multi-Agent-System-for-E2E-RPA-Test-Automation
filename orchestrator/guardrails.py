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

from dataclasses import dataclass
from enum import Enum

from config.settings import GuardrailSettings, settings


class GuardrailVerdict(str, Enum):
    CONTINUE = "continue"
    WARN = "warn"
    HARD_STOP = "hard_stop"


@dataclass
class StepLoopState:
    """Per-step retry bookkeeping. One instance per (run_id, step_id)."""

    exact_failure_count: int = 0
    same_tool_failure_count: int = 0
    no_progress_count: int = 0
    last_failure_signature: str | None = None
    last_tool_name: str | None = None
    warned: bool = False


class LoopGuardrail:
    """
    Stateful guardrail evaluator for a single run.

    Usage:
        g = LoopGuardrail()
        verdict = g.record_failure(step_id=3, tool_name="Vision.execute_step",
                                    failure_signature="login_button_not_found")
        if verdict is GuardrailVerdict.HARD_STOP:
            ...escalate...
    """

    def __init__(self, config: GuardrailSettings | None = None) -> None:
        self.config = config or settings.guardrails
        self._states: dict[int, StepLoopState] = {}

    def _state_for(self, step_id: int) -> StepLoopState:
        return self._states.setdefault(step_id, StepLoopState())

    def reset(self, step_id: int) -> None:
        """Call when a step finally succeeds — clears its retry history."""
        self._states.pop(step_id, None)

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
        }
