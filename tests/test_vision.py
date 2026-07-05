from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from agents.vision.assertions import check_assertion
from agents.vision.executor import execute_step
from agents.vision.locator import locate_text
from orchestrator.schemas import ActionType, TestStep, VisionStepInput

from target_app.demo_login_app import resolve_font


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
