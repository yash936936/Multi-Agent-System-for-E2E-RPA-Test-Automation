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


def test_shape_based_detection_generalizes_to_unseen_phrasing_without_keyword_list(monkeypatch):
    """
    The point of the shape-based rewrite: it should handle descriptive
    sentences that were never explicitly anticipated by any keyword list
    (no "page"/"homepage"/"loaded"/"rendered" words at all here), unlike
    the previous regex approach which only matched specific vocabulary.
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
            return "Dashboard Overview\nRecent Activity\nSettings"

    monkeypatch.setitem(__import__("sys").modules, "pytesseract", FakePytesseract)
    monkeypatch.setitem(__import__("sys").modules, "PIL", type("m", (), {"Image": FakeImage}))

    # No "page"/"loaded"/"rendered"/"visible" anywhere -- the old regex
    # would have treated this as literal text to search for and failed.
    assert check_assertion(
        "fake.png",
        "Everything on the dashboard appears to be working correctly and as expected.",
    ) is True


def test_short_specific_label_is_not_swallowed_by_the_sentence_heuristic(monkeypatch):
    """A short, specific literal target -- even one containing common
    short words -- must still go through normal literal matching, not
    get misclassified as a descriptive sentence."""
    from agents.vision import locator

    calls = {}

    def fake_locate_text(screenshot_path, target_description, min_ratio=0.55, search_region=None):
        calls["target"] = target_description
        return locator.LocateResult(found=True, matched_text=target_description, confidence=0.9)

    monkeypatch.setattr("agents.vision.assertions.locate_text", fake_locate_text)

    assert check_assertion("fake.png", "Order Confirmed") is True
    assert calls["target"] == "Order Confirmed"


# --------------------------------------------------------------------------
# AD1 (docs/decisions.md D-060) -- explicit assertion_kind from the planner
# --------------------------------------------------------------------------

def test_explicit_page_rendered_kind_bypasses_shape_inference(monkeypatch):
    """
    A short literal-looking expected_state (which the old shape-based
    inference would have sent through locate_text) must still be treated
    as a structural "did anything render" check when the planner
    explicitly says assertion_kind="page_rendered" -- the whole point of
    AD1 is that the planner's stated intent wins over guessing from the
    string's shape.
    """
    from agents.vision.assertions import check_assertion_detailed

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
            return "Home Work About Contact"

    monkeypatch.setitem(__import__("sys").modules, "pytesseract", FakePytesseract)
    monkeypatch.setitem(__import__("sys").modules, "PIL", type("m", (), {"Image": FakeImage}))

    # "dashboard" alone is short/literal-shaped -- old inference would try
    # locate_text and fail since it's not literally on screen. With
    # assertion_kind="page_rendered" it must pass purely because *some*
    # real content rendered.
    detail = check_assertion_detailed("fake.png", "dashboard", assertion_kind="page_rendered")
    assert detail["passed"] is True
    assert detail["method"] == "structural_sentinel"
    assert detail["kind_source"] == "explicit"


def test_explicit_literal_text_kind_does_not_fall_back_to_structural(monkeypatch):
    """
    A long, sentence-shaped expected_state that the old inference would
    have guessed was "descriptive" (and thus structural-fallback) must
    stay a strict literal-text search when assertion_kind="literal_text"
    is explicit -- no silent fallback to "well, something rendered."
    """
    from agents.vision.assertions import check_assertion_detailed

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
            return "Some completely unrelated text"

    monkeypatch.setitem(__import__("sys").modules, "pytesseract", FakePytesseract)
    monkeypatch.setitem(__import__("sys").modules, "PIL", type("m", (), {"Image": FakeImage}))

    detail = check_assertion_detailed(
        "fake.png",
        "The order confirmation banner is now visible on screen",
        assertion_kind="literal_text",
    )
    assert detail["passed"] is False
    assert detail["method"] == "literal_ocr_failed_no_fallback"
    assert detail["kind_source"] == "explicit"


def test_negative_assertion_kind_passes_when_text_absent(monkeypatch):
    """
    The real gap AD1 closes that shape-inference could never express:
    "this text must NOT appear." Passes when the target text is genuinely
    absent from the screen.
    """
    from agents.vision.assertions import check_assertion_detailed
    from agents.vision import locator

    monkeypatch.setattr(
        "agents.vision.assertions.locate_text",
        lambda *a, **k: locator.LocateResult(found=False, matched_text=None, confidence=0.0),
    )

    detail = check_assertion_detailed("fake.png", "error_banner", assertion_kind="negative")
    assert detail["passed"] is True
    assert detail["method"] == "negative_ocr"
    assert detail["kind_source"] == "explicit"


def test_negative_assertion_kind_fails_when_text_present(monkeypatch):
    """The forbidden text actually being on screen must fail a negative
    assertion -- this is the exact "wrong content rendered but reported
    fulfilled" class of bug (D-056) that a positive-only assertion model
    could never even detect."""
    from agents.vision.assertions import check_assertion_detailed
    from agents.vision import locator

    monkeypatch.setattr(
        "agents.vision.assertions.locate_text",
        lambda *a, **k: locator.LocateResult(found=True, matched_text="Error: something went wrong", confidence=0.9),
    )

    detail = check_assertion_detailed("fake.png", "error_banner", assertion_kind="negative")
    assert detail["passed"] is False
    assert detail["method"] == "negative_ocr"
    assert detail["matched_text"] == "Error: something went wrong"


def test_custom_assertion_kind_falls_back_to_inference_but_marks_kind_source(monkeypatch):
    """"custom" has no built-in strict check, so behavior matches the
    same shape-inference used for legacy (assertion_kind=None) specs --
    but kind_source must say "inferred" either way, since no strict
    verification actually happened for either "custom" or None."""
    from agents.vision.assertions import check_assertion_detailed
    from agents.vision import locator

    monkeypatch.setattr(
        "agents.vision.assertions.locate_text",
        lambda *a, **k: locator.LocateResult(found=True, matched_text="Dashboard", confidence=0.9),
    )

    detail = check_assertion_detailed("fake.png", "dashboard_visible", assertion_kind="custom")
    assert detail["passed"] is True
    assert detail["kind_source"] == "inferred"


def test_none_assertion_kind_is_backward_compatible_with_legacy_specs(monkeypatch):
    """A spec generated before assertion_kind existed (assertion_kind is
    None, the default) must behave exactly as before -- shape-based
    inference, unaffected by this change."""
    from agents.vision.assertions import check_assertion_detailed

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
            return "Home Work About Contact"

    monkeypatch.setitem(__import__("sys").modules, "pytesseract", FakePytesseract)
    monkeypatch.setitem(__import__("sys").modules, "PIL", type("m", (), {"Image": FakeImage}))

    detail = check_assertion_detailed("fake.png", "page_loaded")
    assert detail["passed"] is True
    assert detail["kind_source"] == "inferred"


def test_heuristic_backend_emits_explicit_page_rendered_for_fallback(monkeypatch):
    """LocalHeuristicBackend's page_loaded fallback (used by every plain
    `aura execute --url` smoke test) must now emit assertion_kind
    explicitly rather than relying on downstream inference."""
    from agents.planner.spec_generator import LocalHeuristicBackend

    spec_dict = LocalHeuristicBackend().generate("check homepage loads")
    assert spec_dict["steps"][0]["expected_state"] == "page_loaded"
    assert spec_dict["steps"][0]["assertion_kind"] == "page_rendered"
    assert spec_dict["assertions"][0]["assertion_kind"] == "page_rendered"


def test_heuristic_backend_emits_negative_kind_for_should_not_see(monkeypatch):
    """Real gap this closes: 'should not see the error banner' previously
    had no way to be expressed as anything other than a (wrong) positive
    literal-text check for the literal phrase 'error banner'."""
    from agents.planner.spec_generator import LocalHeuristicBackend

    spec_dict = LocalHeuristicBackend().generate(
        "Given: navigate to https://example.com\nThen: user should not see the error banner"
    )
    negative_assertions = [a for a in spec_dict["assertions"] if a.get("assertion_kind") == "negative"]
    assert len(negative_assertions) == 1
    assert negative_assertions[0]["expected"] == "error_banner"


def test_heuristic_backend_emits_literal_text_kind_for_positive_assertions(monkeypatch):
    from agents.planner.spec_generator import LocalHeuristicBackend

    spec_dict = LocalHeuristicBackend().generate(
        "Given: navigate to https://example.com\nThen: user should see the dashboard"
    )
    literal_assertions = [a for a in spec_dict["assertions"] if a.get("assertion_kind") == "literal_text"]
    assert len(literal_assertions) == 1
    assert literal_assertions[0]["expected"] == "dashboard"
