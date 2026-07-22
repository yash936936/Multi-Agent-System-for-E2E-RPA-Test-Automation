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


def test_llm_generated_sentence_expected_state_is_treated_as_structural(monkeypatch):
    """
    Regression test: CloudLLMBackend/HermesAgentBackend planners often
    synthesize a full descriptive sentence for expected_state -- e.g. "The
    personal portfolio page is fully loaded and visible" -- instead of a
    short literal-text slug like "dashboard_visible". No real webpage
    displays that exact sentence, so the old code (which only special-cased
    the exact "page_loaded"/"page loaded" slug) treated it as literal OCR
    text to search for and failed on every real run, regardless of whether
    the page actually rendered -- confirmed against a real run against a
    live Vercel-hosted site with 5+ real nav/footer links visible.
    """

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
            return "Home Work About Contact\nYash - AI Engineer"

    monkeypatch.setitem(__import__("sys").modules, "pytesseract", FakePytesseract)
    monkeypatch.setitem(__import__("sys").modules, "PIL", type("m", (), {"Image": FakeImage}))

    assert check_assertion("fake.png", "The personal portfolio page is fully loaded and visible") is True
    assert check_assertion(
        "fake.png",
        "The page is fully loaded and elements such as Home, Work, About, and Contact are visible.",
    ) is True


def test_homepage_and_similar_compound_phrasing_is_also_treated_as_structural(monkeypatch):
    """
    Regression test: the generic-sentence regex originally required a
    standalone word "page" (\\bpage\\b), which does NOT match "page"
    embedded inside "homepage" (word-boundary rules require a transition
    between word/non-word characters, and "home"+"page" has none). A real
    CloudLLMBackend-generated spec assertion -- "The portfolio homepage is
    successfully rendered with all initial sections loaded." -- was
    therefore treated as literal OCR text to search for and failed on
    every real run, exactly like the original page_loaded bug, just with
    a compound-word phrasing the original fix didn't anticipate.
    """

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
            return "Home Work About Contact\nAwaken your thinking partner"

    monkeypatch.setitem(__import__("sys").modules, "pytesseract", FakePytesseract)
    monkeypatch.setitem(__import__("sys").modules, "PIL", type("m", (), {"Image": FakeImage}))

    assert check_assertion(
        "fake.png",
        "The portfolio homepage is successfully rendered with all initial sections loaded.",
    ) is True


def test_short_literal_expected_state_with_loaded_word_is_not_falsely_structural(monkeypatch):
    """The generic-sentence heuristic requires several words, so a short,
    specific literal target that happens to contain 'loaded' (e.g. a
    genuine on-screen label) still goes through normal literal matching
    rather than being swallowed by the structural fallback."""
    from agents.vision import locator

    calls = {}

    def fake_locate_text(screenshot_path, target_description, min_ratio=0.55, search_region=None):
        calls["target"] = target_description
        return locator.LocateResult(found=True, matched_text=target_description, confidence=0.9)

    monkeypatch.setattr("agents.vision.assertions.locate_text", fake_locate_text)

    assert check_assertion("fake.png", "upload_loaded") is True
    assert calls["target"] == "upload loaded"
