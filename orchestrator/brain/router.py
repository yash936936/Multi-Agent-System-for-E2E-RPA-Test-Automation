"""
orchestrator/brain/router.py

Given an `Intent`, calls into the right *existing* subsystems in the
right order. This module does not reimplement `RunEngine`,
`ui_audit_runner`, `spec_generator`, or the capability adapters --
those stay exactly what they are; the Router's only job is coordination.
See docs/AURA_BRAIN_ARCHITECTURE.md §2.3.

**Phase B3 (docs/decisions.md D-075):** all six `IntentKind` values are
now migrated. Two design decisions were needed beyond B1's mechanical
pattern (full rationale in `docs/AURA_BRAIN_ARCHITECTURE.md` §5.1/§5.2):

1. **Callback injection, not an event-stream redesign.** `execute_spec`/
   `execute_prompt`/`execute_interactive` need to render *during* a run
   (spec approval, per-step progress, heal accept/reject), not just
   from a completed report the way `explore` does. Rather than
   redesigning `RunEngine` to return a stream of typed events (a bigger,
   riskier change touching a "hand" the Brain isn't supposed to
   reimplement -- see §5's boundary), the CLI still builds its
   `live_view`-calling closures exactly as before and passes them
   through `Intent.params`; `_handle_execute_requirement()` and
   `_handle_execute_interactive()` forward them to `RunEngine`/approval
   points unchanged, and never import or call `live_view` themselves.
   This keeps the "Router doesn't render" boundary intact: it's the CLI
   that renders, via callbacks the CLI itself constructed -- the Router
   just carries them to where `RunEngine` already expected callbacks to
   begin with.

   **Gap #1 follow-up (docs/decisions.md D-079):**
   `_handle_execute_requirement` also accepts an optional `built_spec`
   param (skips `planner_generate_spec` and calls
   `RunEngine.run_spec()` directly when the caller -- api/routers/runs.py's
   "guided" mode -- already has a hand-assembled `TestSpec`, since there
   is no free-text requirement to re-plan from). Both
   `_handle_execute_requirement` and `_handle_explore` also accept an
   optional `run_id` param, since API callers pre-create a `run_store`
   record under their own generated UUID before the background task
   runs and cannot let the Brain derive a different one.
2. **`ui_audit` and `capability_check` became real, minimal standalone
   CLI commands** (`aura ui-audit <url>`, `aura capability-check
   <tool> --args '{...}'`) rather than staying flags/step-actions with
   nothing to migrate. Kept intentionally small: `ui_audit` reuses
   `orchestrator/ui_audit_runner.run_ui_audit` exactly as the existing
   `--ui-audit` flag on `execute` already does; `capability_check`
   reuses `orchestrator/kernel.py`'s existing `ToolCall`/`ToolResponse`
   contract exactly as a spec's `CAPABILITY_CHECK` step already does.
   Neither adds new capability -- both just expose an existing internal
   path as its own command.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from orchestrator.brain.intent import Intent
from orchestrator.brain.policy import Policy


@dataclass
class BrainResult:
    run_id: str
    kind: str
    data: dict[str, Any] = field(default_factory=dict)


class Router:
    def __init__(self, policy: Policy):
        self.policy = policy

    def resolve(self, intent: Intent) -> BrainResult:
        handler = getattr(self, f"_handle_{intent.kind}", None)
        if handler is None:
            raise NotImplementedError(
                f"AuraBrain: intent kind {intent.kind!r} has no handler in orchestrator/brain/router.py. "
                "All 6 documented IntentKind values (explore, execute_spec, execute_prompt, "
                "execute_interactive, ui_audit, capability_check) are migrated as of Phase B3 "
                "(docs/decisions.md D-075) -- this means either a typo, or a genuinely new intent "
                "kind that needs its own _handle_<kind>() method added here first."
            )
        return handler(intent)

    # ------------------------------------------------------------------
    # explore
    # ------------------------------------------------------------------
    def _handle_explore(self, intent: Intent) -> BrainResult:
        """
        Moved verbatim (same call sequence, same defaults) from
        `aura/cli/explore_cmd.py::explore()` as it existed before this
        migration -- this is a coordination move, not a behavior change.
        Rendering (console output, JSON report writing) stays in
        `explore_cmd.py`; this returns the data that rendering needs.
        """
        from config.settings import settings
        from runtime.hooks import browser
        from runtime.hooks.browser import normalize_url
        from runtime.hooks.capture import capture_screenshot

        url = intent.get("url")
        max_elements = intent.get("max_elements", 25)
        prompt = intent.get("prompt")
        scroll_scan = intent.get("scroll_scan", True)
        check_links = intent.get("check_links", False)
        link_scope = intent.get("link_scope", "all")

        # `run_id` override (API callers, e.g. api/routers/runs.py, pre-create
        # a run_store record under their own generated UUID before the
        # background task runs -- the Brain can't be allowed to derive a
        # different run_id here, or the report would be written under an id
        # the caller never learns about). CLI callers omit this and keep the
        # original explore_<hex8> scheme.
        run_id = intent.get("run_id") or f"explore_{uuid.uuid4().hex[:8]}"
        normalized = normalize_url(url)

        open_error: str | None = None
        try:
            browser.open_url(normalized)
        except Exception as e:  # noqa: BLE001 - surfaced to the caller either way
            open_error = str(e)

        time.sleep(settings.human_action_poll_interval_seconds)

        def provider(rid: str, index: int) -> str:
            # Deliberately does NOT catch NoDisplayError here -- see
            # explore_cmd.py's original note, preserved: run_autoscan and
            # run_exploration each wrap their own calls to this provider in
            # runtime.errors.display_guard(), which only works if the error
            # propagates out of the provider uncaught.
            return str(capture_screenshot(rid, index))

        autoscan_report = None
        if scroll_scan:
            from orchestrator.autoscan import run_autoscan

            autoscan_report = run_autoscan(provider, run_id=run_id)

        from orchestrator.ui_audit_runner import run_exploration

        report = run_exploration(
            provider,
            run_id=run_id,
            max_elements=max_elements,
            requirement_prompt=prompt,
            page_url=normalized if check_links else None,
            link_check_scope=link_scope,
        )

        return BrainResult(
            run_id=run_id,
            kind="explore",
            data={
                "normalized_url": normalized,
                "open_error": open_error,
                "autoscan_report": autoscan_report,
                "report": report,
                "prompt": prompt,
                "check_links": check_links,
                "link_scope": link_scope,
            },
        )

    # ------------------------------------------------------------------
    # execute_spec / execute_prompt -- both share the exact same
    # requirement-text -> generate_spec -> RunEngine flow (the pre-B3
    # CLI's `_run_requirement_text`); there is no real behavioral
    # difference between "a spec file's text" and "a prompt's text" once
    # both have been resolved to a requirement string, so one handler
    # serves both intent kinds.
    # ------------------------------------------------------------------
    def _handle_execute_spec(self, intent: Intent) -> BrainResult:
        return self._handle_execute_requirement(intent)

    def _handle_execute_prompt(self, intent: Intent) -> BrainResult:
        return self._handle_execute_requirement(intent)

    def _handle_execute_requirement(self, intent: Intent) -> BrainResult:
        """
        Moved from `aura/cli/execute_cmd.py::_run_requirement_text()`.
        Every place the pre-migration function called `live_view`
        directly (spec-approval checklist, per-step progress, the
        low-confidence inline prompt, heal accept/reject) is now a
        callback the CLI builds and passes in via `intent.params` --
        see this module's docstring, decision 1. Report writing
        (`render_json`/`render_html`/PDF/JUnit) and the final
        `live_view.render_run_summary` call also stay in the CLI, same
        as `explore`'s split: this returns data, the CLI renders it.
        """
        from agents.planner.spec_generator import extract_navigate_url
        from agents.planner.tool import generate_spec as planner_generate_spec
        from orchestrator.memory import RunMemoryStore
        from orchestrator.run_engine import RunEngine
        from orchestrator.schemas import RequirementInput
        from orchestrator.skill_store import SkillStore
        from orchestrator.spec_validator import SpecValidationError

        requirement_text = intent.get("requirement_text")
        auto_approve = intent.get("auto_approve", False)
        refresh_data = intent.get("refresh_data", False)
        scroll_test = intent.get("scroll_test", False)
        ui_audit = intent.get("ui_audit", False)
        continuous_audit = intent.get("continuous_audit")
        screenshot_provider = intent.get("screenshot_provider")

        # `built_spec` (API "guided" mode): the caller already has a fully
        # structured TestSpec (built via api/spec_builder.py::build_test_spec
        # from hand-assembled JSON steps), so there is no free-text
        # requirement to hand to the Planner -- skip planner_generate_spec
        # entirely and run the spec as given.
        built_spec = intent.get("built_spec")

        # `run_id` override -- see the matching note in _handle_explore.
        run_id_override = intent.get("run_id")

        # CLI-supplied closures -- each defaults to a no-op so this
        # method never needs to know whether the caller wired rendering
        # up; `approve_spec` additionally defaults to "approve" (matches
        # `_run_requirement_text`'s own `auto_approve` semantics when no
        # checkpoint callback is given at all).
        on_step_start = intent.get("on_step_start") or (lambda step_id, step: None)
        on_step_result = intent.get("on_step_result") or (lambda step_id, step, result: None)
        on_skill_learned = intent.get("on_skill_learned") or (lambda step_id, skill: None)
        approve_spec = intent.get("approve_spec") or (lambda spec: True)
        confirm_heal_accept = intent.get("confirm_heal_accept") or (lambda step_id, skill: True)
        on_scan_progress = intent.get("on_scan_progress") or (lambda message: None)

        nav_url = extract_navigate_url(requirement_text) if requirement_text else None

        if built_spec is not None:
            spec = built_spec
        else:
            page_context = None
            if nav_url:
                from agents.planner.page_grounding import snapshot_page_elements

                page_context = snapshot_page_elements(nav_url)

            spec = planner_generate_spec(RequirementInput(requirement_text=requirement_text, page_context=page_context))

        if not auto_approve and not approve_spec(spec):
            return BrainResult(run_id=spec.test_id, kind=intent.kind, data={"cancelled": True, "spec": spec})

        if refresh_data:
            from agents.data_synth.cache import clear_cache

            clear_cache(spec.test_id)

        skill_store = SkillStore()
        memory = RunMemoryStore()
        learned_skills: list[tuple[int, Any]] = []

        def _on_skill_learned(step_id: int, skill) -> None:
            learned_skills.append((step_id, skill))
            on_skill_learned(step_id, skill)

        engine = RunEngine(
            screenshot_provider=screenshot_provider,
            skill_store=skill_store,
            memory=memory,
            on_step_start=on_step_start,
            on_step_result=on_step_result,
            on_skill_learned=_on_skill_learned,
        )

        resolved_run_id = run_id_override or spec.test_id.lower().replace(" ", "-")

        if built_spec is not None:
            # Execute the already-built spec directly -- engine.run() would
            # otherwise re-derive a spec from requirement_text via
            # Planner.generate_spec, discarding the caller's hand-assembled
            # steps (the API's "guided" mode has no free-text requirement
            # to re-plan from in the first place).
            result = engine.run_spec(
                spec,
                run_id=resolved_run_id,
                requirement_text=requirement_text,
                keep_browser_open=scroll_test or ui_audit,
                continuous_audit=continuous_audit,
            )
        else:
            result = engine.run(
                requirement_text,
                run_id=resolved_run_id,
                keep_browser_open=scroll_test or ui_audit,
                continuous_audit=continuous_audit,
            )

        for step_id, skill in learned_skills:
            if auto_approve:
                continue
            if not confirm_heal_accept(step_id, skill):
                skill_store.delete(skill.skill_id)

        autoscan_report = None
        if scroll_test:
            from orchestrator.autoscan import run_autoscan

            on_scan_progress("scanning_full_page")
            autoscan_report = run_autoscan(screenshot_provider, run_id=result.run_id)

        ui_audit_report = None
        if ui_audit:
            from orchestrator.ui_audit_runner import run_ui_audit

            on_scan_progress("running_ui_audit")
            ui_audit_report = run_ui_audit(screenshot_provider, run_id=result.run_id, page_url=nav_url)

        if scroll_test or ui_audit:
            try:
                from runtime.hooks import browser as browser_hook

                browser_hook.close()
            except Exception:
                pass

        return BrainResult(
            run_id=result.run_id,
            kind=intent.kind,
            data={
                "spec": spec,
                "result": result,
                "autoscan_report": autoscan_report,
                "ui_audit_report": ui_audit_report,
                "nav_url": nav_url,
                "memory": memory,
                "cancelled": False,
            },
        )

    # ------------------------------------------------------------------
    # execute_interactive
    # ------------------------------------------------------------------
    def _handle_execute_interactive(self, intent: Intent) -> BrainResult:
        """
        Moved from `aura/cli/execute_cmd.py::execute_interactive()`.
        `on_waiting` is a CLI-supplied closure (decision 1, same
        pattern as the requirement-execution handlers above) -- this
        method never calls `live_view` itself.
        """
        from orchestrator.run_engine import RunEngine
        from orchestrator.schemas import ActionType, TestSpec, TestStep
        from runtime.hooks.browser import normalize_url

        prompt = intent.get("prompt")
        url = intent.get("url")
        timeout = intent.get("timeout", 0)
        screenshot_provider = intent.get("screenshot_provider")
        on_waiting = intent.get("on_waiting")

        run_id = f"interactive_{uuid.uuid4().hex[:8]}"
        steps: list[TestStep] = []
        if url:
            steps.append(TestStep(step_id=1, action=ActionType.NAVIGATE_URL, url=normalize_url(url)))
        steps.append(
            TestStep(
                step_id=len(steps) + 1,
                action=ActionType.WAIT_FOR_HUMAN_ACTION,
                target_description=prompt,
                human_action_timeout_seconds=timeout or None,
            )
        )
        spec = TestSpec(test_id=f"TC-INTERACTIVE-{run_id.upper()}", requirement_ref="human-in-the-loop", steps=steps)

        engine = RunEngine(screenshot_provider=screenshot_provider, on_waiting_for_human=on_waiting)
        result = engine.run_spec(spec, run_id=run_id)

        return BrainResult(run_id=run_id, kind="execute_interactive", data={"result": result})

    # ------------------------------------------------------------------
    # ui_audit -- standalone (decision 2): `agents/vision/ui_audit_runner
    # .run_ui_audit` exactly as `execute --ui-audit` already calls it,
    # just without a full spec run wrapped around it.
    # ------------------------------------------------------------------
    def _handle_ui_audit(self, intent: Intent) -> BrainResult:
        from config.settings import settings
        from runtime.hooks import browser
        from runtime.hooks.browser import normalize_url
        from runtime.hooks.capture import capture_screenshot

        url = intent.get("url")
        max_elements = intent.get("max_elements", 12)
        link_scope = intent.get("link_scope", "all")

        run_id = f"ui_audit_{uuid.uuid4().hex[:8]}"
        normalized = normalize_url(url)

        open_error: str | None = None
        try:
            browser.open_url(normalized)
        except Exception as e:  # noqa: BLE001
            open_error = str(e)

        time.sleep(settings.human_action_poll_interval_seconds)

        def provider(rid: str, index: int) -> str:
            return str(capture_screenshot(rid, index))

        from orchestrator.ui_audit_runner import run_ui_audit

        report = run_ui_audit(provider, run_id=run_id, max_elements=max_elements, page_url=normalized, link_check_scope=link_scope)

        return BrainResult(
            run_id=run_id,
            kind="ui_audit",
            data={"normalized_url": normalized, "open_error": open_error, "report": report},
        )

    # ------------------------------------------------------------------
    # capability_check -- standalone (decision 2): the exact
    # ToolCall/ToolResponse + CapabilityCheckInput contract a spec's
    # CAPABILITY_CHECK step already dispatches through
    # (orchestrator/run_engine.py's own `call_tool("Capability.check",
    # ...)` closure), exposed directly rather than reimplemented.
    # ------------------------------------------------------------------
    def _handle_capability_check(self, intent: Intent) -> BrainResult:
        from orchestrator.kernel import OrchestratorKernel, ToolRegistry
        from orchestrator.schemas import CapabilityCheckInput, ToolCall

        capability_type = intent.get("capability_type")
        target = intent.get("target")
        params = intent.get("params", {})
        expected = intent.get("expected", {})

        run_id = f"capability_{uuid.uuid4().hex[:8]}"
        registry = ToolRegistry().load()
        kernel = OrchestratorKernel(registry=registry, run_id=run_id)

        payload = CapabilityCheckInput(capability=capability_type, target=target, params=params, expected=expected)
        response = kernel.call_tool(ToolCall(name="Capability.check", arguments=payload.model_dump(mode="json")))

        result = None
        error = None
        if response.ok:
            result = registry.get("Capability.check").output_schema.model_validate(response.result)
        else:
            error = response.error

        return BrainResult(
            run_id=run_id,
            kind="capability_check",
            data={"capability_type": capability_type, "target": target, "result": result, "error": error},
        )
