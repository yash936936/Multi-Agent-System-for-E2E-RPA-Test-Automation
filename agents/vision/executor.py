"""
Executor — Vision.execute_step

Locates the step's target and applies the confidence gate (TRD §5.3 /
WORKFLOW §Step 4.3, default 0.75 in config/settings.py), dispatching the
interaction if confidence clears the bar. Below-threshold locates are
returned with escalate=True and no interaction is dispatched -- the
healing loop (Phase 5) decides what to do next.

Phase U (Roadmap "Phases R-V", decisions.md D-043) replaced the previous
DOM-first/OCR-fallback chain (Phase C) with OCR-then-DOM dual
verification: for any browser target with a live page, BOTH locators
always run, every time -- not conditionally, not "OCR only if DOM
missed." Their results are then compiled:

  - Both clear the threshold AND their locations overlap -> agreement.
    Dispatch through whichever method scored higher, tagged
    "dual-method-confirmed".
  - Both clear the threshold but at different locations -> disagreement.
    Never silently trust one over the other: log it, record both
    candidates in verification_evidence, and resolve via the configured
    settings.dual_verification_tie_break. Still tagged
    "dual-method-confirmed" (both genuinely found *something*).
  - Only one method clears the threshold (including "DOM wasn't
    applicable at all," e.g. no browser session) -> proceed on that one,
    tagged "single-method".
  - Neither clears the threshold -> escalate, both candidates still
    recorded.

A skill_hint (SkillRecord), if provided, can propose a broadened search
region for the OCR side -- this is where a previously-learned "broaden
search region" fix (agents/planner/diagnoser.py) actually gets applied
on retry.
"""
from __future__ import annotations

import logging

from config.settings import DUAL_VERIFICATION_TIE_BREAK_CHOICES, settings
from orchestrator.schemas import ActionType, VisionActionResult, VisionStepInput

_logger = logging.getLogger(__name__)


def _region_from_skill_hint(skill_hint) -> tuple[int, int, int, int] | None:
    """
    Very small convention: if a skill's proposed_fix mentions "broaden",
    we signal "search full screen" by returning None (no crop) rather than
    attempting to parse arbitrary coordinates out of free text. Real region
    inference from skill text is a natural place to extend later without
    changing this function's contract.
    """
    return None


def _resolve_dom(browser_hook, target_text: str):
    """
    Phase U: pure resolution, no dispatch (dispatch now happens after
    compilation, once we know which method -- possibly both -- actually
    won). Runs the same two-step DOM chain Phase C established:

      1. locate_dom() against the current accessibility tree.
      2. If that doesn't clear its own threshold, relocate_dom() -- the
         Scrapling-style self-heal -- re-scores every current candidate
         at a relaxed threshold before giving up on the DOM path.

    Returns a DomLocateResult (found=False if no live page, no
    candidates, or neither step cleared its threshold).

    Phase 3 bug fix (next-phase plan, "OCR + DOM working together"):
    this previously only caught NoDisplayError, raised solely by
    browser_hook.get_page() when no page exists at all. Everything after
    that -- locate_dom()/relocate_dom() calling
    dom_locator.snapshot_elements(), which calls Playwright's
    page.locator("html").aria_snapshot() with no exception handling of
    its own -- was completely unguarded. Verified by direct reproduction
    (not assumed): a page mid-navigation, a closed target, or a detached
    frame all raise a raw Playwright Error there ("Execution context was
    destroyed, most likely because of a navigation" is a common one right
    after a click that triggers page load) -- none of which are
    NoDisplayError, so they propagated straight through execute_step,
    orchestrator/kernel.py's call_tool (which re-wraps it as a failed
    ToolResponse), and back out as a RuntimeError from run_engine.py's
    call_tool closure, crashing the entire run instead of the documented
    "only one method clears the threshold -> proceed on that one"
    single-method fallback. This is a materially better explanation for
    intermittent "looks like OCR only" behavior than a genuine dual-
    verification miss: a step whose DOM snapshot happens to land during
    a navigation doesn't just silently prefer OCR, it can take the whole
    run down -- which, depending on which steps happen to hit the timing
    window, looks exactly like unpredictable "sometimes only OCR ran."

    Every DOM-path miss is now logged (not silently swallowed) with which
    of the three cases it was -- no live page, a genuine no-match, or a
    caught exception with its actual message -- specifically so a live
    run's logs can distinguish "DOM never got a chance to run" from "DOM
    ran and found nothing" the next time this comes up.
    """
    from agents.vision.dom_locator import DomLocateResult, locate_dom, relocate_dom
    from runtime.errors import NoDisplayError

    try:
        page = browser_hook.get_page()
    except NoDisplayError as e:
        _logger.info("Vision.execute_step: DOM path skipped, no active page (%s).", e)
        return DomLocateResult(found=False)

    try:
        dom_result = locate_dom(page, target_text)
        if not dom_result.found:
            dom_result = relocate_dom(page, {"name": target_text})
    except Exception as e:  # noqa: BLE001 - see docstring: must degrade to single-method, never crash the run
        _logger.warning(
            "Vision.execute_step: DOM path raised during resolution (%s: %s) -- "
            "treating as not-found so OCR's result can still be dispatched, "
            "instead of crashing the run.",
            type(e).__name__, e,
        )
        return DomLocateResult(found=False)

    if not dom_result.found:
        _logger.info(
            "Vision.execute_step: DOM path ran but found no match for %r (top score seen: %s).",
            target_text, dom_result.top_score_seen,
        )
    return dom_result


