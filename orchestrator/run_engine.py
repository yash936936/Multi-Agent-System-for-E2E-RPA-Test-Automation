"""
Run engine — orchestrator/run_engine.py

The actual WORKFLOW.md sequencer. Turns Phases 2-5 into one working
pipeline:

    Step 0: bootstrap (run_id, kernel, guardrail, skill_store, memory)
    Step 1: Planner.generate_spec from requirement text
    Step 2: DataSynth.generate for the spec's data_requirements
    Step 3: skill pre-check (look up a likely hint before attempting a step)
    Step 4: vision loop (capture -> Vision.execute_step per step)
    Step 5: self-healing sub-loop on escalation (orchestrator/healing_loop.py)
    Step 6: hand off to report_aggregator -> finalize RunReport

Phase 18 Update:
    - Integrated Cross-Modal Self-Healing into the CAPABILITY_CHECK branch.
    - Backend adapters (API, DB) now trigger a localized healing loop using
      the CrossModalDiagnoser before escalating to the final report.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

from agents.vision.assertions import check_assertion
from orchestrator.guardrails import LoopGuardrail
from orchestrator.healing_loop import HealingLoop
from orchestrator.kernel import OrchestratorKernel, ToolRegistry
from orchestrator.memory import RunMemoryStore
from orchestrator.report_aggregator import ReportAggregator
from orchestrator.schemas import (
    DataRequirements,
    ActionType,
    CapabilityCheckInput,
    CapabilityCheckResult,  # Phase 14/18: Updated from CapabilityResult
    RequirementInput,
    RunReport,
    SkillRecord,
    SyntheticDataRecord,
    TestSpec,
    TestStep,
    ToolCall,
    VisionActionResult,
    VisionStepInput,
)
from orchestrator.skill_store import SkillStore

ScreenshotProvider = Callable[[str, int], str]  # (run_id, step_id) -> screenshot_path


@dataclass
class RunEngineResult:
    run_id: str
    spec: TestSpec
    report: RunReport


class RunEngine:
    def __init__(
        self,
        screenshot_provider: ScreenshotProvider,
        skill_store: Optional[SkillStore] = None,
        memory: Optional[RunMemoryStore] = None,
        on_step_start: Optional[Callable[[int, TestStep], None]] = None,
        on_step_result: Optional[Callable[[int, TestStep, VisionActionResult], None]] = None,
        on_skill_learned: Optional[Callable[[int, SkillRecord], None]] = None,
    ) -> None:
        self.screenshot_provider = screenshot_provider
        self.skill_store = skill_store or SkillStore()
        self.memory = memory or RunMemoryStore()
        self.on_step_start = on_step_start
        self.on_step_result = on_step_result
        self.on_skill_learned = on_skill_learned
        self.registry = ToolRegistry().load()

    def run(self, requirement_text: str, run_id: str | None = None) -> RunEngineResult:
        run_id = run_id or str(uuid.uuid4())[:8]
        guardrail = LoopGuardrail()
        kernel = OrchestratorKernel(registry=self.registry, run_id=run_id)

        def call_tool(name: str, payload) -> Any:
            """
            Dispatches through OrchestratorKernel.call_tool() instead of
            calling the agent function directly, ensuring verbatim JSONL audit.
            """
            response = kernel.call_tool(ToolCall(name=name, arguments=payload.model_dump(mode="json")))
            if not response.ok:
                raise RuntimeError(f"tool call '{name}' failed: {response.error}")
            return self.registry.get(name).output_schema.model_validate(response.result)

        # --- Step 1: spec generation ---
        spec: TestSpec = call_tool("Planner.generate_spec", RequirementInput(requirement_text=requirement_text))
        self.memory.start_run(run_id, spec.test_id)

        # --- Step 2: synthetic data ---
        data_record: SyntheticDataRecord | None = None
        if spec.data_requirements:
            data_record = call_tool(
                "DataSynth.generate", DataRequirements(fields=spec.data_requirements, test_id=spec.test_id)
            )

        aggregator = ReportAggregator(run_id=run_id, total_steps=len(spec.steps))
        healing_loop = HealingLoop(
            guardrail=guardrail,
            skill_store=self.skill_store,
            memory=self.memory,
            diagnose_fn=lambda payload: call_tool("Planner.diagnose", payload),
            execute_step_fn=lambda payload: call_tool("Vision.execute_step", payload),
            run_id=run_id,
        )

        # Phase 18: Import Cross-Modal Diagnoser for backend healing
        from agents.planner.cross_modal_diagnoser import CrossModalDiagnoser
        cross_modal_diagnoser = CrossModalDiagnoser()
        MAX_CAPABILITY_HEALS = 2

        # --- Steps 3-5: per-step skill pre-check, vision/capability execution, healing ---
        for step in spec.steps:
            if self.on_step_start:
                self.on_step_start(step.step_id, step)

            value = None
            if step.value_ref and data_record:
                field_name = step.value_ref.split(".", 1)[-1]
                value = data_record.values.get(field_name)

            if step.action == ActionType.CAPABILITY_CHECK:
                # Phase 18 — Cross-modal self-healing for backend adapters.
                # Mirrors the vision healing loop but uses the CrossModalDiagnoser
                # to patch API/DB schema drifts before escalating.
                heal_attempts = 0
                current_step = step
                cap_result: CapabilityCheckResult | None = None

                while heal_attempts <= MAX_CAPABILITY_HEALS:
                    # Map to Phase 14 CapabilityCheckInput schema
                    capability_input = CapabilityCheckInput(
                        capability=current_step.capability_type,
                        target=current_step.target,
                        params=current_step.capability_params or {},
                        expected=current_step.expected or {}
                    )
                    
                    cap_result = call_tool("Capability.check", capability_input)
                    
                    # If passed and not escalated, we're done
                    if cap_result.passed and not cap_result.escalate:
                        break
                        
                    # If explicitly unhealable or max attempts reached, stop trying
                    if cap_result.evidence.get("unhealable") or heal_attempts == MAX_CAPABILITY_HEALS:
                        break
                        
                    # Attempt cross-modal heal
                    healed_step = cross_modal_diagnoser.diagnose(current_step, cap_result)
                    if healed_step:
                        # Persist the heal to SkillStore for future runs
                        skill_record = SkillRecord(
                            trigger=f"capability_{current_step.capability_type.value}_{current_step.target}",
                            fix=f"cross_modal_heal_{heal_attempts + 1}",
                            context={
                                "original_expected": current_step.expected,
                                "healed_expected": healed_step.expected,
                                "diagnosis": "cross_modal_schema_drift"
                            }
                        )
                        self.skill_store.add(skill_record)
                        if self.on_skill_learned:
                            self.on_skill_learned(step.step_id, skill_record)
                            
                        current_step = healed_step
                        heal_attempts += 1
                    else:
                        break  # Diagnoser couldn't find a fix

                # Construct the final VisionActionResult for the aggregator
                result = VisionActionResult(
                    step_id=step.step_id,
                    action_taken="capability_check",
                    confidence=cap_result.confidence if cap_result else 0.0,
                    escalate=not (cap_result.passed if cap_result else False),
                    assertion_passed=cap_result.passed if cap_result else False,
                    capability_result=cap_result,
                )
                
                aggregator.record_step_result(result)
                if self.on_step_result:
                    self.on_step_result(step.step_id, step, result)
                    
                if not result.escalate:
                    self.memory.mark_step_complete(run_id, step.step_id)
                continue

            # --- Vision Execution Branch (Unchanged) ---
            screenshot_path = self.screenshot_provider(run_id, step.step_id)

            # Step 3: skill pre-check
            hint = None
            target_text = step.target_description or step.field_description or ""
            if target_text:
                similar = self.skill_store.find_similar(target_text, top_k=1, min_ratio=0.6)
                if similar:
                    hint = similar[0][0]

            step_input = VisionStepInput(step=step, screenshot_path=screenshot_path, skill_hint=hint, value=value)
            result: VisionActionResult = call_tool("Vision.execute_step", step_input)

            if result.escalate:
                execution_logs = [f"step {step.step_id} escalated: confidence={result.confidence}"]
                heal_result = healing_loop.heal(
                    step=step,
                    failed_result=result,
                    screenshot_path=screenshot_path,
                    execution_logs=execution_logs,
                    value=value,
                )
                result = heal_result.final_result
                if heal_result.skill_used_or_learned is not None:
                    aggregator.record_skill_learned(heal_result.skill_used_or_learned)
                    if self.on_skill_learned:
                        self.on_skill_learned(step.step_id, heal_result.skill_used_or_learned)

            if step.expected_state and not result.escalate:
                assertion_screenshot = self.screenshot_provider(run_id, step.step_id)
                passed = check_assertion(assertion_screenshot, step.expected_state)
                result = result.model_copy(update={"assertion_passed": passed})

            aggregator.record_step_result(result)
            if self.on_step_result:
                self.on_step_result(step.step_id, step, result)

            if result.escalate:
                continue

            self.memory.mark_step_complete(run_id, step.step_id)

        # --- Final spec-level assertions ---
        if spec.assertions:
            final_step_id = len(spec.steps) + 1
            final_screenshot = self.screenshot_provider(run_id, final_step_id)
            all_passed = all(check_assertion(final_screenshot, a.expected) for a in spec.assertions)
            aggregator.record_step_result(
                VisionActionResult(
                    step_id=final_step_id,
                    action_taken="assert",
                    confidence=1.0,
                    escalate=False,
                    screenshot_ref=final_screenshot,
                    assertion_passed=all_passed,
                )
            )

        report = aggregator.finalize()
        self.memory.finish_run(run_id, report.status.value)

        return RunEngineResult(run_id=run_id, spec=spec, report=report)