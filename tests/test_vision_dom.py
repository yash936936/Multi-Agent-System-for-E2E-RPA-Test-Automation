"""Merged test file: test_vision_dom.py
Consolidated from: test_dom_extractor.py, test_dom_locator.py, test_dom_change_detector.py, test_locator_ocr_fixes.py, test_vision.py, test_executor_dom_path.py, test_dual_verification_compile.py
All original test functions preserved 1:1. Colliding fixture/helper names
renamed with a source-file suffix to avoid silent shadowing across sections.
"""
from __future__ import annotations
import pytest
from agents.vision.dom_extractor import (
    DomElement,
    extract_interactive_elements,
    to_ui_elements,
)
from tests.conftest_local_server import make_server, server_url
from agents.vision.dom_change_detector import arm, read_result
from agents.vision.locator import _group_lines, locate_text
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from agents.vision.assertions import check_assertion
from agents.vision.executor import execute_step
from agents.vision.locator import locate_text
from orchestrator.schemas import ActionType, TestStep, VisionStepInput
from target_app.demo_login_app import resolve_font
from agents.vision.dom_locator import DomLocateResult
from agents.vision.executor import _apply_tie_break, _compile_dual_result, _locations_overlap
from agents.vision.locator import LocateResult


# ============================================================================
# ---- from test_dom_extractor.py ----
# ============================================================================
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
        (500, 1000, "body"),     # 50% down -> between hero and footer bands
        (950, 1000, "footer"),   # 95% down -> at/above _FOOTER_BAND_START (88%)
        (99, 1000, "nav"),       # just under the 10% nav cutoff
        (100, 1000, "hero"),     # just at/over the 10% nav cutoff -> into the hero band
        (880, 1000, "footer"),   # exactly at the 88% footer cutoff
    ],
)
def test_to_ui_elements_band_classification_matches_ui_audit_boundaries(cy, page_height, expected_band):
    """
    Band boundaries must match agents/vision/ui_audit.py's own constants
    exactly -- DOM-sourced and OCR-sourced elements are merged into one
    list downstream (orchestrator/ui_audit_runner.py), so a mismatch here
    would silently misclassify DOM elements relative to their OCR peers.

    Includes the hero band (10%-45%) -- DOM-sourced elements previously
    only ever landed in nav/body/footer, meaning a DOM-only hero control
    (e.g. an icon-only carousel arrow with no OCR-readable text) never
    counted toward has_hero even when a real one was on screen.
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

# ============================================================================
# ---- from test_dom_locator.py ----
# ============================================================================
PAGE_V1 = b"""
<html><body>
  <nav><a href="/about">About Us</a></nav>
  <button>Login Button</button>
  <input type="text" placeholder="Username" aria-label="Username Field" />
</body></html>
"""

# Same page, but the button's accessible name drifted slightly (structure
# drift) -- relocate_dom() should still find it via fuzzy re-scoring.
PAGE_V2_DRIFTED = b"""
<html><body>
  <nav><a href="/about">About Us</a></nav>
  <button>Login</button>
  <input type="text" placeholder="Username" aria-label="Username Field" />
