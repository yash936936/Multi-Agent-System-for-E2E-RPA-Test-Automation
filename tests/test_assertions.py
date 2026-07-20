"""
tests/test_assertions.py

Regression coverage for the "page_loaded" assertion bug: check_assertion()
used to treat "page_loaded" as literal on-screen text to OCR-search for
("page loaded"), which no real webpage displays -- so the generic
fallback assertion synthesized by LocalHeuristicBackend (used by every
`aura execute --url <url>` smoke test with no explicit Then: clause)
failed on every real run regardless of whether the page actually
rendered. Confirmed against a real run against a live Vercel-hosted site:
navigation succeeded but the run was still reported "failed" purely
because of this assertion.

check_assertion() now special-cases "page_loaded"/"page loaded" to check
for *any* rendered content (OCR finds *some* text) instead of literal
text matching. All other expected_state values are unaffected and still
go through the normal literal-text OCR match.
"""
from __future__ import annotations

from agents.vision.assertions import check_assertion


def test_page_loaded_passes_when_screenshot_has_any_readable_content(monkeypatch):
    """The actual bug: a real rendered page (any text at all -- nav
    links, headings, footer, etc.) must pass the page_loaded fallback
    assertion, even though the literal phrase 'page loaded' never
    appears anywhere on it."""

    class FakeImageHandle:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def load(self):
            pass

    class FakeImage:
        @staticmethod
        def open(path):
            return FakeImageHandle()

    class FakePytesseract:
        @staticmethod
        def image_to_string(img):
            return "Yash Malik - Portfolio\nAbout Me\nProjects\nContact"

    monkeypatch.setitem(__import__("sys").modules, "pytesseract", FakePytesseract)
    monkeypatch.setitem(__import__("sys").modules, "PIL", type("m", (), {"Image": FakeImage}))

    assert check_assertion("fake.png", "page_loaded") is True


def test_page_loaded_fails_on_genuinely_blank_screenshot(monkeypatch):
    """A blank/crashed-renderer screen (no OCR text at all) should still
    fail the page_loaded check -- the fix isn't "always pass", it's
    "check for real content instead of a literal impossible phrase"."""

    class FakeImageHandle:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def load(self):
            pass

    class FakeImage:
        @staticmethod
        def open(path):
            return FakeImageHandle()

    class FakePytesseract:
        @staticmethod
        def image_to_string(img):
            return "   "

    monkeypatch.setitem(__import__("sys").modules, "pytesseract", FakePytesseract)
    monkeypatch.setitem(__import__("sys").modules, "PIL", type("m", (), {"Image": FakeImage}))

    assert check_assertion("fake.png", "page_loaded") is False


def test_non_sentinel_expected_state_still_uses_literal_text_match(monkeypatch):
    """Real spec-authored expected_state values (e.g. 'dashboard_visible')
    must be unaffected by the page_loaded special-case -- still literal
    OCR text matching via locate_text."""
    from agents.vision import locator

    calls = {}

    def fake_locate_text(screenshot_path, target_description, min_ratio=0.55, search_region=None):
        calls["target"] = target_description
        return locator.LocateResult(found=True, matched_text=target_description, confidence=0.9)

    monkeypatch.setattr("agents.vision.assertions.locate_text", fake_locate_text)

    assert check_assertion("fake.png", "dashboard_visible") is True
    assert calls["target"] == "dashboard visible"
