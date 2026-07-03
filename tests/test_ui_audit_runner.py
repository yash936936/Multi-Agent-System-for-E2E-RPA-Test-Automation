"""
tests/test_ui_audit_runner.py

Covers orchestrator/ui_audit_runner.py -- the live "click nav/footer
elements and see if anything happens" audit. Mocks locate_text/interact
the same way tests/test_autoscan.py mocks interact.scroll, since real
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

    fake_landmarks = FakeLandmarks(nav_elements=[], footer_elements=[], has_nav=True, has_hero=False, has_footer=True)
    monkeypatch.setattr("agents.vision.ui_audit.audit_screenshot", lambda path: fake_landmarks)
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues", lambda path: [])

    report = run_ui_audit(provider, run_id="test-run")

    assert report.has_nav is True
    assert report.has_hero is False
    assert report.has_footer is True


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
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues", lambda path: [])
    monkeypatch.setattr("agents.vision.locator.locate_text", lambda path, text, **kw: FakeLocateResult(found=True))

    import runtime.hooks.interact as real_interact

    monkeypatch.setattr(real_interact, "click", lambda x, y: None)
    monkeypatch.setattr(real_interact, "browser_back", lambda: None)

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
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues", lambda path: [])
    monkeypatch.setattr("agents.vision.locator.locate_text", lambda path, text, **kw: FakeLocateResult(found=True))

    import runtime.hooks.interact as real_interact

    monkeypatch.setattr(real_interact, "click", lambda x, y: None)
    monkeypatch.setattr(real_interact, "browser_back", lambda: None)

    report = run_ui_audit(provider, run_id="test-run")

    assert len(report.possibly_broken) == 0
    assert report.checked[0].state_changed is True


def test_run_ui_audit_records_unreachable_when_element_not_located(tmp_path, monkeypatch):
    def provider(run_id, index):
        return _make_screenshot(tmp_path, f"shot_{index}.png", b"baseline")

    nav_el = FakeLandmarkElement(text="Ghost Link", band="nav", looks_interactive=True)
    fake_landmarks = FakeLandmarks(nav_elements=[nav_el], footer_elements=[])
    monkeypatch.setattr("agents.vision.ui_audit.audit_screenshot", lambda path: fake_landmarks)
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues", lambda path: [])
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
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues", lambda path: [])
    monkeypatch.setattr("agents.vision.locator.locate_text", lambda path, text, **kw: FakeLocateResult(found=True))

    import runtime.hooks.interact as real_interact

    monkeypatch.setattr(real_interact, "click", lambda x, y: None)
    monkeypatch.setattr(real_interact, "browser_back", lambda: None)

    report = run_ui_audit(provider, run_id="test-run", max_elements=5)

    assert len(report.checked) == 5


def test_run_ui_audit_collects_page_issues_from_baseline():
    pass  # covered implicitly by the presence checks above; page_issues wiring exercised directly below


def test_run_ui_audit_includes_baseline_page_issues(tmp_path, monkeypatch):
    def provider(run_id, index):
        return _make_screenshot(tmp_path, f"shot_{index}.png", b"baseline")

    fake_landmarks = FakeLandmarks(nav_elements=[], footer_elements=[])
    monkeypatch.setattr("agents.vision.ui_audit.audit_screenshot", lambda path: fake_landmarks)
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues", lambda path: ["404"])

    report = run_ui_audit(provider, run_id="test-run")

    assert "404" in report.page_issues
