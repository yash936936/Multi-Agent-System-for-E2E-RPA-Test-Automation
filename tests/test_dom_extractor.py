"""
Tests for agents/vision/dom_extractor.py -- covers the parts that don't
require a live Playwright page (this sandbox has no Chromium binary
available). The JS-injection path itself (extract_interactive_elements's
page.evaluate() call) is exercised implicitly by
tests/test_ui_audit_runner.py's mocked-browser-hook tests and, for real,
by anyone running the full suite where Chromium is actually installed.
"""
from __future__ import annotations

import pytest

from agents.vision.dom_extractor import (
    DomElement,
    extract_interactive_elements,
    to_ui_elements,
)


class _FakePage:
    """Minimal stand-in for a Playwright Page, just enough for evaluate()."""

    def __init__(self, evaluate_result=None, raise_on_evaluate: bool = False):
        self._result = evaluate_result
        self._raise = raise_on_evaluate

    def evaluate(self, script):
        if self._raise:
            raise RuntimeError("page navigated away mid-evaluate")
        return self._result


def test_extract_interactive_elements_returns_empty_list_on_evaluate_failure():
    """
    A detached/navigated-away page must degrade to an empty result, not
    propagate the exception -- callers (orchestrator/ui_audit_runner.py)
    treat DOM extraction as a best-effort supplement, never a hard
    dependency of the OCR-based audit that already succeeded.
    """
    page = _FakePage(raise_on_evaluate=True)
    assert extract_interactive_elements(page) == []


def test_extract_interactive_elements_returns_empty_list_for_none_result():
    page = _FakePage(evaluate_result=None)
    assert extract_interactive_elements(page) == []


def test_extract_interactive_elements_parses_real_shaped_js_output():
    raw = [
        {"index": 0, "tag": "button", "role": "", "name": "Login Button", "cx": 100, "cy": 50, "width": 80, "height": 30},
        {"index": 1, "tag": "div", "role": "", "name": "Menu", "cx": 20, "cy": 20, "width": 24, "height": 24},
    ]
    page = _FakePage(evaluate_result=raw)
    result = extract_interactive_elements(page)
    assert len(result) == 2
    assert isinstance(result[0], DomElement)
    assert result[0].name == "Login Button"
    assert result[0].tag == "button"
    assert result[1].tag == "div"


def test_extract_interactive_elements_tolerates_missing_optional_fields():
    """The JS side always sends every key, but the Python side shouldn't
    hard-crash if a future JS revision drops an optional one."""
    raw = [{"name": "Something"}]
    page = _FakePage(evaluate_result=raw)
    result = extract_interactive_elements(page)
    assert result[0].name == "Something"
    assert result[0].cx == 0
    assert result[0].tag == ""


@pytest.mark.parametrize(
    "cy,page_height,expected_band",
    [
        (10, 1000, "nav"),       # 1% down -> below _NAV_BAND_END (10%)
        (500, 1000, "body"),     # 50% down -> between nav and footer bands
        (950, 1000, "footer"),   # 95% down -> at/above _FOOTER_BAND_START (88%)
        (99, 1000, "nav"),       # just under the 10% nav cutoff
        (100, 1000, "body"),     # just at/over the 10% nav cutoff
        (880, 1000, "footer"),   # exactly at the 88% footer cutoff
    ],
)
def test_to_ui_elements_band_classification_matches_ui_audit_boundaries(cy, page_height, expected_band):
    """
    Band boundaries must match agents/vision/ui_audit.py's own constants
    exactly -- DOM-sourced and OCR-sourced elements are merged into one
    list downstream (orchestrator/ui_audit_runner.py), so a mismatch here
    would silently misclassify DOM elements relative to their OCR peers.
    """
    raw = [{"index": 0, "tag": "div", "role": "", "name": "Target", "cx": 50, "cy": cy, "width": 10, "height": 10}]
    page = _FakePage(evaluate_result=raw)
    result = to_ui_elements(page, page_height)
    assert len(result) == 1
    assert result[0].band == expected_band
    assert result[0].looks_interactive is True
    assert result[0].text == "Target"
    assert result[0].cx == 50
    assert result[0].cy == cy


def test_to_ui_elements_falls_back_to_default_page_height_safely():
    """A falsy page_height (0/None) must not raise ZeroDivisionError."""
    raw = [{"index": 0, "tag": "div", "role": "", "name": "Target", "cx": 5, "cy": 5, "width": 1, "height": 1}]
    page = _FakePage(evaluate_result=raw)
    result = to_ui_elements(page, 0)
    assert len(result) == 1
    assert result[0].band == "nav"  # frac defaults to 0.0 when page_height is falsy


def test_to_ui_elements_empty_when_extraction_fails():
    page = _FakePage(raise_on_evaluate=True)
    assert to_ui_elements(page, 1000) == []