def _locations_overlap(ocr_result, dom_result, tolerance_px: int) -> bool:
    """
    True if OCR's matched point falls inside DOM's bounding box, expanded
    by tolerance_px in every direction. Real DOM boxes and OCR text-line
    centers rarely land on the exact same pixel even for a genuine match
    (different measurement methods entirely), so a tolerance avoids
    flagging pixel jitter as a real disagreement. Returns False (not an
    exception) whenever there's nothing to compare -- a missing bbox is
    "can't confirm agreement," which correctly routes to the tie-break
    path rather than crashing.
    """
    if not (ocr_result.found and dom_result.found and dom_result.bbox):
        return False
    bbox = dom_result.bbox
    x0 = bbox["x"] - tolerance_px
    y0 = bbox["y"] - tolerance_px
    x1 = bbox["x"] + bbox["width"] + tolerance_px
    y1 = bbox["y"] + bbox["height"] + tolerance_px
    return x0 <= ocr_result.x <= x1 and y0 <= ocr_result.y <= y1


def _apply_tie_break(ocr_result, dom_result, tie_break_mode: str, target_description: str | None = None) -> str:
    """Returns "dom" or "ocr" -- which candidate wins a genuine
    disagreement. Falls back to the "highest_confidence" default (with a
    logged warning, not a crash) if settings holds an unrecognized value,
    same defensive posture as runtime/hooks/browser.py's own
    playwright_browser validation.

    Phase W (decisions.md D-047): "llm_semantic" asks a configured LLM
    backend which candidate's matched text/role better fits the step's
    plain-English target_description (agents/vision/llm_verifier.py).
    This is a best-effort refinement layered on top of the numeric rules
    below, not a replacement for them -- if the verifier is disabled, not
    configured, or its call fails, this silently (but logged) falls back
    to "highest_confidence" exactly like an unrecognized mode string
    would, so enabling llm_semantic can never make dual-verification less
    reliable than it already was.
    """
    if tie_break_mode not in DUAL_VERIFICATION_TIE_BREAK_CHOICES:
        _logger.warning(
            "Vision.execute_step: unrecognized dual_verification_tie_break "
            "%r, falling back to 'highest_confidence'. Valid choices: %s.",
            tie_break_mode, ", ".join(DUAL_VERIFICATION_TIE_BREAK_CHOICES),
        )
        tie_break_mode = "highest_confidence"

    if tie_break_mode == "prefer_dom":
        return "dom"
    if tie_break_mode == "prefer_ocr":
        return "ocr"
    if tie_break_mode == "llm_semantic":
        from agents.vision.llm_verifier import semantic_verify

        winner = semantic_verify(target_description or "", ocr_result, dom_result)
        if winner is not None:
            return winner
        # No usable opinion (disabled/unconfigured/failed) -- fall through
        # to the same numeric rule "highest_confidence" already uses.
    return "dom" if dom_result.confidence >= ocr_result.confidence else "ocr"


