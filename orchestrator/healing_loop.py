"""
Healing loop — orchestrator/healing_loop.py

Implements WORKFLOW.md §Step 5 exactly:
  1. A Vision.execute_step call escalates (confidence below threshold, or
     not found).
  2. Planner.diagnose is called with the failed step + screenshots + logs.
  3. The resulting SkillRecord's fix_type determines what happens next:
       - retry_strategy -> retry Vision.execute_step with the skill as a hint
       - spec_correction -> the step itself can't be healed by retrying;
         record it and escalate (a human needs to edit the TestSpec)
  4. Every retry attempt is guardrail-checked. HARD_STOP -> push to the
     escalation queue (orchestrator/memory.py) and stop retrying this step.
  5. A successful heal is persisted to the skill store so future runs can
     look it up as a hint *before* even attempting the step (see
     run_engine.py's pre-check phase).
"""
from __future__ import annotations

from dataclasses import dataclass

from orchestrator.guardrails import GuardrailVerdict, LoopGuardrail, compute_evidence_fingerprint
from orchestrator.memory import RunMemoryStore
from orchestrator.schemas import (
    DiagnosisInput,
    FixType,
    SkillRecord,
    TestStep,
    VisionActionResult,
    VisionStepInput,
)
from orchestrator.skill_store import SkillStore


@dataclass
class HealResult:
    final_result: VisionActionResult
    healed: bool
    skill_used_or_learned: SkillRecord | None
    escalated: bool


class HealingLoop:
    def __init__(
        self,
        guardrail: LoopGuardrail,
        skill_store: SkillStore,
        memory: RunMemoryStore,
        diagnose_fn,
        execute_step_fn,
        run_id: str,
    ) -> None:
        """
        diagnose_fn: Callable[[DiagnosisInput], SkillRecord] — normally
            agents.planner.tool.diagnose, injected so tests can substitute
            a stub without importing the whole Planner agent.
        execute_step_fn: Callable[[VisionStepInput], VisionActionResult] —
            normally agents.vision.tool.execute_step, same reasoning.
        """
        self.guardrail = guardrail
        self.skill_store = skill_store
        self.memory = memory
        self.diagnose_fn = diagnose_fn
        self.execute_step_fn = execute_step_fn
        self.run_id = run_id

    def heal(
        self,
        step: TestStep,
        failed_result: VisionActionResult,
        screenshot_path: str,
        execution_logs: list[str],
        value: str | None = None,
    ) -> HealResult:
        current_result = failed_result

        while True:
            failure_signature = f"escalated_step_{step.step_id}_confidence_{current_result.confidence}"
            verdict = self.guardrail.record_failure(
                step_id=step.step_id, tool_name="Vision.execute_step", failure_signature=failure_signature
            )

            if verdict is GuardrailVerdict.HARD_STOP:
                self.memory.escalate(
                    run_id=self.run_id,
                    step_id=step.step_id,
                    reason="guardrail hard_stop during self-healing",
                    guardrail_snapshot=self.guardrail.state_snapshot(step.step_id),
                )
                return HealResult(final_result=current_result, healed=False, skill_used_or_learned=None, escalated=True)

            # AD2 (docs/decisions.md D-062): compare this attempt's AA1
            # verification evidence against the previous attempt's. If
            # they're byte-identical, the previous diagnosis+retry made
            # zero measurable difference to the screen -- short-circuit
            # straight to HARD_STOP rather than burning through the
            # remaining count-based threshold budget on further retries
            # that are provably as pointless as this one was.
            evidence_fingerprint = compute_evidence_fingerprint(current_result.verification_source, current_result.raw_evidence)
            evidence_verdict = self.guardrail.record_evidence(
                step_id=step.step_id, tool_name="Vision.execute_step", evidence_fingerprint=evidence_fingerprint
            )
            if evidence_verdict is GuardrailVerdict.HARD_STOP:
                self.memory.escalate(
                    run_id=self.run_id,
                    step_id=step.step_id,
                    reason="guardrail hard_stop: retry produced evidence identical to the previous attempt (AD2 short-circuit)",
                    guardrail_snapshot=self.guardrail.state_snapshot(step.step_id),
                )
                return HealResult(final_result=current_result, healed=False, skill_used_or_learned=None, escalated=True)

            diagnosis = self.diagnose_fn(
                DiagnosisInput(
                    failed_step=step,
                    before_screenshot=screenshot_path,
                    after_screenshot=screenshot_path,
                    execution_logs=execution_logs,
                )
            )

            if diagnosis.fix_type == FixType.SPEC_CORRECTION:
                # Can't self-heal by retrying vision; needs a human to edit
                # the TestSpec. Persist the diagnosis as a skill anyway (it's
                # useful context for whoever reviews it) but stop retrying.
                self.skill_store.save(diagnosis)
                self.memory.escalate(
                    run_id=self.run_id,
                    step_id=step.step_id,
                    reason=f"spec_correction needed: {diagnosis.root_cause}",
                    guardrail_snapshot=self.guardrail.state_snapshot(step.step_id),
                )
                return HealResult(final_result=current_result, healed=False, skill_used_or_learned=diagnosis, escalated=True)

            # retry_strategy: retry Vision.execute_step with the skill as a hint
            retry_payload = VisionStepInput(
                step=step,
                screenshot_path=screenshot_path,
                skill_hint=diagnosis,
                value=value,
            )
            retry_result = self.execute_step_fn(retry_payload)

            if not retry_result.escalate:
                # healed
                self.skill_store.save(diagnosis)
                self.skill_store.increment_applied(diagnosis.skill_id)
                self.guardrail.reset(step.step_id)
                return HealResult(final_result=retry_result, healed=True, skill_used_or_learned=diagnosis, escalated=False)

            # still failing -> loop again (guardrail will eventually hard_stop)
            current_result = retry_result
            execution_logs = execution_logs + [f"retry with skill {diagnosis.skill_id} still escalated"]
