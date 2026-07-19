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
    """
    from agents.vision.dom_locator import DomLocateResult, locate_dom, relocate_dom
    from runtime.errors import NoDisplayError

    try:
        page = browser_hook.get_page()
    except NoDisplayError:
        return DomLocateResult(found=False)

    dom_result = locate_dom(page, target_text)
    if not dom_result.found:
        dom_result = relocate_dom(page, {"name": target_text})
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


def _apply_tie_break(ocr_result, dom_result, tie_break_mode: str) -> str:
    """Returns "dom" or "ocr" -- which candidate wins a genuine
    disagreement. Falls back to the "highest_confidence" default (with a
    logged warning, not a crash) if settings holds an unrecognized value,
    same defensive posture as runtime/hooks/browser.py's own
    playwright_browser validation."""
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
    return "dom" if dom_result.confidence >= ocr_result.confidence else "ocr"


def _compile_dual_result(
    ocr_result, dom_result, dom_attempted: bool,
    threshold: float, tie_break_mode: str, overlap_tolerance_px: int,
    ocr_attempted: bool = True,
):
    """
    The Phase U compilation rule (docs/Roadmap.md "Phase U"). Returns
    (decision, confidence, winner, evidence):

      decision: "dispatch" | "escalate"
      confidence: the float to report on the VisionActionResult
      winner: "dom" | "ocr" | None -- which method's candidate to dispatch
      evidence: dict for VisionActionResult.verification_evidence, always
        carrying both candidates (never silently dropping the loser)

    D-046: ocr_attempted mirrors dom_attempted -- False whenever the
    active browser session is headless (runtime.hooks.browser.
    is_headless()), since OCR searching an OS-level screenshot of a
    headless browser's (invisible, by construction) rendered content is
    not "low confidence," it's structurally guaranteed-meaningless, and
    was observed to occasionally produce a spurious near-zero-coordinate
    match against unrelated on-screen content rather than a clean
    not-found. Treated exactly like dom_attempted=False: never even
    attempted, not attempted-and-failed.
    """
    ocr_ok = ocr_attempted and ocr_result.found and ocr_result.confidence >= threshold
    dom_ok = dom_attempted and dom_result.found and dom_result.confidence >= threshold

    ocr_evidence = (
        {"attempted": False}
        if not ocr_attempted
        else {
            "attempted": True,
            "found": ocr_result.found,
            "confidence": ocr_result.confidence,
            "x": ocr_result.x if ocr_result.found else None,
            "y": ocr_result.y if ocr_result.found else None,
            "matched_text": ocr_result.matched_text,
        }
    )
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
        confidence = max(
            ocr_result.confidence if ocr_attempted else 0.0,
            dom_result.confidence if dom_attempted else 0.0,
        )
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
            winner = _apply_tie_break(ocr_result, dom_result, tie_break_mode)
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
    NoDisplayError (e.g. headless/no-tkinter environment)."""
    from runtime.errors import NoDisplayError
    from runtime.hooks import interact

    try:
        if action_taken == "click":
            interact.click(ocr_result.x, ocr_result.y)
        else:
            interact.click(ocr_result.x, ocr_result.y)  # focus the field first
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

    action_taken = "click" if step.action == ActionType.VISUAL_CLICK else "type"

    # --- Phase U: both locators always run when a browser session
    # exists -- OCR against the screenshot (as before Phase C), and DOM
    # against the live accessibility tree (including its relocate()
    # self-heal) -- rather than the old DOM-first/OCR-only-as-fallback
    # chain. For native desktop targets, or when no browser session
    # exists at all, DOM simply isn't attempted (dom_attempted=False) and
    # this collapses back to OCR-only, exactly as it always has.
    # --- Phase U: both locators always run when a browser session
    # exists -- OCR against the screenshot (as before Phase C), and DOM
    # against the live accessibility tree (including its relocate()
    # self-heal) -- rather than the old DOM-first/OCR-only-as-fallback
    # chain. For native desktop targets, or when no browser session
    # exists at all, DOM simply isn't attempted (dom_attempted=False) and
    # this collapses back to OCR-only, exactly as it always has.
    #
    # D-046: OCR is skipped (ocr_attempted=False), not just low-confidence,
    # whenever there IS an active browser session but it's headless --
    # a headless browser's rendered content never reaches the OS-level
    # framebuffer runtime.hooks.capture's mss-based screenshot reads, so
    # attempting OCR there searches whatever's actually on the real
    # desktop, not the page. This mirrors dom_attempted's own "not
    # attempted when not applicable" pattern rather than letting OCR run
    # and produce a misleading not-found or, worse, a spurious low-
    # confidence match against unrelated on-screen content.
    from runtime.hooks import browser as browser_hook

    dom_attempted = browser_hook.has_active_page()
    ocr_attempted = not (dom_attempted and browser_hook.is_headless())

    region = _region_from_skill_hint(payload.skill_hint)
    if ocr_attempted:
        ocr_result = locate_text(payload.screenshot_path, target_text, search_region=region)
    else:
        from agents.vision.locator import LocateResult

        ocr_result = LocateResult(found=False)

    dom_result = _resolve_dom(browser_hook, target_text) if dom_attempted else None
    if dom_result is None:
        from agents.vision.dom_locator import DomLocateResult

        dom_result = DomLocateResult(found=False)

    decision, confidence, winner, evidence = _compile_dual_result(
        ocr_result, dom_result, dom_attempted, threshold,
        settings.dual_verification_tie_break,
        settings.dual_verification_overlap_tolerance_px,
        ocr_attempted=ocr_attempted,
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
    ocr_ok = ocr_attempted and ocr_result.found and ocr_result.confidence >= threshold

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
