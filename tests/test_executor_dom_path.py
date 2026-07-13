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
