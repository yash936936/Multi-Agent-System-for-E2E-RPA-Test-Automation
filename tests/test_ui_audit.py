"""
tests/test_ui_audit.py

Covers agents/vision/ui_audit.py's classify_landmarks() (pure function,
no I/O) -- the comprehensive UI audit feature (nav/hero/footer/buttons
detection) requested to make AURA check a full page the way a professional
QA tester would, not just scan for error text while scrolling.
"""
from __future__ import annotations

from agents.vision.ui_audit import classify_landmarks


def test_classify_landmarks_buckets_by_y_position():
    page_height = 2000
    elements = [
        {"text": "Home", "cx": 100, "cy": 50},       # nav band (top 10% = 0-200)
        {"text": "Welcome to our product", "cx": 400, "cy": 500},  # hero band (10-45% = 200-900)
        {"text": "Some paragraph text", "cx": 400, "cy": 1200},    # body band (45-88% = 900-1760)
        {"text": "Privacy Policy", "cx": 400, "cy": 1900},         # footer band (88%+ = 1760+)
    ]
    audit = classify_landmarks(elements, page_height)

    assert [e.text for e in audit.nav_elements] == ["Home"]
    assert [e.text for e in audit.hero_elements] == ["Welcome to our product"]
    assert [e.text for e in audit.body_elements] == ["Some paragraph text"]
    assert [e.text for e in audit.footer_elements] == ["Privacy Policy"]


def test_classify_landmarks_flags_known_nav_vocabulary_as_interactive():
    elements = [{"text": "About Us", "cx": 100, "cy": 50}]
    audit = classify_landmarks(elements, 2000)
    assert audit.nav_elements[0].looks_interactive is True


def test_classify_landmarks_flags_known_cta_vocabulary_as_interactive():
    elements = [{"text": "Get Started", "cx": 400, "cy": 500}]
    audit = classify_landmarks(elements, 2000)
    assert audit.hero_elements[0].looks_interactive is True


def test_classify_landmarks_flags_short_titlecase_text_as_interactive():
    elements = [{"text": "Book a Demo", "cx": 400, "cy": 500}]
    audit = classify_landmarks(elements, 2000)
    assert audit.hero_elements[0].looks_interactive is True


def test_classify_landmarks_does_not_flag_long_body_paragraph_as_interactive():
    elements = [{
        "text": "this is a long paragraph of body copy that should not be mistaken for a button or link",
        "cx": 400, "cy": 1200,
    }]
    audit = classify_landmarks(elements, 2000)
    assert audit.body_elements[0].looks_interactive is False


def test_has_nav_true_when_nav_band_has_elements():
    elements = [{"text": "Home", "cx": 100, "cy": 50}]
    audit = classify_landmarks(elements, 2000)
    assert audit.has_nav is True


def test_has_nav_false_when_no_elements_in_nav_band():
    elements = [{"text": "Welcome", "cx": 400, "cy": 500}]
    audit = classify_landmarks(elements, 2000)
    assert audit.has_nav is False


def test_has_footer_true_when_footer_band_has_elements():
    elements = [{"text": "Copyright 2026", "cx": 400, "cy": 1950}]
    audit = classify_landmarks(elements, 2000)
    assert audit.has_footer is True


def test_has_hero_true_with_interactive_cta_even_if_alone():
    elements = [{"text": "Sign Up", "cx": 400, "cy": 500}]
    audit = classify_landmarks(elements, 2000)
    assert audit.has_hero is True


def test_has_hero_true_with_multiple_non_interactive_elements():
    elements = [
        {"text": "some long non interactive heading text here", "cx": 400, "cy": 450},
        {"text": "some long non interactive supporting text here too", "cx": 400, "cy": 550},
    ]
    audit = classify_landmarks(elements, 2000)
    assert audit.has_hero is True


def test_has_hero_false_with_only_one_non_interactive_element():
    elements = [{"text": "this is a long non interactive paragraph of hero text", "cx": 400, "cy": 500}]
    audit = classify_landmarks(elements, 2000)
    assert audit.has_hero is False


def test_classify_landmarks_handles_empty_elements():
    audit = classify_landmarks([], 2000)
    assert audit.has_nav is False
    assert audit.has_footer is False
    assert audit.has_hero is False
    assert audit.interactive_elements == []


def test_classify_landmarks_handles_zero_page_height_gracefully():
    audit = classify_landmarks([{"text": "Home", "cx": 100, "cy": 50}], 0)
    assert audit.has_nav is False
    assert audit.nav_elements == []


def test_interactive_elements_aggregates_across_all_bands():
    elements = [
        {"text": "Home", "cx": 100, "cy": 50},           # nav, interactive
        {"text": "Get Started", "cx": 400, "cy": 500},   # hero, interactive
        {"text": "Privacy Policy", "cx": 400, "cy": 1900},  # footer, interactive (footer vocab)
        {"text": "just some body text here that is long", "cx": 400, "cy": 1200},  # body, not interactive
    ]
    audit = classify_landmarks(elements, 2000)
    interactive_texts = {e.text for e in audit.interactive_elements}
    assert interactive_texts == {"Home", "Get Started", "Privacy Policy"}
