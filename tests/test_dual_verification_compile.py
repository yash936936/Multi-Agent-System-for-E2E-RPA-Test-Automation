"""
Tests for agents/vision/executor.py's Phase U OCR-then-DOM dual
verification compilation logic (decisions.md D-043).

These are deliberately pure-function/unit tests against
_compile_dual_result / _locations_overlap / _apply_tie_break directly --
no real browser or OCR engine involved -- so they run in any sandbox
regardless of whether a Chromium binary is available (unlike
tests/test_executor_dom_path.py's live-browser integration tests).
"""
from __future__ import annotations

from agents.vision.dom_locator import DomLocateResult
from agents.vision.executor import _apply_tie_break, _compile_dual_result, _locations_overlap
from agents.vision.locator import LocateResult


def _ocr(found=True, x=100, y=100, confidence=0.9, matched_text="Login Button"):
    return LocateResult(found=found, x=x, y=y, confidence=confidence, matched_text=matched_text)


def _dom(found=True, confidence=0.9, matched_text="Login Button", bbox=None, role="button"):
    if bbox is None and found:
        bbox = {"x": 90, "y": 90, "width": 60, "height": 20}
    return DomLocateResult(found=found, confidence=confidence, matched_text=matched_text, bbox=bbox, role=role)


# --------------------------------------------------------------------------
# _locations_overlap
# --------------------------------------------------------------------------

def test_overlap_true_when_ocr_point_inside_dom_bbox():
    ocr = _ocr(x=110, y=95)
    dom = _dom(bbox={"x": 90, "y": 90, "width": 60, "height": 20})
    assert _locations_overlap(ocr, dom, tolerance_px=10) is True


def test_overlap_false_when_locations_genuinely_differ():
    ocr = _ocr(x=500, y=500)
    dom = _dom(bbox={"x": 90, "y": 90, "width": 60, "height": 20})
    assert _locations_overlap(ocr, dom, tolerance_px=10) is False


def test_overlap_respects_tolerance_expansion():
    ocr = _ocr(x=160, y=90)  # just past the raw bbox edge (90+60=150)
    dom = _dom(bbox={"x": 90, "y": 90, "width": 60, "height": 20})
    assert _locations_overlap(ocr, dom, tolerance_px=5) is False
    assert _locations_overlap(ocr, dom, tolerance_px=15) is True


def test_overlap_false_when_dom_bbox_missing():
    ocr = _ocr()
    dom = _dom(bbox=None, found=True)
    dom.bbox = None
    assert _locations_overlap(ocr, dom, tolerance_px=10) is False


# --------------------------------------------------------------------------
# _apply_tie_break
# --------------------------------------------------------------------------

def test_tie_break_prefer_dom():
    ocr = _ocr(confidence=0.95)
    dom = _dom(confidence=0.60)
    assert _apply_tie_break(ocr, dom, "prefer_dom") == "dom"


def test_tie_break_prefer_ocr():
    ocr = _ocr(confidence=0.60)
    dom = _dom(confidence=0.95)
    assert _apply_tie_break(ocr, dom, "prefer_ocr") == "ocr"


def test_tie_break_highest_confidence_picks_dom_when_higher():
    ocr = _ocr(confidence=0.60)
    dom = _dom(confidence=0.90)
    assert _apply_tie_break(ocr, dom, "highest_confidence") == "dom"


def test_tie_break_highest_confidence_picks_ocr_when_higher():
    ocr = _ocr(confidence=0.90)
    dom = _dom(confidence=0.60)
    assert _apply_tie_break(ocr, dom, "highest_confidence") == "ocr"


def test_tie_break_falls_back_to_highest_confidence_on_unrecognized_value():
    ocr = _ocr(confidence=0.90)
    dom = _dom(confidence=0.60)
    assert _apply_tie_break(ocr, dom, "some_typo") == "ocr"


# --------------------------------------------------------------------------
# _compile_dual_result
# --------------------------------------------------------------------------