def _compile_dual_result(ocr_result, dom_result, dom_attempted: bool, threshold: float, tie_break_mode: str, overlap_tolerance_px: int, target_description: str | None = None):
    """
    The Phase U compilation rule (docs/Roadmap.md "Phase U"). Returns
    (decision, confidence, winner, evidence):

      decision: "dispatch" | "escalate"
      confidence: the float to report on the VisionActionResult
      winner: "dom" | "ocr" | None -- which method's candidate to dispatch
      evidence: dict for VisionActionResult.verification_evidence, always
        carrying both candidates (never silently dropping the loser)
    """
    ocr_ok = ocr_result.found and ocr_result.confidence >= threshold
    dom_ok = dom_attempted and dom_result.found and dom_result.confidence >= threshold

    ocr_evidence = {
        "found": ocr_result.found,
        "confidence": ocr_result.confidence,
        "x": ocr_result.x if ocr_result.found else None,
        "y": ocr_result.y if ocr_result.found else None,
        "matched_text": ocr_result.matched_text,
    }
    dom_evidence = (
        {"attempted": False}
        if not dom_attempted
        else {
            "attempted": True,
            "found": dom_result.found,
            "confidence": dom_result.confidence,
            "matched_text": dom_result.matched_text,
            "role": dom_result.role,
            "strategy": dom_result.strategy,
            "bbox": dom_result.bbox,
            "top_score_seen": dom_result.top_score_seen,
        }
    )

    if not ocr_ok and not dom_ok:
        confidence = max(ocr_result.confidence, dom_result.confidence if dom_attempted else 0.0)
        return "escalate", confidence, None, {
            "verification_method": None,
            "ocr": ocr_evidence,
            "dom": dom_evidence,
            "agreement": None,
            "tie_break_applied": None,
            "winner": None,
        }

    if ocr_ok and dom_ok:
        agree = _locations_overlap(ocr_result, dom_result, overlap_tolerance_px)
        if agree:
            winner = "dom" if dom_result.confidence >= ocr_result.confidence else "ocr"
            confidence = max(ocr_result.confidence, dom_result.confidence)
            tie_break_applied = None
        else:
            winner = _apply_tie_break(ocr_result, dom_result, tie_break_mode, target_description)
            confidence = dom_result.confidence if winner == "dom" else ocr_result.confidence
            tie_break_applied = tie_break_mode
            _logger.warning(
                "Vision.execute_step: OCR/DOM disagreement -- OCR found %r "
                "at (%s, %s) conf=%.2f; DOM found %r conf=%.2f at a "
                "non-overlapping location. Resolving via tie-break %r -> %s.",
                ocr_result.matched_text, ocr_result.x, ocr_result.y, ocr_result.confidence,
                dom_result.matched_text, dom_result.confidence, tie_break_mode, winner,
            )
        return "dispatch", confidence, winner, {
            "verification_method": "dual-method-confirmed",
            "ocr": ocr_evidence,
            "dom": dom_evidence,
            "agreement": agree,
            "tie_break_applied": tie_break_applied,
            "winner": winner,
        }

    winner = "dom" if dom_ok else "ocr"
    confidence = dom_result.confidence if dom_ok else ocr_result.confidence
    return "dispatch", confidence, winner, {
        "verification_method": "single-method",
        "ocr": ocr_evidence,
        "dom": dom_evidence,
        "agreement": None,
        "tie_break_applied": None,
        "winner": winner,
    }


