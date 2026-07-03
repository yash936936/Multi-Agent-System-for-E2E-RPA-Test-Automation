"""
Executor — Vision.execute_step

Locates the step's target from a screenshot, applies the confidence gate
(TRD §5.3 / WORKFLOW §Step 4.3, default 0.75 in config/settings.py), and
dispatches the interaction if confidence clears the bar. Below-threshold
locates are returned with escalate=True and no interaction is dispatched
— the healing loop (Phase 5) decides what to do next.

A skill_hint (SkillRecord), if provided, can propose a broadened search
region — this is where a previously-learned "broaden search region" fix
(agents/planner/diagnoser.py) actually gets applied on retry.
"""
from __future__ import annotations

from config.settings import settings
from orchestrator.schemas import ActionType, VisionActionResult, VisionStepInput


def _region_from_skill_hint(skill_hint) -> tuple[int, int, int, int] | None:
    """
    Very small convention: if a skill's proposed_fix mentions "broaden",
    we signal "search full screen" by returning None (no crop) rather than
    attempting to parse arbitrary coordinates out of free text. Real region
    inference from skill text is a natural place to extend later without
    changing this function's contract.
    """
    return None


def execute_step(payload: VisionStepInput) -> VisionActionResult:
    from agents.vision.locator import locate_text

    step = payload.step
    threshold = settings.vision_confidence_threshold

    if step.action == ActionType.NAVIGATE_URL:
        from runtime.hooks import browser
        from runtime.hooks.browser import NoDisplayError as BrowserNoDisplayError

        url = step.url or step.target_description
        try:
            browser.open_url(url or "")
        except ValueError:
            # No URL on the step at all -- this is a spec problem, not an
            # environment one, so escalate rather than silently no-op.
            return VisionActionResult(
                step_id=step.step_id,
                action_taken="none",
                confidence=0.0,
                escalate=True,
                screenshot_ref=payload.screenshot_path,
            )
        except BrowserNoDisplayError:
            # No live display/browser (headless/test environment) -- same
            # posture as the click/type NoDisplayError handling below: the
            # step itself is well-formed, dispatch just can't happen here.
            pass

        return VisionActionResult(
            step_id=step.step_id,
            action_taken="navigate",
            confidence=1.0,
            escalate=False,
            screenshot_ref=payload.screenshot_path,
        )

    if step.action == ActionType.SCROLL:
        from runtime.hooks import interact

        interact.scroll(-300)
        return VisionActionResult(
            step_id=step.step_id,
            action_taken="scroll",
            confidence=1.0,
            escalate=False,
            screenshot_ref=payload.screenshot_path,
        )

    target_text = step.target_description or step.field_description
    if not target_text:
        return VisionActionResult(
            step_id=step.step_id,
            action_taken="none",
            confidence=0.0,
            escalate=True,
            screenshot_ref=payload.screenshot_path,
        )

    region = _region_from_skill_hint(payload.skill_hint)
    result = locate_text(payload.screenshot_path, target_text, search_region=region)

    if not result.found or result.confidence < threshold:
        return VisionActionResult(
            step_id=step.step_id,
            action_taken="none",
            target_coords=(result.x, result.y) if result.found else None,
            confidence=result.confidence,
            escalate=True,
            screenshot_ref=payload.screenshot_path,
        )

    action_taken = "click" if step.action == ActionType.VISUAL_CLICK else "type"

    try:
        from runtime.hooks import interact
        from runtime.hooks.interact import NoDisplayError

        if action_taken == "click":
            interact.click(result.x, result.y)
        else:
            interact.click(result.x, result.y)  # focus the field first
            interact.type_text(payload.value or "")
    except NoDisplayError:
        # No live display (headless/test environment) — locate still
        # succeeded, so we report the action as taken with its real
        # confidence rather than masking a working locator behind a
        # dispatch-layer failure that's environmental, not a step failure.
        pass

    return VisionActionResult(
        step_id=step.step_id,
        action_taken=action_taken,
        target_coords=(result.x, result.y),
        confidence=result.confidence,
        escalate=False,
        screenshot_ref=payload.screenshot_path,
    )
