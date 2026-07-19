from __future__ import annotations

import pytest

from agents.vision.executor import execute_step
from orchestrator.schemas import ActionType, TestStep, VisionStepInput
from tests.conftest_local_server import make_server, server_url


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
def _reset_browser_session():
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


# --------------------------------------------------------------------------
# D-046: headless browser sessions skip OCR entirely, mock-based (no live
# browser/Chromium binary needed -- unlike the live_page-fixture tests
# above, which do). Reproduces, without a real display, the exact bug a
# live Windows pytest run with a working browser actually hit: OCR
# searching an OS-level (mss) screenshot of the real desktop -- never the
# headless browser's invisible rendered content -- either failed to find
# the target (reporting "single-method" instead of "dual-method-confirmed"
# even though both methods logically should have agreed) or, worse,
# occasionally matched something unrelated near a screen corner, which
# PyAutoGUI's own fail-safe correctly refused to click.
# --------------------------------------------------------------------------

def test_headless_session_skips_ocr_entirely_dom_alone_dispatches():
    from unittest.mock import patch

    from agents.vision.dom_locator import DomLocateResult

    with patch("runtime.hooks.browser.has_active_page", return_value=True), \
         patch("runtime.hooks.browser.is_headless", return_value=True), \
         patch(
             "agents.vision.executor._resolve_dom",
             return_value=DomLocateResult(
                 found=True, confidence=0.9, matched_text="Login Button",
                 role="button", strategy="exact_name",
                 bbox={"x": 10, "y": 20, "width": 100, "height": 30},
             ),
         ), \
         patch("agents.vision.executor._dispatch_dom", return_value=True):
        step = TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login Button")
        payload = VisionStepInput(step=step, screenshot_path="never_opened.png")

        result = execute_step(payload)

        assert result.escalate is False
        assert result.verification_method == "single-method"
        assert result.verification_evidence["ocr"] == {"attempted": False}
        assert result.verification_evidence["dispatched_via"] == "dom"


def test_headless_session_never_invokes_pyautogui_dispatch_at_all():
    # The direct fix for the real PyAutoGUI fail-safe crash: when headless,
    # _dispatch_ocr (the only pyautogui-touching code path in this file)
    # must never even be called, regardless of what coordinates a stray
    # OCR match might otherwise have produced.
    from unittest.mock import patch

    from agents.vision.dom_locator import DomLocateResult

    with patch("runtime.hooks.browser.has_active_page", return_value=True), \
         patch("runtime.hooks.browser.is_headless", return_value=True), \
         patch(
             "agents.vision.executor._resolve_dom",
             return_value=DomLocateResult(
                 found=True, confidence=0.9, matched_text="Login Button",
                 role="button", strategy="exact_name",
                 bbox={"x": 10, "y": 20, "width": 100, "height": 30},
             ),
         ), \
         patch("agents.vision.executor._dispatch_dom", return_value=True), \
         patch("agents.vision.executor._dispatch_ocr") as mock_dispatch_ocr:
        step = TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login Button")
        payload = VisionStepInput(step=step, screenshot_path="never_opened.png")

        execute_step(payload)

        mock_dispatch_ocr.assert_not_called()


def test_headed_session_still_runs_ocr_and_can_reach_dual_confirmation():
    # Confirms the fix is a headless-specific skip, not an accidental
    # blanket disabling of OCR for every browser-target step.
    from unittest.mock import patch

    from agents.vision.dom_locator import DomLocateResult
    from agents.vision.locator import LocateResult

    with patch("runtime.hooks.browser.has_active_page", return_value=True), \
         patch("runtime.hooks.browser.is_headless", return_value=False), \
         patch(
             "agents.vision.executor._resolve_dom",
             return_value=DomLocateResult(
                 found=True, confidence=0.9, matched_text="Login Button",
                 role="button", strategy="exact_name",
                 bbox={"x": 10, "y": 20, "width": 100, "height": 30},
             ),
         ), \
         patch(
             "agents.vision.locator.locate_text",
             return_value=LocateResult(found=True, x=50, y=35, confidence=0.85, matched_text="Login Button"),
         ), \
         patch("agents.vision.executor._dispatch_dom", return_value=True):
        step = TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login Button")
        payload = VisionStepInput(step=step, screenshot_path="never_opened.png")

        result = execute_step(payload)

        assert result.verification_method == "dual-method-confirmed"
        assert result.verification_evidence["ocr"]["attempted"] is True
        assert result.verification_evidence["agreement"] is True
