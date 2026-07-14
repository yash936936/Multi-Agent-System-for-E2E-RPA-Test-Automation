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


def test_run_autoscan_handles_no_display_on_first_screenshot():
    """Regression test: the screenshot_provider call inside run_autoscan's
    loop used to be unguarded, so a NoDisplayError on the very first
    iteration (the common case in a headless/no-display environment)
    crashed both `aura execute --scroll-test` and `aura explore` with a
    raw traceback instead of stopping cleanly."""
    from runtime.hooks.capture import NoDisplayError

    def no_display_provider(run_id: str, index: int) -> str:
        raise NoDisplayError("no display connected")

    report = run_autoscan(no_display_provider, run_id="r1")

    assert report.display_unavailable is True
    assert report.reached_bottom is False
    assert report.steps == []
    assert report.all_issues == []


def test_run_autoscan_handles_no_display_mid_scan(tmp_path, monkeypatch):
    """A display that disconnects partway through the scan should also
    stop cleanly, keeping whatever steps were already collected."""
    from runtime.hooks.capture import NoDisplayError

    frames = [b"frame-0", b"frame-1"]
    calls = {"i": 0}

    def flaky_provider(run_id: str, index: int) -> str:
        i = calls["i"]
        calls["i"] += 1
        if i >= len(frames):
            raise NoDisplayError("display dropped")
        path = tmp_path / f"shot_{i}.png"
        path.write_bytes(frames[i])
        return str(path)

    import runtime.hooks.interact as real_interact

    monkeypatch.setattr(real_interact, "scroll", lambda amount: None)
    monkeypatch.setattr("agents.vision.page_health.detect_page_issues", lambda path: [])

    report = run_autoscan(flaky_provider, run_id="r2")

    assert report.display_unavailable is True
    assert len(report.steps) == 2
    assert report.reached_bottom is False
