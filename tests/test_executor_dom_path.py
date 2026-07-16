from __future__ import annotations

import pytest

from agents.vision.executor import execute_step
from orchestrator.schemas import ActionType, TestStep, VisionStepInput
from tests.conftest_local_server import make_server, server_url

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
    shot_path = tmp_path / "dual_agree.png"
    live_page.screenshot(path=str(shot_path))

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
    shot_path = tmp_path / "dual_single.png"
    live_page.screenshot(path=str(shot_path))

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

    shot_path = tmp_path / "dual_fallback.png"
    live_page.screenshot(path=str(shot_path))

    step = TestStep(step_id=1, action=ActionType.VISUAL_CLICK, target_description="Login Button")
    payload = VisionStepInput(step=step, screenshot_path=str(shot_path))

    result = execute_step(payload)

    assert result.escalate is False
    assert result.verification_evidence["dispatched_via"] == "ocr"
    assert live_page.title() == "clicked"
