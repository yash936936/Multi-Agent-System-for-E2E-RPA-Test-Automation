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

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from agents.auditor import run_monitor
from agents.vision.assertions import check_assertion_detailed
from orchestrator.assertion_audit_log import assertion_audit_log
from agents.vision.visual_regression import compare_to_baseline
from config.settings import settings

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
    CapabilityType,
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
from orchestrator.spec_validator import SpecValidationIssue, validate_spec_or_raise
from runtime.hooks.capture import file_hash

ScreenshotProvider = Callable[[str, int], str]  # (run_id, step_id) -> screenshot_path


@dataclass
class RunEngineResult:
    run_id: str
    spec: TestSpec
    report: RunReport
    # Phase T: non-blocking action/target-type mismatch warnings found by
    # spec_validator.py's heuristic check. Empty list in the overwhelming
    # common case (no mismatch found) -- populated only when something
    # looked suspicious enough to flag, never fatal on its own.
    validation_warnings: list[SpecValidationIssue] = field(default_factory=list)


class RunEngine:
    def __init__(
        self,
        screenshot_provider: ScreenshotProvider,
        skill_store: Optional[SkillStore] = None,
        memory: Optional[RunMemoryStore] = None,
        on_step_start: Optional[Callable[[int, TestStep], None]] = None,
        on_step_result: Optional[Callable[[int, TestStep, VisionActionResult], None]] = None,
        on_skill_learned: Optional[Callable[[int, SkillRecord], None]] = None,
        on_waiting_for_human: Optional[Callable[[int, TestStep, float], None]] = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.screenshot_provider = screenshot_provider
        self.skill_store = skill_store or SkillStore()
        self.memory = memory or RunMemoryStore()
        self.on_step_start = on_step_start
        self.on_step_result = on_step_result
        self.on_skill_learned = on_skill_learned
        # Interactive mode: called on every poll tick of a
        # WAIT_FOR_HUMAN_ACTION step (step_id, step, seconds_elapsed) so a
        # CLI can render "waiting for you to click X... (12s)" without the
        # engine itself knowing anything about terminals.
        self.on_waiting_for_human = on_waiting_for_human
        self._sleep = sleep_fn
        self.registry = ToolRegistry().load()

    def _safe_screenshot(self, run_id: str, step_id: int) -> str | None:
        """
        Wraps self.screenshot_provider so a missing display (NoDisplayError,
        raised by runtime/hooks/capture.py when mss/the OS display isn't
        available -- e.g. any headless CI/sandbox environment) turns into a
        clean `None` instead of an uncaught traceback that kills the whole
        run. Every other real action path in this pipeline (agents/vision/
        executor.py's click/type/navigate) already catches this and
        escalates gracefully -- this makes the screenshot capture that
        happens just before dispatching to the vision executor behave the
        same way, instead of being the one place that crashes.
        """
        from runtime.errors import display_guard

        with display_guard() as guard:
            guard.value = self.screenshot_provider(run_id, step_id)
        return None if guard.no_display else guard.value

    def _enforce_bot_validation_cross_check(self, spec: TestSpec, aggregator: ReportAggregator) -> None:
        """
        TRD §11.6 / Roadmap Phase 21c: "no blind trust of bot-reported
        success." Groups every CAPABILITY_CHECK step sharing a non-null
        `bot_validation_group` into one logical trigger-and-verify unit
        (docs/TRD.md §11's diagram: trigger -> Web App/Database/Files
        validation legs -> "Playwright Validates" aggregation point) and
        retroactively corrects the trigger step's own result if the bot
        reported success but none of its grouped validation legs
        independently confirmed the expected end state.

        Runs once, after every step in the spec has already executed and
        been recorded -- by spec convention (matching the diagram's
        top-to-bottom flow) the trigger step is expected to come before its
        validation-leg steps, so by the time this runs every result needed
        is already available in the aggregator.
        """
        results_by_step_id = {r.step_id: r for r in aggregator.get_results()}
        groups: dict[str, dict[str, Any]] = {}

        for step in spec.steps:
            group = getattr(step, "bot_validation_group", None)
            if not group:
                continue
            result = results_by_step_id.get(step.step_id)
            if result is None or result.capability_result is None:
                continue

            entry = groups.setdefault(group, {"trigger": None, "validations": []})
            cap_type = result.capability_result.capability
            if cap_type == CapabilityType.AUTOMATION_ANYWHERE:
                entry["trigger"] = (step, result)
            elif cap_type in (
                CapabilityType.WEB_VALIDATION,
                CapabilityType.DATABASE,
                CapabilityType.FILE_SYSTEM,
            ):
                entry["validations"].append((step, result))

        for group_name, entry in groups.items():
            trigger = entry["trigger"]
            if trigger is None:
                # A validation-leg step tagged with a group that has no
                # matching trigger step in this spec -- nothing to enforce.
                continue

            trigger_step, trigger_result = trigger
            if not trigger_result.capability_result.passed:
                # The bot itself already failed/timed out -- already
                # correctly reflected (escalate=True) from the normal
                # CAPABILITY_CHECK branch above; nothing more to add.
                continue

            validations = entry["validations"]
            any_confirmed = any(
                v_result.capability_result is not None and v_result.capability_result.passed
                for _, v_result in validations
            )

            if any_confirmed:
                continue  # bot succeeded AND at least one leg independently confirmed it -- genuinely passed.

            if not validations:
                reason = (
                    f"bot_validation_group '{group_name}' has a trigger step but no "
                    "validation-leg steps (web_validation/database/file_system) were found "
                    "in this spec to independently confirm it -- per TRD §11.6, a bot's own "
                    "reported success is never sufficient alone."
                )
            else:
                reason = (
                    f"bot_validation_group '{group_name}': the Automation Anywhere bot reported "
                    "success, but none of the grouped validation-leg steps independently "
                    "confirmed the expected end state (TRD §11.6 -- 'no blind trust of "
                    "bot-reported success')."
                )

            corrected_evidence = dict(trigger_result.capability_result.evidence)
            corrected_evidence["cross_check_failed"] = reason
            corrected_cap_result = trigger_result.capability_result.model_copy(
                update={"passed": False, "evidence": corrected_evidence}
            )
            corrected = trigger_result.model_copy(
                update={
                    "assertion_passed": False,
                    "escalate": True,
                    "capability_result": corrected_cap_result,
                }
            )
            aggregator.override_step_result(trigger_step.step_id, corrected)
            if self.on_step_result:
                self.on_step_result(trigger_step.step_id, trigger_step, corrected)

    def run(self, requirement_text: str, run_id: str | None = None, keep_browser_open: bool = False, continuous_audit: bool | None = None) -> RunEngineResult:
        run_id = run_id or str(uuid.uuid4())[:8]
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

        # --- Step 2: synthetic data ---
        data_record: SyntheticDataRecord | None = None
        if spec.data_requirements:
            data_record = call_tool(
                "DataSynth.generate", DataRequirements(fields=spec.data_requirements, test_id=spec.test_id)
            )

        return self.run_spec(
            spec,
            run_id=run_id,
            data_record=data_record,
            kernel=kernel,
            call_tool=call_tool,
            requirement_text=requirement_text,
            keep_browser_open=keep_browser_open,
            continuous_audit=continuous_audit,
        )

    def run_spec(
        self,
        spec: TestSpec,
        run_id: str | None = None,
        data_record: Optional[SyntheticDataRecord] = None,
        kernel: Optional[OrchestratorKernel] = None,
        call_tool: Optional[Callable[[str, Any], Any]] = None,
        requirement_text: str | None = None,
        keep_browser_open: bool = False,
        continuous_audit: bool | None = None,
    ) -> RunEngineResult:
        """
        Executes an already-built TestSpec directly, skipping Planner
        entirely. This is `run()`'s actual execution loop, split out so
        `aura explore` and `--interactive` mode can hand-assemble a spec
        (e.g. a single WAIT_FOR_HUMAN_ACTION step from a typed instruction)
        without needing the heuristic/LLM planner to understand it first.

        `requirement_text`: the original plain-English request, for
        RunReport.request_text (report-detail pass). Note
        TestSpec.requirement_ref is a test-id-style slug (see
        agents/planner/spec_generator.py), not the original text, so
        callers with the real text (run(), below) should pass it
        explicitly; callers without it (aura explore/--interactive
        hand-assembling a spec with no separate original request string)
        fall back to spec.requirement_ref, which is still more useful
        than an empty string even though it's a slug.

        `continuous_audit`: None (default) defers to
        settings.enable_continuous_audit; True/False overrides it for this
        run only (e.g. a CLI `--continuous-audit` flag). See
        agents/auditor/run_monitor.py.
        """
        run_id = run_id or str(uuid.uuid4())[:8]
        do_continuous_audit = settings.enable_continuous_audit if continuous_audit is None else continuous_audit
        guardrail = LoopGuardrail()
        if kernel is None:
            kernel = OrchestratorKernel(registry=self.registry, run_id=run_id)
        if call_tool is None:
            def call_tool(name: str, payload) -> Any:
                response = kernel.call_tool(ToolCall(name=name, arguments=payload.model_dump(mode="json")))
                if not response.ok:
                    raise RuntimeError(f"tool call '{name}' failed: {response.error}")
                return self.registry.get(name).output_schema.model_validate(response.result)

        # Phase T: validate the whole spec before touching memory/the
        # aggregator/any screenshot. An error-severity issue raises
        # SpecValidationError right here -- nothing has started yet, so
        # there's nothing to half-record or clean up. Warnings (the
        # action/target-type mismatch heuristic) never block; they're
        # carried through to the final RunEngineResult instead.
        validation_warnings = validate_spec_or_raise(spec)

        self.memory.start_run(run_id, spec.test_id)

        aggregator = ReportAggregator(run_id=run_id, total_steps=len(spec.steps))
        slideshow_recorder = None
        if settings.record_video:
            from runtime.hooks.video_recorder import SlideshowRecorder

            slideshow_recorder = SlideshowRecorder()
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

                    # Same-class bug fix as Phase 3 (next-phase plan) applied
                    # to the vision path's _resolve_dom(): most capability
                    # adapters already catch their own transport errors
                    # (e.g. agents/capability/api_adapter.py's broad
                    # `except Exception` around its httpx call), but nothing
                    # here guaranteed that -- a new or incompletely-guarded
                    # adapter raising anything at all propagates uncaught
                    # through orchestrator/kernel.py's call_tool (re-wrapped
                    # as a failed ToolResponse) and back out as a
                    # RuntimeError from this file's own call_tool closure,
                    # crashing the entire run instead of the same
                    # "escalate this one step, keep going" behavior a
                    # deliberate cap_result.escalate=True already gets.
                    # Verified by direct reproduction (a stub adapter that
                    # raises a plain Exception) before and after this fix.
                    try:
                        cap_result = call_tool("Capability.check", capability_input)
                    except RuntimeError as e:
                        cap_result = CapabilityCheckResult(
                            capability=current_step.capability_type,
                            passed=False,
                            confidence=0.0,
                            evidence={"unhealable": True, "adapter_error": str(e)},
                            escalate=True,
                        )
                        break
                    
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

                # Construct the final VisionActionResult for the aggregator.
                # escalate reflects the adapter's own uncertainty signal
                # (cap_result.escalate), not just "did it fail" -- a
                # capability like LINK_CHECK is fully deterministic (a real
                # HTTP status code, not a fuzzy vision confidence score), so
                # a broken link is a clean, decisive assertion_passed=False
                # ("flag it, show it in the report") rather than an
                # ambiguous "escalated, needs human review."
                result = VisionActionResult(
                    step_id=step.step_id,
                    action_taken="capability_check",
                    confidence=cap_result.confidence if cap_result else 0.0,
                    escalate=cap_result.escalate if cap_result else True,
                    assertion_passed=cap_result.passed if cap_result else False,
                    capability_result=cap_result,
                )
                
                aggregator.record_step_result(result)
                if self.on_step_result:
                    self.on_step_result(step.step_id, step, result)
                    
                if not result.escalate:
                    self.memory.mark_step_complete(run_id, step.step_id)
                continue

            if step.action == ActionType.WAIT_FOR_HUMAN_ACTION:
                # Human-in-the-loop: no autonomous action here. Poll the
                # live screen (same screenshot_provider as everything else
                # -- it's a real capture in a live run, a fixture in tests)
                # until it changes, then verify. This does NOT time out by
                # default (human_action_timeout_seconds = 0) because the
                # whole point of this mode is "wait for a person," not
                # "wait up to N seconds and give up."
                timeout = (
                    step.human_action_timeout_seconds
                    if step.human_action_timeout_seconds is not None
                    else settings.human_action_timeout_seconds
                )
                poll_interval = settings.human_action_poll_interval_seconds

                baseline_path = self._safe_screenshot(run_id, step.step_id)
                if baseline_path is None:
                    result = VisionActionResult(
                        step_id=step.step_id,
                        action_taken="wait_for_human",
                        confidence=0.0,
                        escalate=True,
                        assertion_passed=False,
                    )
                    aggregator.record_step_result(result)
                    if self.on_step_result:
                        self.on_step_result(step.step_id, step, result)
                    continue
                baseline_hash = file_hash(baseline_path)

                elapsed = 0.0
                changed = False
                latest_path = baseline_path
                while True:
                    if self.on_waiting_for_human:
                        self.on_waiting_for_human(step.step_id, step, elapsed)
                    self._sleep(poll_interval)
                    elapsed += poll_interval

                    latest_path = self._safe_screenshot(run_id, step.step_id)
                    if latest_path is None:
                        # Display disappeared mid-poll -- stop waiting on
                        # something we can no longer observe rather than
                        # crashing on file_hash(None).
                        latest_path = baseline_path
                        break
                    if file_hash(latest_path) != baseline_hash:
                        changed = True
                        break
                    if timeout and elapsed >= timeout:
                        break

                assertion_detail = None
                if changed and step.expected_state:
                    assertion_detail = check_assertion_detailed(latest_path, step.expected_state)
                    passed = assertion_detail["passed"]
                    assertion_audit_log.log(
                        run_id=run_id, step_id=step.step_id, expected_state=step.expected_state,
                        detail=assertion_detail, escalate=not passed,
                    )
                elif changed:
                    # No specific expected_state given -- the instruction
                    # was just "do the thing," and something visibly did
                    # happen, so treat that as success rather than
                    # guessing at an assertion that was never specified.
                    passed = True
                else:
                    passed = False

                result = VisionActionResult(
                    step_id=step.step_id,
                    action_taken="wait_for_human",
                    confidence=1.0 if changed else 0.0,
                    escalate=not passed,
                    screenshot_ref=latest_path,
                    assertion_passed=passed if changed else None,
                    verification_source="ocr" if assertion_detail is not None else "none_required",
                    raw_evidence=assertion_detail,
                    human_action_evidence={
                        "elapsed_seconds": round(elapsed, 2),
                        "timeout_seconds": timeout,
                        "timed_out": bool(timeout) and not changed and elapsed >= timeout,
                        "screen_changed": changed,
                        "expected_state": step.expected_state,
                        "baseline_screenshot_ref": baseline_path,
                        # Whether the person's action alone was accepted as
                        # sufficient (no expected_state to check against) or
                        # was actually verified against a stated expectation --
                        # the report needs to be able to say which one
                        # happened, not just "passed."
                        "acceptance_basis": (
                            "verified_against_expected_state" if changed and step.expected_state
                            else "screen_change_accepted_no_expected_state" if changed
                            else "no_screen_change_detected"
                        ),
                    },
                )

                aggregator.record_step_result(result)
                if self.on_step_result:
                    self.on_step_result(step.step_id, step, result)

                if not result.escalate:
                    self.memory.mark_step_complete(run_id, step.step_id)
                continue

            # --- Vision Execution Branch ---
            screenshot_path = self._safe_screenshot(run_id, step.step_id)
            if screenshot_path is None:
                # No display available (headless/no-display environment) --
                # every other action path here (click/type/navigate in
                # agents/vision/executor.py) already escalates gracefully on
                # this exact condition instead of crashing; this makes the
                # screenshot capture consistent with that instead of taking
                # the whole run down with an uncaught NoDisplayError.
                result = VisionActionResult(
                    step_id=step.step_id,
                    action_taken="none",
                    confidence=0.0,
                    escalate=True,
                    assertion_passed=False,
                )
                aggregator.record_step_result(result)
                if self.on_step_result:
                    self.on_step_result(step.step_id, step, result)
                continue

            if slideshow_recorder is not None:
                slideshow_recorder.add_frame(screenshot_path, step.step_id)

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
                assertion_screenshot = self._safe_screenshot(run_id, step.step_id)
                if assertion_screenshot is None:
                    result = result.model_copy(update={
                        "assertion_passed": False,
                        "escalate": True,
                        "verification_source": "ocr",
                        "raw_evidence": {"error": "screenshot capture failed"},
                    })
                else:
                    detail = check_assertion_detailed(assertion_screenshot, step.expected_state)
                    result = result.model_copy(update={
                        "assertion_passed": detail["passed"],
                        "verification_source": "ocr",
                        "raw_evidence": detail,
                    })
                    assertion_audit_log.log(
                        run_id=run_id, step_id=step.step_id, expected_state=step.expected_state,
                        detail=detail, escalate=result.escalate,
                    )

            # Phase G3 (decisions.md D-027): opt-in real pixel-diff visual
            # regression, independent of and additive to the OCR
            # expected_state check above. Only runs when the spec author
            # set visual_baseline_key -- every step/spec that doesn't use
            # it is completely unaffected. Combining rule: if the OCR
            # assertion above already failed (assertion_passed is False),
            # a passing visual diff doesn't revive it back to True; if OCR
            # wasn't configured or passed, the visual diff's own verdict
            # becomes (or further gates) assertion_passed. Deliberately
            # does NOT force escalate=True on a failing diff -- matches
            # the OCR expected_state path above, which also reports a
            # failed assertion without auto-escalating for human review;
            # only the "couldn't even capture a screenshot" case escalates,
            # since that's an infra failure, not an assertion failure.
            if step.visual_baseline_key and not result.escalate:
                visual_screenshot = self._safe_screenshot(run_id, step.step_id)
                if visual_screenshot is None:
                    result = result.model_copy(update={"assertion_passed": False, "escalate": True})
                else:
                    diff_result = compare_to_baseline(
                        visual_screenshot, step.visual_baseline_key, tolerance=step.visual_diff_tolerance
                    )
                    combined_passed = diff_result.passed if result.assertion_passed is not False else False
                    result = result.model_copy(update={
                        "assertion_passed": combined_passed,
                        "visual_diff_ratio": diff_result.diff_ratio,
                        "visual_diff_image_ref": diff_result.diff_image_path,
                        "visual_baseline_created": diff_result.baseline_created,
                    })

            # Phase 1 (next-phase plan) -- continuous-audit second opinion.
            # Runs before this step's result is recorded so that, on
            # disagreement, the healed (not the premature) result is what
            # actually gets aggregated/reported -- same principle as the
            # assertion/visual-diff checks just above, which also mutate
            # `result` before it's ever recorded. Gated on `not
            # result.escalate` -- an already-escalated step has nothing new
            # to second-guess; healing_loop already owns that case.
            if do_continuous_audit and not result.escalate:
                verdict = run_monitor.review_step(step, result)
                run_monitor.log_verdict(run_id, verdict)
                if not verdict.agrees:
                    disputed_result = result.model_copy(update={"escalate": True})
                    execution_logs = [
                        f"step {step.step_id} continuous-audit disagreement: {verdict.reason}"
                    ]
                    heal_result = healing_loop.heal(
                        step=step,
                        failed_result=disputed_result,
                        screenshot_path=screenshot_path,
                        execution_logs=execution_logs,
                        value=value,
                    )
                    result = heal_result.final_result
                    if heal_result.skill_used_or_learned is not None:
                        aggregator.record_skill_learned(heal_result.skill_used_or_learned)
                        if self.on_skill_learned:
                            self.on_skill_learned(step.step_id, heal_result.skill_used_or_learned)

            aggregator.record_step_result(result)
            if self.on_step_result:
                self.on_step_result(step.step_id, step, result)

            if result.escalate:
                continue

            self.memory.mark_step_complete(run_id, step.step_id)

        # --- Bot-trigger / validation-leg cross-check (TRD §11.6, Roadmap 21c) ---
        # A CapabilityType.AUTOMATION_ANYWHERE trigger step's own reported
        # terminal status is never sufficient alone -- this enforces that
        # at least one grouped WEB_VALIDATION/DATABASE/FILE_SYSTEM step also
        # independently confirmed the expected end state before the
        # trigger step (and therefore the run) can be marked passed.
        if any(getattr(s, "bot_validation_group", None) for s in spec.steps):
            self._enforce_bot_validation_cross_check(spec, aggregator)

        # --- Final spec-level assertions ---
        if spec.assertions:
            final_step_id = len(spec.steps) + 1
            final_screenshot = self._safe_screenshot(run_id, final_step_id)
            if final_screenshot is None:
                all_passed = False
                per_assertion_detail = [{"expected": a.expected, "passed": False, "method": "no_screenshot"} for a in spec.assertions]
            else:
                per_assertion_detail = []
                for a in spec.assertions:
                    detail = check_assertion_detailed(final_screenshot, a.expected)
                    per_assertion_detail.append({"expected": a.expected, **detail})
                    assertion_audit_log.log(
                        run_id=run_id, step_id=final_step_id, expected_state=a.expected,
                        detail=detail, escalate=False,
                    )
                all_passed = all(d["passed"] for d in per_assertion_detail)
            aggregator.record_step_result(
                VisionActionResult(
                    step_id=final_step_id,
                    action_taken="assert",
                    confidence=1.0,
                    escalate=False,
                    screenshot_ref=final_screenshot,
                    assertion_passed=all_passed,
                    verification_source="ocr",
                    raw_evidence={"assertions": per_assertion_detail},
                )
            )

        report = aggregator.finalize(requirement_text=requirement_text if requirement_text is not None else spec.requirement_ref)
        self.memory.finish_run(run_id, report.status.value)

        # Phase C: the Playwright browser session (runtime/hooks/browser.py)
        # is persistent *across this run's steps* by design (so DOM
        # resolution/self-heal share one live page), but must not leak into
        # the next run/process -- close it once this run's steps are done.
        #
        # keep_browser_open=True skips this: callers like
        # aura/cli/execute_cmd.py request it when --scroll-test/--ui-audit
        # are set, since those post-passes need the *same* live page this
        # run just used (a live DOM handle + a viewport-scoped screenshot
        # instead of a full-monitor grab of whatever's on screen after
        # teardown). Those callers are responsible for calling
        # browser_hook.close() themselves once they're done with it.
        if not keep_browser_open:
            try:
                from runtime.hooks import browser as browser_hook

                browser_hook.close()
            except Exception:
                pass

        # Phase I2 (decisions.md D-030): video/slideshow path is only known
        # for certain *after* browser_hook.close() finalizes the recording
        # to disk (Playwright only writes the video file once its page is
        # closed) -- so this has to happen after teardown above, then get
        # stitched into the report that's already been written. A real
        # Playwright video takes priority over the slideshow manifest when
        # both exist (e.g. a spec that started on the DOM path).
        if settings.record_video:
            video_path = None
            try:
                from runtime.hooks import browser as browser_hook

                video_path = browser_hook.get_last_video_path()
            except Exception:
                pass

            if video_path:
                report.report_paths["video"] = video_path
            elif slideshow_recorder is not None:
                slideshow_path = slideshow_recorder.finalize(run_id)
                if slideshow_path:
                    report.report_paths["video_slideshow"] = slideshow_path

            if "video" in report.report_paths or "video_slideshow" in report.report_paths:
                report_json_path = aggregator.run_dir / "report.json"
                report_json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

        # Phase Q (decisions.md D-038): same "only known for certain after
        # teardown" constraint as video above -- tracing.stop(path=...) is
        # called inside browser_hook.close() itself (it needs the context
        # still open), so by the time we get here the .zip is already on
        # disk and this is just reading the path back out. Scoped as its
        # own settings.record_trace check (not folded into the
        # settings.record_video block above) since the two are
        # independently toggleable -- a run can have either, both, or
        # neither.
        if settings.record_trace:
            trace_path = None
            try:
                from runtime.hooks import browser as browser_hook

                trace_path = browser_hook.get_last_trace_path()
            except Exception:
                pass

            if trace_path:
                report.report_paths["trace"] = trace_path
                report_json_path = aggregator.run_dir / "report.json"
                report_json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

        return RunEngineResult(run_id=run_id, spec=spec, report=report, validation_warnings=validation_warnings)