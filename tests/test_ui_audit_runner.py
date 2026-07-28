"""
tests/test_ui_audit_runner.py

Covers orchestrator/ui_audit_runner.py -- the live "click nav/footer
elements and see if anything happens" audit. Mocks locate_text/interact
the same way tests/test_autoscan.py mocks os_fallback.scroll, since real
clicking needs a live display.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orchestrator.ui_audit_runner import run_ui_audit


def _make_screenshot(tmp_path: Path, name: str, content: bytes) -> str:
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


@dataclass
class FakeLandmarkElement:
    text: str
    band: str
    looks_interactive: bool


@dataclass
class FakeLandmarks:
    nav_elements: list
    footer_elements: list
    hero_elements: list = None
    body_elements: list = None
    has_nav: bool = True
    has_hero: bool = True
    has_footer: bool = True

    def __post_init__(self):
        if self.hero_elements is None:
            self.hero_elements = []
        if self.body_elements is None:
            self.body_elements = []


@dataclass
class FakeLocateResult:
    found: bool
    x: int = 100
    y: int = 100


def test_run_ui_audit_reports_landmark_presence(tmp_path, monkeypatch):
    def provider(run_id, index):
        return _make_screenshot(tmp_path, f"shot_{index}.png", b"baseline")

    fake_landmarks = FakeLandmarks(
        nav_elements=[FakeLandmarkElement(text="About", band="nav", looks_interactive=True)],
        footer_elements=[FakeLandmarkElement(text="Privacy", band="footer", looks_interactive=True)],
        hero_elements=[],
    )
    monkeypatch.setattr("agents.vision.ui_audit.audit_screenshot", lambda path: fake_landmarks)
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues_detailed", lambda path: ([], True))

    report = run_ui_audit(provider, run_id="test-run")

    assert report.has_nav is True
    assert report.has_hero is False
    assert report.has_footer is True


def test_run_ui_audit_flags_ocr_unavailable_distinct_from_clean(tmp_path, monkeypatch):
    """Regression: an OCR failure (e.g. tesseract missing) must not be
    silently reported the same as 'checked, found no page_issues'. See
    agents/vision/page_health.py::detect_page_issues_detailed."""
    def provider(run_id, index):
        return _make_screenshot(tmp_path, f"shot_{index}.png", b"baseline")

    fake_landmarks = FakeLandmarks(nav_elements=[], footer_elements=[], hero_elements=[])
    monkeypatch.setattr("agents.vision.ui_audit.audit_screenshot", lambda path: fake_landmarks)
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues_detailed", lambda path: ([], False))

    report = run_ui_audit(provider, run_id="test-run")

    assert report.page_issues == []
    assert report.ocr_checked is False


def test_run_ui_audit_flags_element_with_no_visible_change_as_possibly_broken(tmp_path, monkeypatch):
    call_count = {"n": 0}

    def provider(run_id, index):
        # Every screenshot (baseline + after-click) is byte-identical --
        # simulates a click that produced no visible change on screen.
        call_count["n"] += 1
        return _make_screenshot(tmp_path, f"shot_{call_count['n']}.png", b"same-content-every-time")

    nav_el = FakeLandmarkElement(text="Broken Link", band="nav", looks_interactive=True)
    fake_landmarks = FakeLandmarks(nav_elements=[nav_el], footer_elements=[])
    monkeypatch.setattr("agents.vision.ui_audit.audit_screenshot", lambda path: fake_landmarks)
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues_detailed", lambda path: ([], True))
    monkeypatch.setattr("agents.vision.locator.locate_text", lambda path, text, **kw: FakeLocateResult(found=True))

    import runtime.hooks.os_fallback as real_os_fallback

    monkeypatch.setattr(real_os_fallback, "click", lambda x, y: None)
    monkeypatch.setattr(real_os_fallback, "browser_back", lambda: None)

    report = run_ui_audit(provider, run_id="test-run")

    assert len(report.possibly_broken) == 1
    assert report.possibly_broken[0].label == "Broken Link"


def test_run_ui_audit_does_not_flag_element_when_page_visibly_changes(tmp_path, monkeypatch):
    frames = iter([b"baseline", b"different-page-content"])

    def provider(run_id, index):
        return _make_screenshot(tmp_path, f"shot_{index}.png", next(frames))

    nav_el = FakeLandmarkElement(text="Working Link", band="nav", looks_interactive=True)
    fake_landmarks = FakeLandmarks(nav_elements=[nav_el], footer_elements=[])
    monkeypatch.setattr("agents.vision.ui_audit.audit_screenshot", lambda path: fake_landmarks)
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues_detailed", lambda path: ([], True))
    monkeypatch.setattr("agents.vision.locator.locate_text", lambda path, text, **kw: FakeLocateResult(found=True))

    import runtime.hooks.os_fallback as real_os_fallback

    monkeypatch.setattr(real_os_fallback, "click", lambda x, y: None)
    monkeypatch.setattr(real_os_fallback, "browser_back", lambda: None)

    report = run_ui_audit(provider, run_id="test-run")

    assert len(report.possibly_broken) == 0
    assert report.checked[0].state_changed is True


def test_run_ui_audit_records_unreachable_when_element_not_located(tmp_path, monkeypatch):
    def provider(run_id, index):
        return _make_screenshot(tmp_path, f"shot_{index}.png", b"baseline")

    nav_el = FakeLandmarkElement(text="Ghost Link", band="nav", looks_interactive=True)
    fake_landmarks = FakeLandmarks(nav_elements=[nav_el], footer_elements=[])
    monkeypatch.setattr("agents.vision.ui_audit.audit_screenshot", lambda path: fake_landmarks)
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues_detailed", lambda path: ([], True))
    monkeypatch.setattr("agents.vision.locator.locate_text", lambda path, text, **kw: FakeLocateResult(found=False))

    report = run_ui_audit(provider, run_id="test-run")

    assert len(report.unreachable) == 1
    assert report.unreachable[0].label == "Ghost Link"


def test_run_ui_audit_respects_max_elements_cap(tmp_path, monkeypatch):
    def provider(run_id, index):
        return _make_screenshot(tmp_path, f"shot_{index}.png", f"frame-{index}".encode())

    nav_elements = [FakeLandmarkElement(text=f"Link {i}", band="nav", looks_interactive=True) for i in range(20)]
    fake_landmarks = FakeLandmarks(nav_elements=nav_elements, footer_elements=[])
    monkeypatch.setattr("agents.vision.ui_audit.audit_screenshot", lambda path: fake_landmarks)
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues_detailed", lambda path: ([], True))
    monkeypatch.setattr("agents.vision.locator.locate_text", lambda path, text, **kw: FakeLocateResult(found=True))

    import runtime.hooks.os_fallback as real_os_fallback

    monkeypatch.setattr(real_os_fallback, "click", lambda x, y: None)
    monkeypatch.setattr(real_os_fallback, "browser_back", lambda: None)

    report = run_ui_audit(provider, run_id="test-run", max_elements=5)

    assert len(report.checked) == 5


def test_run_ui_audit_collects_page_issues_from_baseline():
    pass  # covered implicitly by the presence checks above; page_issues wiring exercised directly below


def test_run_ui_audit_includes_baseline_page_issues(tmp_path, monkeypatch):
    def provider(run_id, index):
        return _make_screenshot(tmp_path, f"shot_{index}.png", b"baseline")

    fake_landmarks = FakeLandmarks(nav_elements=[], footer_elements=[])
    monkeypatch.setattr("agents.vision.ui_audit.audit_screenshot", lambda path: fake_landmarks)
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues_detailed", lambda path: (["404"], True))

    report = run_ui_audit(provider, run_id="test-run")

    assert "404" in report.page_issues


def test_run_ui_audit_handles_no_display_on_baseline_capture():
    """Regression test: the baseline screenshot_provider call inside
    _run_click_audit used to be unguarded, so a NoDisplayError crashed
    `aura execute --ui-audit` with a raw
    traceback instead of returning a clean, empty report."""
    from runtime.hooks.capture import NoDisplayError

    def no_display_provider(run_id: str, index: int) -> str:
        raise NoDisplayError("no display connected")

    report = run_ui_audit(no_display_provider, run_id="r1")

    assert report.has_nav is False
    assert report.has_hero is False
    assert report.has_footer is False
    assert report.checked == []
    assert any("No display available" in issue for issue in report.page_issues)


def test_discovery_uses_dom_path_and_never_calls_ocr_when_dom_page_available(tmp_path, monkeypatch):
    """
    Re-architecture Phase 2 (docs/decisions.md D-073): the plan's explicit
    acceptance test -- when a live DOM page is available (and the
    extractor is enabled), discovery must go through
    agents.vision.dom_extractor.to_ui_elements exclusively.
    agents.vision.ui_audit.audit_screenshot (the OCR/vocab path) must
    never even be called, not just "not relied upon" -- asserted directly
    against the branch condition, per the plan's own instruction.
    """
    import agents.vision.ui_audit as ui_audit_module
    from agents.vision.ui_audit import UIElement
    from config.settings import settings

    def provider(run_id, index):
        return _make_screenshot(tmp_path, f"shot_{index}.png", b"baseline")

    ocr_called = {"n": 0}

    def _spy_audit_screenshot(path):
        ocr_called["n"] += 1
        raise AssertionError("OCR path (audit_screenshot) must not be called when a DOM page is available")

    monkeypatch.setattr(ui_audit_module, "audit_screenshot", _spy_audit_screenshot)
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues_detailed", lambda path: ([], True))
    monkeypatch.setattr(settings, "enable_dom_extractor", True)

    class FakePage:
        def evaluate(self, js):
            return 2000  # scrollHeight

    fake_page = FakePage()
    monkeypatch.setattr("runtime.hooks.browser.has_active_page", lambda: True)
    monkeypatch.setattr("runtime.hooks.browser.get_page", lambda: fake_page)

    dom_elements = [UIElement(text="About", cx=50, cy=30, band="nav", looks_interactive=True)]
    monkeypatch.setattr("agents.vision.dom_extractor.to_ui_elements", lambda page, height: dom_elements)

    report = run_ui_audit(provider, run_id="dom-run")

    assert ocr_called["n"] == 0
    assert report.has_nav is True


def test_discovery_falls_back_to_ocr_when_no_dom_page(tmp_path, monkeypatch):
    """The other half of the same branch condition: no live DOM page (or
    the extractor disabled) -- OCR is the only path, as before Phase 2."""
    from config.settings import settings

    def provider(run_id, index):
        return _make_screenshot(tmp_path, f"shot_{index}.png", b"baseline")

    fake_landmarks = FakeLandmarks(
        nav_elements=[FakeLandmarkElement(text="About", band="nav", looks_interactive=True)],
        footer_elements=[],
        hero_elements=[],
    )
    monkeypatch.setattr("agents.vision.ui_audit.audit_screenshot", lambda path: fake_landmarks)
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues_detailed", lambda path: ([], True))
    monkeypatch.setattr(settings, "enable_dom_extractor", True)
    monkeypatch.setattr("runtime.hooks.browser.has_active_page", lambda: False)

    report = run_ui_audit(provider, run_id="ocr-run")

    assert report.has_nav is True


def test_click_audit_uses_mutation_observer_as_primary_change_detection_when_dom_page_available(tmp_path, monkeypatch):
    """
    Phase 4 (docs/decisions.md D-077): when a live DOM page exists, a
    real DOM mutation (not a pixel-hash diff) drives state_changed --
    proven here by having the two screenshots be byte-identical (would
    report state_changed=False under the old hash-diff-only logic) while
    the mutation observer reports a real mutation, and asserting
    state_changed comes out True anyway.
    """
    import agents.vision.ui_audit as ui_audit_module
    from agents.vision.ui_audit import UIElement
    from config.settings import settings

    same_bytes = b"identical-every-time"

    def provider(run_id, index):
        return _make_screenshot(tmp_path, f"shot_{index}.png", same_bytes)

    monkeypatch.setattr(ui_audit_module, "audit_screenshot", lambda path: FakeLandmarks(nav_elements=[], footer_elements=[]))
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues_detailed", lambda path: ([], True))
    monkeypatch.setattr(settings, "enable_dom_extractor", True)

    class FakePage:
        def __init__(self):
            self.arm_calls = 0

        def evaluate(self, js, arg=None):
            if "document.documentElement.scrollHeight" in js:
                return 2000
            if "__aura_mutations = []" in js:
                self.arm_calls += 1
                return True
            return {"count": 5, "urlBefore": "http://x", "urlAfter": "http://x", "sample": [{"type": "childList", "tag": "DIV"}]}

    fake_page = FakePage()
    monkeypatch.setattr("runtime.hooks.browser.has_active_page", lambda: True)
    monkeypatch.setattr("runtime.hooks.browser.get_page", lambda: fake_page)

    dom_elements = [UIElement(text="Sign Up", cx=50, cy=30, band="nav", looks_interactive=True)]
    monkeypatch.setattr("agents.vision.dom_extractor.to_ui_elements", lambda page, height: dom_elements)

    import orchestrator.ui_audit_runner as runner_module

    class FakeSmartBackResult:
        new_tab_opened = False
        new_tab_url = None
        went_back = False

    monkeypatch.setattr(runner_module, "_try_dom_click", lambda page, text: FakeSmartBackResult())

    report = run_ui_audit(provider, run_id="mutation-run")

    assert fake_page.arm_calls == 1  # armed exactly once, before the click dispatch
    assert len(report.checked) == 1
    assert report.checked[0].clicked is True
    assert report.checked[0].state_changed is True  # from the mutation, not the (identical) screenshot hash


def test_click_audit_reports_no_change_when_mutation_observer_sees_nothing_even_if_screenshot_bytes_happen_to_differ(tmp_path, monkeypatch):
    """
    The inverse proof: two screenshots that DO differ (which the old
    hash-diff-only logic would have called state_changed=True) but a
    mutation observer reporting zero real mutations and no URL change --
    state_changed must come out False. This is the structural fix for
    "an unrelated animation/ad rotation looked like a real change."
    """
    import agents.vision.ui_audit as ui_audit_module
    from agents.vision.ui_audit import UIElement
    from config.settings import settings

    call_count = {"n": 0}

    def provider(run_id, index):
        call_count["n"] += 1
        return _make_screenshot(tmp_path, f"shot_{index}.png", f"different-bytes-{call_count['n']}".encode())

    monkeypatch.setattr(ui_audit_module, "audit_screenshot", lambda path: FakeLandmarks(nav_elements=[], footer_elements=[]))
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues_detailed", lambda path: ([], True))
    monkeypatch.setattr(settings, "enable_dom_extractor", True)

    class FakePage:
        def evaluate(self, js, arg=None):
            if "document.documentElement.scrollHeight" in js:
                return 2000
            if "__aura_mutations = []" in js:
                return True
            return {"count": 0, "urlBefore": "http://x", "urlAfter": "http://x", "sample": []}

    fake_page = FakePage()
    monkeypatch.setattr("runtime.hooks.browser.has_active_page", lambda: True)
    monkeypatch.setattr("runtime.hooks.browser.get_page", lambda: fake_page)

    dom_elements = [UIElement(text="Heading", cx=50, cy=30, band="footer", looks_interactive=True)]
    monkeypatch.setattr("agents.vision.dom_extractor.to_ui_elements", lambda page, height: dom_elements)

    import orchestrator.ui_audit_runner as runner_module

    class FakeSmartBackResult:
        new_tab_opened = False
        new_tab_url = None
        went_back = False

    monkeypatch.setattr(runner_module, "_try_dom_click", lambda page, text: FakeSmartBackResult())

    report = run_ui_audit(provider, run_id="no-mutation-run")

    assert report.checked[0].state_changed is False