def test_both_agree_dispatches_dual_confirmed_with_strongest_confidence():
    ocr = _ocr(confidence=0.80, x=100, y=95)
    dom = _dom(confidence=0.92, bbox={"x": 90, "y": 90, "width": 60, "height": 20})
    decision, confidence, winner, evidence = _compile_dual_result(
        ocr, dom, dom_attempted=True, threshold=0.55,
        tie_break_mode="highest_confidence", overlap_tolerance_px=10,
    )
    assert decision == "dispatch"
    assert confidence == 0.92
    assert winner == "dom"
    assert evidence["verification_method"] == "dual-method-confirmed"
    assert evidence["agreement"] is True
    assert evidence["tie_break_applied"] is None


def test_both_disagree_applies_tie_break_and_records_both_candidates():
    ocr = _ocr(confidence=0.80, x=500, y=500, matched_text="Sign Up")
    dom = _dom(confidence=0.70, bbox={"x": 90, "y": 90, "width": 60, "height": 20}, matched_text="Login Button")
    decision, confidence, winner, evidence = _compile_dual_result(
        ocr, dom, dom_attempted=True, threshold=0.55,
        tie_break_mode="prefer_dom", overlap_tolerance_px=10,
    )
    assert decision == "dispatch"
    assert winner == "dom"
    assert confidence == 0.70
    assert evidence["verification_method"] == "dual-method-confirmed"
    assert evidence["agreement"] is False
    assert evidence["tie_break_applied"] == "prefer_dom"
    # Both candidates recorded -- the losing one is never silently dropped.
    assert evidence["ocr"]["matched_text"] == "Sign Up"
    assert evidence["dom"]["matched_text"] == "Login Button"


def test_only_ocr_found_is_single_method():
    ocr = _ocr(confidence=0.80)
    dom = _dom(found=False, confidence=0.0, bbox=None)
    decision, confidence, winner, evidence = _compile_dual_result(
        ocr, dom, dom_attempted=True, threshold=0.55,
        tie_break_mode="highest_confidence", overlap_tolerance_px=10,
    )
    assert decision == "dispatch"
    assert winner == "ocr"
    assert confidence == 0.80
    assert evidence["verification_method"] == "single-method"
    assert evidence["agreement"] is None


def test_only_dom_found_is_single_method():
    ocr = _ocr(found=False, confidence=0.1)
    dom = _dom(confidence=0.80)
    decision, confidence, winner, evidence = _compile_dual_result(
        ocr, dom, dom_attempted=True, threshold=0.55,
        tie_break_mode="highest_confidence", overlap_tolerance_px=10,
    )
    assert decision == "dispatch"
    assert winner == "dom"
    assert confidence == 0.80
    assert evidence["verification_method"] == "single-method"


def test_dom_not_attempted_at_all_is_single_method_ocr():
    """No browser session -- DOM path isn't applicable, not "tried and
    failed." Native-desktop/no-session targets must still work exactly as
    before Phase C ever existed."""
    ocr = _ocr(confidence=0.80)
    dom = DomLocateResult(found=False)
    decision, confidence, winner, evidence = _compile_dual_result(
        ocr, dom, dom_attempted=False, threshold=0.55,
        tie_break_mode="highest_confidence", overlap_tolerance_px=10,
    )
    assert decision == "dispatch"
    assert winner == "ocr"
    assert evidence["verification_method"] == "single-method"
    assert evidence["dom"] == {"attempted": False}


def test_neither_found_escalates_with_both_candidates_recorded():
    ocr = _ocr(found=False, confidence=0.2, x=0, y=0)
    dom = _dom(found=False, confidence=0.3, bbox=None)
    decision, confidence, winner, evidence = _compile_dual_result(
        ocr, dom, dom_attempted=True, threshold=0.55,
        tie_break_mode="highest_confidence", overlap_tolerance_px=10,
    )
    assert decision == "escalate"
    assert winner is None
    assert confidence == 0.3
    assert evidence["verification_method"] is None
    assert evidence["ocr"]["found"] is False
    assert evidence["dom"]["found"] is False


def test_neither_found_and_dom_not_attempted_escalates_on_ocr_confidence_only():
    ocr = _ocr(found=False, confidence=0.2)
    dom = DomLocateResult(found=False)
    decision, confidence, winner, evidence = _compile_dual_result(
        ocr, dom, dom_attempted=False, threshold=0.55,
        tie_break_mode="highest_confidence", overlap_tolerance_px=10,
    )
    assert decision == "escalate"
    assert confidence == 0.2
