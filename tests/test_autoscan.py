from __future__ import annotations

from pathlib import Path

from agents.vision.page_health import detect_page_issues
from orchestrator.autoscan import run_autoscan


def _make_screenshot(tmp_path: Path, name: str, content: bytes) -> str:
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


def test_run_autoscan_stops_when_screenshot_stops_changing(tmp_path, monkeypatch):
    # Simulate 3 distinct screenshots then repeats forever (bottom of page).
    frames = [b"frame-0", b"frame-1", b"frame-2", b"frame-2", b"frame-2"]
    calls = {"i": 0}

    def fake_provider(run_id: str, index: int) -> str:
        content = frames[min(calls["i"], len(frames) - 1)]
        calls["i"] += 1
        return _make_screenshot(tmp_path, f"shot_{calls['i']}.png", content)

    scrolled = {"count": 0}

    class FakeInteract:
        class NoDisplayError(RuntimeError):
            pass

        @staticmethod
        def scroll(amount):
            scrolled["count"] += 1

    import runtime.hooks.interact as real_interact

    monkeypatch.setattr(real_interact, "scroll", FakeInteract.scroll)
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues", lambda path: [])

    report = run_autoscan(fake_provider, run_id="test-run", max_scrolls=25)

    assert report.reached_bottom is True
    # Stops as soon as two consecutive screenshots hash identically.
    assert len(report.steps) == 4


def test_run_autoscan_respects_max_scrolls_cap(tmp_path, monkeypatch):
    def always_different_provider(run_id: str, index: int) -> str:
        return _make_screenshot(tmp_path, f"shot_{index}.png", f"frame-{index}".encode())

    import runtime.hooks.interact as real_interact

    monkeypatch.setattr(real_interact, "scroll", lambda amount: None)
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues", lambda path: [])

    report = run_autoscan(always_different_provider, run_id="test-run", max_scrolls=5)

    assert report.reached_bottom is False
    assert len(report.steps) == 5


def test_run_autoscan_collects_issues(tmp_path, monkeypatch):
    def provider(run_id: str, index: int) -> str:
        return _make_screenshot(tmp_path, f"shot_{index}.png", f"frame-{index}".encode())

    import runtime.hooks.interact as real_interact

    monkeypatch.setattr(real_interact, "scroll", lambda amount: None)

    calls = {"i": 0}

    def fake_detect(path):
        calls["i"] += 1
        return ["404"] if calls["i"] == 2 else []

    monkeypatch.setattr("agents.vision.page_health.detect_page_issues", fake_detect)

    report = run_autoscan(provider, run_id="test-run", max_scrolls=3)

    assert "404" in report.all_issues


def test_detect_page_issues_matches_known_markers(monkeypatch):
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
            return "Oops! 404 - Page Not Found"

    monkeypatch.setitem(__import__("sys").modules, "pytesseract", FakePytesseract)
    monkeypatch.setitem(__import__("sys").modules, "PIL", type("m", (), {"Image": FakeImage}))

    issues = detect_page_issues("fake.png")
    assert "404" in issues


def test_detect_page_issues_clean_page_returns_empty(monkeypatch):
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
            return "Welcome to our homepage. Everything is working great."

    monkeypatch.setitem(__import__("sys").modules, "pytesseract", FakePytesseract)
    monkeypatch.setitem(__import__("sys").modules, "PIL", type("m", (), {"Image": FakeImage}))

    assert detect_page_issues("fake.png") == []


def test_detect_page_issues_never_raises_on_ocr_failure(monkeypatch):
    class FailingPytesseract:
        @staticmethod
        def image_to_string(img):
            raise RuntimeError("no OCR engine")

    monkeypatch.setitem(__import__("sys").modules, "pytesseract", FailingPytesseract)

    assert detect_page_issues("fake.png") == []