</body></html>
"""


@pytest.fixture(autouse=True)
def _reset_browser_session():
    from runtime.hooks import browser

    browser.close()
    yield
    browser.close()


def _page_for(html: bytes):
    from runtime.hooks import browser

    srv = make_server(html)
    browser.open_url(server_url(srv), wait_seconds=0.1)
    return browser.get_page(), srv


def test_locate_dom_finds_exact_button_match():
    from agents.vision.dom_locator import locate_dom

    page, srv = _page_for(PAGE_V1)
    try:
        result = locate_dom(page, "Login Button")
        assert result.found is True
        assert result.role == "button"
        assert result.confidence >= 0.55
        assert result.locator is not None
    finally:
        srv.shutdown()


def test_locate_dom_no_match_reports_top_score_not_silently_empty():
    from agents.vision.dom_locator import locate_dom

    page, srv = _page_for(PAGE_V1)
    try:
        result = locate_dom(page, "Totally Unrelated Nonexistent Target Xyz")
        assert result.found is False
        # Scrapling-style UX: log the top score even on failure.
        assert result.top_score_seen >= 0.0
    finally:
        srv.shutdown()


def test_relocate_dom_self_heals_after_structure_drift():
    from agents.vision.dom_locator import locate_dom, relocate_dom

    page, srv = _page_for(PAGE_V2_DRIFTED)
    try:
        # Primary path fails to confidently match "Login Button" against
        # the drifted text "Login" at the default 0.55 threshold territory
        # -- but relocate()'s relaxed 0.40 threshold should still resolve it.
        result = relocate_dom(page, {"name": "Login Button"})
        assert result.found is True
        assert result.strategy == "relocate"
        assert result.role == "button"
    finally:
        srv.shutdown()


def test_relocate_dom_returns_ties_count_when_ambiguous():
    from agents.vision.dom_locator import relocate_dom

    html = b"""
    <html><body>
      <button>Submit</button>
      <button>Submit</button>
    </body></html>
    """
    page, srv = _page_for(html)
    try:
        result = relocate_dom(page, {"name": "Submit"})
        assert result.found is True
        assert result.ambiguous_count == 2
    finally:
        srv.shutdown()


def test_locate_dom_populates_bbox_for_phase_u_overlap_check():
    """
    Phase U (decisions.md D-043): locate_dom must populate `bbox` on a
    successful match so executor.py's OCR/DOM overlap check has real
    coordinates to compare against -- not left None for every real match.
    """
    from agents.vision.dom_locator import locate_dom

    page, srv = _page_for(PAGE_V1)
    try:
        result = locate_dom(page, "Login Button")
        assert result.found is True
        assert result.bbox is not None
        assert set(result.bbox.keys()) >= {"x", "y", "width", "height"}
    finally:
        srv.shutdown()

# ============================================================================
# ---- from test_dom_change_detector.py ----
# ============================================================================
class FakePage:
    def __init__(self, arm_result=True, read_result_value=None, raise_on_arm=False, raise_on_read=False):
        self._arm_result = arm_result
        self._read_result_value = read_result_value or {"count": 0, "urlBefore": "http://x", "urlAfter": "http://x", "sample": []}
        self._raise_on_arm = raise_on_arm
        self._raise_on_read = raise_on_read
        self.arm_calls = []
        self.read_calls = 0

    def evaluate(self, js, arg=None):
        if "__aura_mutations = []" in js:  # the arm script
            if self._raise_on_arm:
                raise RuntimeError("page closed mid-arm")
            self.arm_calls.append(arg)
            return self._arm_result
        else:  # the read script
            if self._raise_on_read:
                raise RuntimeError("page navigated away, no __aura_mutations in this document")
            self.read_calls += 1
            return self._read_result_value


def test_arm_passes_ignore_selectors_through_and_returns_true_on_success():
    page = FakePage()
    ok = arm(page, ["[data-ad]", ".analytics-beacon"])
    assert ok is True
    assert page.arm_calls == [["[data-ad]", ".analytics-beacon"]]


def test_arm_defaults_to_empty_list_when_no_selectors_given():
    page = FakePage()
    arm(page)
    assert page.arm_calls == [[]]


def test_arm_degrades_to_false_on_exception_never_raises():
    page = FakePage(raise_on_arm=True)
    assert arm(page) is False


def test_read_result_reports_mutated_true_when_mutations_recorded():
    page = FakePage(read_result_value={"count": 3, "urlBefore": "http://x", "urlAfter": "http://x", "sample": [{"type": "childList", "tag": "DIV"}]})
    result = read_result(page)
    assert result.armed is True
    assert result.mutated is True
    assert result.mutation_count == 3
    assert result.url_changed is False
    assert len(result.sample_mutations) == 1


def test_read_result_reports_url_changed_independent_of_mutation_count():
    """A real navigation with zero recorded DOM mutations (the observer's
    document context got destroyed before anything else was recorded)
    must still count as a real change via url_changed."""
    page = FakePage(read_result_value={"count": 0, "urlBefore": "http://x/a", "urlAfter": "http://x/b", "sample": []})
    result = read_result(page)
    assert result.mutated is False
    assert result.url_changed is True


def test_read_result_degrades_to_unarmed_on_exception_never_raises():
    page = FakePage(raise_on_read=True)
    result = read_result(page)
    assert result.armed is False
    assert result.error is not None
    assert result.mutated is False  # safe default, not an exception propagating up


def test_read_result_respects_settle_wait(monkeypatch):
    slept = {}
    monkeypatch.setattr("agents.vision.dom_change_detector.time.sleep", lambda s: slept.setdefault("seconds", s))
    page = FakePage()
    read_result(page, settle_wait_seconds=0.5)
    assert slept["seconds"] == 0.5

# ============================================================================
# ---- from test_locator_ocr_fixes.py ----
# ============================================================================
def test_locate_text_missing_screenshot_fails_closed_not_a_crash():
    """A missing screenshot_path must return found=False, not raise --
    Phase U calls this unconditionally even when a browser session is
    expected to resolve everything via DOM, so a placeholder/nonexistent
    path is an expected input, not an error condition."""
    result = locate_text("/tmp/definitely_does_not_exist_aura_test.png", "Login Button")
    assert result.found is False
    assert result.confidence == 0.0


def test_locate_text_unreadable_file_fails_closed_not_a_crash(tmp_path):
    """A path that exists but isn't a valid image (e.g. a truncated/
    corrupt file, or a stray non-image file at that path) must also fail
    closed via the same OSError branch PIL's UnidentifiedImageError
    subclasses, not propagate a raw exception."""
    bad_file = tmp_path / "not_an_image.png"
    bad_file.write_bytes(b"this is not valid image data")
    result = locate_text(str(bad_file), "Login Button")
    assert result.found is False
    assert result.confidence == 0.0


def _ocr_row(text, conf, left, top, width=None, height=16, block=1, par=1, line=1):
    width = width if width is not None else max(8, len(text) * 10)
    return {"text": text, "conf": conf, "left": left, "top": top, "width": width, "height": height, "block_num": block, "par_num": par, "line_num": line}


def _build_ocr_dict(rows: list[dict]) -> dict:
    keys = ["text", "conf", "left", "top", "width", "height", "block_num", "par_num", "line_num"]
    return {k: [r[k] for r in rows] for k in keys}


def test_group_lines_excludes_low_confidence_noise_from_text_and_bbox():
    """
    Reproduces the real captured bug: a genuine 'Login Button' detection
    (high confidence) sharing tesseract's line grouping with low-
    confidence noise-glyph misreads on either side. The noise must not
    appear in the joined text, and must not widen the bbox/skew the
    centroid.
    """
    rows = [
        _ocr_row("[", 12, left=50, top=18, width=8),       # noise glyph, low confidence
        _ocr_row("Login", 96, left=100, top=18, width=55),  # real text, high confidence
        _ocr_row("Button", 94, left=160, top=18, width=60),  # real text, high confidence
        _ocr_row("|", 8, left=280, top=19, width=6),        # noise glyph, low confidence
        _ocr_row(")", 5, left=300, top=19, width=6),        # noise glyph, low confidence
    ]
    lines = _group_lines(_build_ocr_dict(rows))

    assert len(lines) == 1
    line = lines[0]
    assert line["text"] == "Login Button", f"noise glyphs leaked into joined text: {line['text']!r}"
    # Real text spans x=[100, 220] -- centroid should be ~160, not skewed
    # toward the noise glyphs at x=50 or x=306 (which would happen if the
    # bbox spanned the full [50, 306] noise-inclusive range: cx=178).
    assert 150 <= line["cx"] <= 170, f"bbox/centroid skewed by noise glyphs: cx={line['cx']}"


def test_group_lines_all_high_confidence_words_unaffected():
    """A normal, fully-legible OCR line (all words high confidence) must
    behave exactly as before -- this fix should never filter real text."""
    rows = [
        _ocr_row("Sign", 92, left=100, top=18, width=45),
        _ocr_row("In", 90, left=150, top=18, width=25),
    ]
    lines = _group_lines(_build_ocr_dict(rows))
    assert len(lines) == 1
    assert lines[0]["text"] == "Sign In"


def test_group_lines_missing_conf_field_does_not_filter_anything():
    """A hand-built OCR dict without a 'conf' key (e.g. an older test
    fixture, or a caller that doesn't populate it) must not have its text
    silently dropped -- the confidence filter degrades to a no-op rather
    than a false rejection when confidence data simply isn't available."""
    ocr = {
        "text": ["Login", "Button"],
        "left": [100, 160],
        "top": [18, 18],
        "width": [55, 60],
        "height": [16, 16],
        "block_num": [1, 1],
        "par_num": [1, 1],
        "line_num": [1, 1],
    }
    lines = _group_lines(ocr)
    assert len(lines) == 1
    assert lines[0]["text"] == "Login Button"


def test_group_lines_line_with_only_noise_produces_no_line():
    """If every word on a detected line is below the confidence
    threshold, that line contributes nothing -- not an empty-text line
    with a bogus bbox."""
    rows = [
        _ocr_row("|", 5, left=50, top=18, width=6),
        _ocr_row(")", 3, left=60, top=18, width=6),
    ]
    lines = _group_lines(_build_ocr_dict(rows))
    assert lines == []

# ============================================================================
# ---- from test_vision.py ----
# ============================================================================
def _font(size: int = 28) -> ImageFont.ImageFont:
    return resolve_font(size)


def make_synthetic_screenshot(tmp_path: Path, texts: list[tuple[str, tuple[int, int]]], size=(800, 600), noisy: bool = False) -> Path:
    """Renders a plain white 'screenshot' with given texts at given (x, y) positions."""
    img = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(img)
    font = _font()
    for text, pos in texts:
        draw.text(pos, text, fill="black", font=font)

    if noisy:
        # Draw an overlapping box to obscure part of the text, simulating a
        # partially-hidden/obscured UI element -> should drop confidence.
        for text, pos in texts:
            x, y = pos
            draw.rectangle([x, y, x + 40, y + 30], fill="white")

    path = tmp_path / "screenshot.png"
    img.save(path)
    return path


@pytest.fixture()
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


def test_locate_text_finds_clear_button_above_threshold(tmp_dir: Path):
    path = make_synthetic_screenshot(tmp_dir, [("Login Button", (300, 40))])
    result = locate_text(path, "Login Button")
    assert result.found is True
    assert result.confidence >= 0.75
    assert 280 <= result.x <= 500
    assert 30 <= result.y <= 90


def test_locate_text_obscured_target_falls_below_threshold(tmp_dir: Path):
    # Render text then immediately paint white over most of it to simulate
    # an element that's covered/obscured -- OCR should fail to read it
    # cleanly, so either not found or found with low confidence.
    img = Image.new("RGB", (800, 600), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((300, 40), "Login Button", fill="black", font=_font())
    # obscure it entirely
    draw.rectangle([290, 30, 520, 80], fill="white")
    path = tmp_dir / "obscured.png"
    img.save(path)

    result = locate_text(path, "Login Button")
    assert (not result.found) or result.confidence < 0.75


def test_locate_text_returns_not_found_for_absent_target(tmp_dir: Path):
    path = make_synthetic_screenshot(tmp_dir, [("Login Button", (300, 40))])
    result = locate_text(path, "Delete Account")
    assert result.found is False


def test_execute_step_assert_does_not_escalate_with_no_target_description(tmp_dir: Path):
    """
    Regression test: ASSERT steps carry their check in expected_state, not
    target_description/field_description. Before this fix, execute_step had
    no branch for ActionType.ASSERT at all -- it fell through to the
    click/type path, which always saw target_text=None for assert steps and
    unconditionally returned confidence=0.0/escalate=True, no matter what
    was actually on screen. That meant run_engine's own expected_state
    check (gated on `not result.escalate`) could never run either, so every
    single assert step escalated regardless of real page content.
    """
    path = make_synthetic_screenshot(tmp_dir, [("Welcome", (250, 60))])
    step = TestStep(step_id=1, action=ActionType.ASSERT, expected_state="page_loaded")
    payload = VisionStepInput(step=step, screenshot_path=str(path))

    result = execute_step(payload)
    assert result.escalate is False
    assert result.action_taken == "none"


def test_execute_step_click_above_threshold_reports_success(tmp_dir: Path):
    path = make_synthetic_screenshot(tmp_dir, [("Submit Button", (250, 60))])
    step = TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Submit Button")
    payload = VisionStepInput(step=step, screenshot_path=str(path))

    result = execute_step(payload)
    assert result.action_taken == "click"
    assert result.escalate is False
    assert result.confidence >= 0.75
    assert result.target_coords is not None


def test_execute_step_below_threshold_escalates(tmp_dir: Path):
    path = make_synthetic_screenshot(tmp_dir, [("Submit Button", (250, 60))])
    step = TestStep(step_id=2, action=ActionType.VISUAL_CLICK, target_description="Nonexistent Widget")
    payload = VisionStepInput(step=step, screenshot_path=str(path))

    result = execute_step(payload)
    assert result.action_taken == "none"
    assert result.escalate is True


def test_execute_step_type_text_locates_field(tmp_dir: Path):
    path = make_synthetic_screenshot(tmp_dir, [("Username Field", (200, 100))])
    step = TestStep(step_id=3, action=ActionType.TYPE_TEXT, field_description="Username Field", value_ref="synthetic.username")
    payload = VisionStepInput(step=step, screenshot_path=str(path), value="jane.doe")

    result = execute_step(payload)
    assert result.action_taken == "type"
    assert result.escalate is False


def test_check_assertion_passes_when_expected_text_present(tmp_dir: Path):
    path = make_synthetic_screenshot(tmp_dir, [("Dashboard Visible", (100, 200))])
    assert check_assertion(path, "dashboard_visible") is True


def test_check_assertion_fails_when_expected_text_absent(tmp_dir: Path):
    path = make_synthetic_screenshot(tmp_dir, [("Login Button", (300, 40))])
    assert check_assertion(path, "dashboard_visible") is False


def test_execute_step_navigate_url_opens_browser_and_does_not_escalate(tmp_dir: Path, monkeypatch):
    opened = {}

    def fake_open_url(url, wait_seconds=2.5, new_window=False):
        opened["url"] = url
        return url

    import runtime.hooks.browser as browser_hook

    monkeypatch.setattr(browser_hook, "open_url", fake_open_url)

    path = make_synthetic_screenshot(tmp_dir, [("Welcome", (100, 100))])
    step = TestStep(step_id=1, action=ActionType.NAVIGATE_URL, url="https://example.com")
    payload = VisionStepInput(step=step, screenshot_path=str(path))

    result = execute_step(payload)
    assert result.action_taken == "navigate"
    assert result.escalate is False
    assert opened["url"] == "https://example.com"


def test_execute_step_navigate_url_missing_url_escalates(tmp_dir: Path):
    path = make_synthetic_screenshot(tmp_dir, [("Welcome", (100, 100))])
    step = TestStep(step_id=1, action=ActionType.NAVIGATE_URL)
    payload = VisionStepInput(step=step, screenshot_path=str(path))

    result = execute_step(payload)
    assert result.action_taken == "none"
    assert result.escalate is True


def test_execute_step_navigate_url_no_display_escalates(tmp_dir: Path, monkeypatch):
    import runtime.hooks.browser as browser_hook

    def raise_no_display(url, wait_seconds=2.5, new_window=False):
        raise browser_hook.NoDisplayError("no browser here")

    monkeypatch.setattr(browser_hook, "open_url", raise_no_display)

    path = make_synthetic_screenshot(tmp_dir, [("Welcome", (100, 100))])
    step = TestStep(step_id=1, action=ActionType.NAVIGATE_URL, url="https://example.com")
    payload = VisionStepInput(step=step, screenshot_path=str(path))

    result = execute_step(payload)
    # Previously this asserted action_taken == "navigate" / escalate is
    # False -- i.e. it encoded the bug (a browser that never actually
    # opened was reported as a successful navigation) as correct
    # behavior. Fixed: no display means navigation could not be
    # confirmed, so the step must escalate rather than lie about success.
    assert result.action_taken == "none"
    assert result.escalate is True

# ============================================================================
# ---- from test_executor_dom_path.py ----
# ============================================================================
def _production_screenshot(run_id: str, step_id: int) -> str:
    """
    Captures via the actual production path (runtime.hooks.capture.
    capture_screenshot -> mss, full-OS-screen-space pixels) instead of
    live_page.screenshot() (Playwright, viewport-relative CSS-pixel
    space). This distinction only matters for tests that exercise the
    OCR-dispatch fallback path (_dispatch_ocr -> runtime.hooks.interact.
    click, which uses pyautogui in OS-screen-space) -- production always
    pairs OCR coordinates with an mss-captured screenshot, so the two
    share one coordinate space by construction. A Playwright-viewport
    screenshot fed into that same OCR-then-pyautogui-click path produces
    coordinates in the wrong space entirely, an artifact of how these
    tests capture their screenshot, not a real production bug (see the
    real Windows pytest failure this was found from: OCR "found" the
    right text, at a screenshot-relative coordinate, but the resulting
    OS-level click missed because the browser window isn't positioned at
    the OS screen's origin).
    """
    from runtime.hooks.capture import capture_screenshot

    return str(capture_screenshot(run_id, step_id))

PAGE = b"""
<html><body>
  <button onclick="document.title='clicked'">Login Button</button>
  <input type="text" aria-label="Username Field" />
</body></html>
"""


@pytest.fixture(autouse=True)
def _reset_browser_session__executor_dom_path():
    from runtime.hooks import browser

    browser.close()
    yield
    browser.close()


@pytest.fixture
def live_page():
    from runtime.hooks import browser

    srv = make_server(PAGE)
    browser.open_url(server_url(srv), wait_seconds=0.1)
    yield browser.get_page()
    srv.shutdown()


def test_visual_click_uses_dom_path_when_browser_session_active(live_page):
    step = TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login Button")
    payload = VisionStepInput(step=step, screenshot_path="unused.png")

    result = execute_step(payload)

    assert result.action_taken == "click"
    assert result.escalate is False
    assert result.confidence >= 0.55
    # Confirms the click actually dispatched through the real page, not a
    # no-op -- the page's own onclick handler changed its title.
    assert live_page.title() == "clicked"


def test_type_text_uses_dom_path_when_browser_session_active(live_page):
    step = TestStep(step_id=2, action=ActionType.TYPE_TEXT, field_description="Username Field")
    payload = VisionStepInput(step=step, screenshot_path="unused.png", value="jane.doe")

    result = execute_step(payload)

    assert result.action_taken == "type"
    assert result.escalate is False
    value = live_page.eval_on_selector("input", "el => el.value")
    assert value == "jane.doe"


def test_no_active_browser_session_falls_back_to_ocr_path(tmp_path):
    from PIL import Image, ImageDraw
    from target_app.demo_login_app import resolve_font

    img = Image.new("RGB", (400, 200), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((50, 50), "Login Button", fill="black", font=resolve_font(28))
    path = tmp_path / "shot.png"
    img.save(path)

    step = TestStep(step_id=3, action=ActionType.VISUAL_CLICK, target_description="Login Button")
    payload = VisionStepInput(step=step, screenshot_path=str(path))

    result = execute_step(payload)
    # No browser session was ever opened this test, so this must have gone
    # through the pre-existing OCR/pixel path (still works, unchanged).
    assert result.action_taken in ("click", "none")
    # Phase U: DOM wasn't applicable at all (no session) -- this must be
    # tagged single-method, not silently missing verification metadata.
    if result.action_taken == "click":
        assert result.verification_method == "single-method"
        assert result.verification_evidence["dom"] == {"attempted": False}


# --------------------------------------------------------------------------
# Phase U (decisions.md D-043): OCR-then-DOM dual verification, both
# methods always run against a live browser page.
# --------------------------------------------------------------------------

def test_dual_verification_both_agree_reports_dual_method_confirmed(live_page, tmp_path):
    """
    Both OCR (against a real screenshot of the live page) and DOM (against
    the live accessibility tree) should independently find "Login Button"
    at the same on-screen location -- real agreement, not mocked.
    """
    shot_path = _production_screenshot("dual_agree_test", 1)

    step = TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login Button")
    payload = VisionStepInput(step=step, screenshot_path=str(shot_path))

    result = execute_step(payload)

    assert result.action_taken == "click"
    assert result.escalate is False
    assert result.verification_method == "dual-method-confirmed"
    assert result.verification_evidence["ocr"]["found"] is True
    assert result.verification_evidence["dom"]["found"] is True
    # The click must have actually dispatched (via whichever method won).
    assert live_page.title() == "clicked"


def test_dual_verification_only_dom_finds_offscreen_target_is_single_method(live_page, tmp_path):
    """
    A target only resolvable via the accessibility tree (e.g. positioned
    such that OCR's screenshot-based text match won't score it, here
    simulated by asking for text OCR can't plausibly see because it's not
    rendered as visible text at all -- an aria-label-only control) should
    still dispatch, tagged single-method, not silently dropped because OCR
    didn't confirm it.
    """
    shot_path = _production_screenshot("dual_single_test", 2)

    step = TestStep(step_id=2, action=ActionType.TYPE_TEXT, field_description="Username Field")
    payload = VisionStepInput(step=step, screenshot_path=str(shot_path), value="jane.doe")

    result = execute_step(payload)

    assert result.action_taken == "type"
    assert result.escalate is False
    # DOM was attempted (live session exists) -- whatever OCR did or
    # didn't find, verification_method must reflect reality, not be None.
    assert result.verification_method in ("single-method", "dual-method-confirmed")
    value = live_page.eval_on_selector("input", "el => el.value")
    assert value == "jane.doe"


def test_dual_verification_disagreement_falls_back_when_winner_dispatch_fails(monkeypatch, live_page, tmp_path):
    """
    If the tie-break winner's dispatch fails for a display-related reason
    but the other candidate also cleared the threshold, the step must
    still succeed via the other candidate rather than reporting a false
    miss -- verified here by forcing the DOM dispatch to fail and
    confirming the OCR fallback (which independently found the same
    on-screen text) still completes the click.
    """
    import agents.vision.executor as executor_mod

    def _dispatch_dom_returns_false(dom_result, action_taken, value):
        return False

    monkeypatch.setattr(executor_mod, "_dispatch_dom", _dispatch_dom_returns_false)

    shot_path = _production_screenshot("dual_fallback_test", 1)

    step = TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login Button")
    payload = VisionStepInput(step=step, screenshot_path=str(shot_path))

    result = execute_step(payload)

    assert result.escalate is False
    assert result.verification_evidence["dispatched_via"] == "ocr"
    assert live_page.title() == "clicked"

# ============================================================================
# ---- from test_dual_verification_compile.py ----
# ============================================================================
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


# ---- merged from tests/test_form_fuzzer.py ----
"""
tests/test_form_fuzzer.py

Covers agents/vision/form_fuzzer.py -- the autonomous "fill in every field
and submit" capability added to close a real gap: `aura explore` could
click nav/footer elements and diff screenshots, but nothing in this repo
ever actually typed data into a form and pressed submit without a
hand-written spec. Unit-tests classify_field()'s keyword mapping for
real, and monkeypatches the DOM primitives (locate_dom/relocate_dom/
snapshot_elements/dom_fill/dom_click/dom_smart_back) to exercise
fuzz_form()'s orchestration logic without a live browser, matching the
existing tests/test_ui_audit_runner.py convention.
"""
from dataclasses import dataclass
from types import SimpleNamespace

import agents.vision.form_fuzzer as form_fuzzer
from agents.vision.form_fuzzer import FormFuzzResult, classify_field, fuzz_form


# ---------- classify_field ----------

def test_classify_field_maps_common_keywords():
    assert classify_field("Email Address") == "email"
    assert classify_field("Confirm Password") == "password"
    assert classify_field("Username") == "username"
    assert classify_field("Phone Number") == "phone"
    assert classify_field("Some Random Label") == "generic"


def test_classify_field_prefers_more_specific_keyword():
    # "confirm password" must match before the bare "password" entry.
    assert classify_field("Confirm your Password again") == "password"


# ---------- fuzz_form orchestration (monkeypatched DOM layer) ----------

@dataclass
class FakeLocateResult:
    found: bool
    locator: object = None


@dataclass
class FakeBackResult:
    new_tab_opened: bool = False
    new_tab_url: str = None
    went_back: bool = False


class FakeLocator:
    def __init__(self, name):
        self.name = name
        self.filled_with = None
        self.clicked = False

    def fill(self, value, timeout=5000):
        self.filled_with = value

    def click(self, timeout=5000):
        self.clicked = True


class FuzzFakePage:
    def __init__(self, url="https://example.com/signup"):
        self.url = url
        self.context = SimpleNamespace(pages=[self])

    def wait_for_load_state(self, state, timeout=5000):
        pass


def _candidates():
    return [
        {"role": "textbox", "name": "Email Address"},
        {"role": "textbox", "name": "Password"},
    ]


def test_fuzz_form_fills_every_field_and_submits(monkeypatch):
    page = FuzzFakePage()

    monkeypatch.setattr(form_fuzzer, "snapshot_elements", lambda p: _candidates())

    def fake_locate_dom(p, name):
        if name in ("Email Address", "Password"):
            return FakeLocateResult(found=True, locator=FakeLocator(name))
        if name == "submit":
            return FakeLocateResult(found=True, locator=FakeLocator("submit"))
        return FakeLocateResult(found=False)

    monkeypatch.setattr(form_fuzzer, "locate_dom", fake_locate_dom)
    monkeypatch.setattr(form_fuzzer, "relocate_dom", lambda p, last: FakeLocateResult(found=False))
    monkeypatch.setattr(form_fuzzer, "dom_smart_back", lambda p, before: FakeBackResult())

    result = fuzz_form(page, submit_label="submit", mode="realistic")

    assert isinstance(result, FormFuzzResult)
    assert len(result.filled) == 2
    field_keys = {f.field_key for f in result.filled}
    assert field_keys == {"email", "password"}
    # password value must be masked in the preview, never shown in full
    password_entry = next(f for f in result.filled if f.field_key == "password")
    assert set(password_entry.value_preview) == {"*"}
    assert result.submit_found is True
    assert result.submit_clicked is True


def test_fuzz_form_edge_case_mode_uses_malformed_generator(monkeypatch):
    page = FuzzFakePage()
    monkeypatch.setattr(form_fuzzer, "snapshot_elements", lambda p: [{"role": "textbox", "name": "Email Address"}])

    seen_locator = FakeLocator("Email Address")
    monkeypatch.setattr(form_fuzzer, "locate_dom", lambda p, name: FakeLocateResult(found=True, locator=seen_locator) if name == "Email Address" else FakeLocateResult(found=False))
    monkeypatch.setattr(form_fuzzer, "relocate_dom", lambda p, last: FakeLocateResult(found=False))
    monkeypatch.setattr(form_fuzzer, "dom_smart_back", lambda p, before: FakeBackResult())

    result = fuzz_form(page, mode="edge_case")

    assert result.filled[0].field_key == "email"
    # edge_case email generator (generator.py's "malformed" fallback / email
    # match) always produces something that isn't a plausible real address --
    # just assert it actually ran through the fill path, not left blank.
    assert seen_locator.filled_with


def test_fuzz_form_no_submit_found_still_reports_filled_fields(monkeypatch):
    page = FuzzFakePage()
    monkeypatch.setattr(form_fuzzer, "snapshot_elements", lambda p: [{"role": "textbox", "name": "Email Address"}])
    monkeypatch.setattr(form_fuzzer, "locate_dom", lambda p, name: FakeLocateResult(found=True, locator=FakeLocator(name)) if name == "Email Address" else FakeLocateResult(found=False))
    monkeypatch.setattr(form_fuzzer, "relocate_dom", lambda p, last: FakeLocateResult(found=False))

    result = fuzz_form(page)

    assert len(result.filled) == 1
    assert result.submit_found is False
    assert result.submit_clicked is False
    assert "not submitted" in result.note


def test_fuzz_form_new_tab_on_submit_is_reported_and_closed(monkeypatch):
    page = FuzzFakePage()
    monkeypatch.setattr(form_fuzzer, "snapshot_elements", lambda p: [])

    def fake_locate_dom(p, name):
        if name == "submit":
            return FakeLocateResult(found=True, locator=FakeLocator("submit"))
        return FakeLocateResult(found=False)

    monkeypatch.setattr(form_fuzzer, "locate_dom", fake_locate_dom)
    monkeypatch.setattr(form_fuzzer, "relocate_dom", lambda p, last: FakeLocateResult(found=False))

    # Simulate a new tab appearing as a side effect of clicking submit
    # (a real target="_blank" submit button), *after* fuzz_form has
    # already captured pages_before -- matching how a live browser
    # actually behaves.
    submit_locator = FakeLocator("submit")
    original_click = submit_locator.click

    def click_and_open_tab(timeout=5000):
        original_click(timeout=timeout)
        page.context.pages.append(FuzzFakePage(url="https://example.com/thank-you"))

    submit_locator.click = click_and_open_tab

    def fake_locate_dom_with_submit(p, name):
        if name == "submit":
            return FakeLocateResult(found=True, locator=submit_locator)
        return FakeLocateResult(found=False)

    monkeypatch.setattr(form_fuzzer, "locate_dom", fake_locate_dom_with_submit)

    def fake_smart_back(p, before):
        return FakeBackResult(new_tab_opened=True, new_tab_url="https://example.com/thank-you")

    monkeypatch.setattr(form_fuzzer, "dom_smart_back", fake_smart_back)

    result = fuzz_form(page)

    assert result.new_tab_opened is True
    assert result.new_tab_url == "https://example.com/thank-you"