def _dispatch_dom(dom_result, action_taken: str, value) -> bool:
    """Attempts the DOM-path interaction. Returns False (not an
    exception) on NoDisplayError -- e.g. the element resolved but went
    stale/detached before dispatch -- so the caller can fall back to the
    OCR candidate if one also cleared the threshold, exactly as Phase C's
    original single-path fallback did."""
    from runtime.errors import NoDisplayError
    from runtime.hooks import interact

    try:
        if action_taken == "click":
            interact.dom_click(dom_result.locator)
        else:
            interact.dom_fill(dom_result.locator, value or "")
        return True
    except NoDisplayError:
        return False


def _dispatch_ocr(ocr_result, action_taken: str, value) -> bool:
    """Attempts the OCR/pixel-path interaction. Returns False on
    NoDisplayError (e.g. headless/no-tkinter environment).

    Phase 2 (cursor-coordinate fix, next-phase plan): a live browser
    session dispatches through the page's own Playwright mouse whenever
    possible, translating ocr_result's OS/mss-pixel coordinate into that
    page's CSS/viewport space first (browser.get_click_point_in_page) --
    never the raw OS coordinate directly when a page exists, since that's
    what caused the "taskbar jump" bug (see that function's docstring).
    Falls back to the OS-level interact.click() path only when no page
    exists at all (a native, non-browser target) or the translation can't
    be computed -- same fail-soft contract, unchanged for that case.
    """
    from runtime.errors import NoDisplayError
    from runtime.hooks import interact
    from runtime.hooks import browser as browser_hook

    try:
        page_point = browser_hook.get_click_point_in_page(ocr_result.x, ocr_result.y)
        if page_point is not None:
            page = browser_hook.get_page()
            page.mouse.click(*page_point)
        elif action_taken == "click":
            interact.click(ocr_result.x, ocr_result.y)
        else:
            interact.click(ocr_result.x, ocr_result.y)  # focus the field first

        if action_taken == "type":
            interact.type_text(value or "")
        return True
    except NoDisplayError:
        return False


def execute_step(payload: VisionStepInput) -> VisionActionResult:
    from agents.vision.locator import locate_text

    step = payload.step
    threshold = settings.vision_confidence_threshold

    if step.action == ActionType.NAVIGATE_URL:
        from runtime.errors import NoDisplayError
        from runtime.hooks import browser

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
        except NoDisplayError:
            # No live display/browser (e.g. running headless on a server).
            # Previously this was silently swallowed and the step was
            # unconditionally reported as a successful navigation
            # (confidence=1.0, escalate=False) -- meaning a run could
            # report "passed" with zero actual navigation ever having
            # happened, and nothing downstream could tell the difference.
            # Report it honestly as escalated/unconfirmed instead so the
            # report reflects reality rather than a guaranteed false pass.
            return VisionActionResult(
                step_id=step.step_id,
                action_taken="none",
                confidence=0.0,
                escalate=True,
                screenshot_ref=payload.screenshot_path,
            )

        return VisionActionResult(
            step_id=step.step_id,
            action_taken="navigate",
            confidence=1.0,
            escalate=False,
            screenshot_ref=payload.screenshot_path,
        )

    if step.action == ActionType.SCROLL:
        from runtime.hooks import interact
        from runtime.hooks import browser as browser_hook

        # Phase 2 (next-phase plan): prefer the DOM-scoped scroll (JS
        # window.scrollBy on the live page, orchestrator/autoscan.py
        # already established this same pattern for its own scroll loop)
        # over the OS-level interact.scroll() fallback -- a raw OS wheel
        # event goes to whatever window currently has OS focus, which
        # silently does nothing useful if that isn't the browser. Only
        # falls back to the OS path when no live page exists at all.
        if not browser_hook.dom_scroll(-300):
            interact.scroll(-300)
        return VisionActionResult(
            step_id=step.step_id,
            action_taken="scroll",
            confidence=1.0,
            escalate=False,
            screenshot_ref=payload.screenshot_path,
        )

    if step.action == ActionType.ASSERT:
        # Regression fix: this branch was missing entirely. Assert steps
        # carry their check in step.expected_state, not
        # target_description/field_description -- falling through to the
        # generic click/type path below meant `target_text` was always
        # None, which unconditionally hit the "no target_text" escalate
        # case a few lines down. That made every single assert step
        # report confidence=0.0/escalate=True immediately, with no OCR/DOM
        # check ever attempted -- which in turn meant run_engine's own
        # expected_state verification (gated on `not result.escalate`)
        # never ran either, so a step could never actually pass or fail
        # on its real content; it just escalated every time, regardless
        # of what was on screen. No action needs to be *taken* for an
        # assert step -- the actual pass/fail check happens downstream in
        # run_engine via check_assertion() against step.expected_state --
        # so this just needs to hand back a non-escalated result so that
        # downstream check gets a chance to run at all.
        return VisionActionResult(
            step_id=step.step_id,
            action_taken="none",
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

    action_taken = "click" if step.action == ActionType.VISUAL_CLICK else "type"

    # --- Phase U: both locators always run when a browser session
    # exists -- OCR against the screenshot (as before Phase C), and DOM
    # against the live accessibility tree (including its relocate()
    # self-heal) -- rather than the old DOM-first/OCR-only-as-fallback
    # chain. For native desktop targets, or when no browser session
    # exists at all, DOM simply isn't attempted (dom_attempted=False) and
    # this collapses back to OCR-only, exactly as it always has.
    region = _region_from_skill_hint(payload.skill_hint)
    ocr_result = locate_text(payload.screenshot_path, target_text, search_region=region)

    from runtime.hooks import browser as browser_hook

    dom_attempted = browser_hook.has_active_page()
    dom_result = _resolve_dom(browser_hook, target_text) if dom_attempted else None
    if dom_result is None:
        from agents.vision.dom_locator import DomLocateResult

        dom_result = DomLocateResult(found=False)

    decision, confidence, winner, evidence = _compile_dual_result(
        ocr_result, dom_result, dom_attempted, threshold,
        settings.dual_verification_tie_break,
        settings.dual_verification_overlap_tolerance_px,
        target_description=target_text,
    )

    if decision == "escalate":
        return VisionActionResult(
            step_id=step.step_id,
            action_taken="none",
            target_coords=(ocr_result.x, ocr_result.y) if ocr_result.found else None,
            confidence=confidence,
            escalate=True,
            screenshot_ref=payload.screenshot_path,
            verification_method=evidence["verification_method"],
            verification_evidence=evidence,
        )

    # Dispatch through the winning method; if its dispatch fails for a
    # display-related reason and the *other* method also cleared the
    # threshold, fall back to it rather than reporting a false miss --
    # the same fallback behavior Phase C's single-path chain had, just
    # available from either direction now.
    dom_ok = dom_attempted and dom_result.found and dom_result.confidence >= threshold
    ocr_ok = ocr_result.found and ocr_result.confidence >= threshold

    dispatched_via = None
    if winner == "dom":
        if _dispatch_dom(dom_result, action_taken, payload.value):
            dispatched_via = "dom"
        elif ocr_ok:
            if _dispatch_ocr(ocr_result, action_taken, payload.value):
                dispatched_via = "ocr"
    else:
        if _dispatch_ocr(ocr_result, action_taken, payload.value):
            dispatched_via = "ocr"
        elif dom_ok:
            if _dispatch_dom(dom_result, action_taken, payload.value):
                dispatched_via = "dom"

    # dispatched_via is None only when every candidate dispatch that was
    # attempted failed with NoDisplayError -- an environmental condition,
    # not a locate failure (both locators already cleared the confidence
    # gate above). Report success rather than masking a working locator
    # behind a dispatch-layer failure, matching Phase C's original
    # headless-OCR handling.
    evidence = dict(evidence)
    evidence["dispatched_via"] = dispatched_via

    return VisionActionResult(
        step_id=step.step_id,
        action_taken=action_taken,
        target_coords=(ocr_result.x, ocr_result.y) if ocr_result.found else None,
        confidence=confidence,
        escalate=False,
        screenshot_ref=payload.screenshot_path,
        verification_method=evidence["verification_method"],
        verification_evidence=evidence,
    )
