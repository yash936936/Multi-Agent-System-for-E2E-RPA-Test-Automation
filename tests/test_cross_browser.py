from __future__ import annotations

import pytest

from config.settings import settings
from tests.conftest_local_server import make_server, server_url

PAGE = b"""
<html><body><h1>Hello Phase I</h1><button>Click me</button></body></html>
"""


@pytest.fixture
def server():
    srv = make_server(PAGE)
    yield srv
    srv.shutdown()


@pytest.fixture(autouse=True)
def _reset_browser_session_and_settings():
    from runtime.hooks import browser

    browser.close()
    original_engine = settings.playwright_browser
    original_video = settings.record_video
    original_trace = settings.record_trace
    yield
    browser.close()
    settings.playwright_browser = original_engine
    settings.record_video = original_video
    settings.record_trace = original_trace


def test_default_engine_is_chromium_and_still_works(server):
    """Baseline: unchanged default behavior for anyone not opting into I1."""
    from runtime.hooks import browser

    assert settings.playwright_browser == "chromium"
    url = browser.open_url(server_url(server), wait_seconds=0.1)
    assert url == server_url(server)
    page = browser.get_page()
    assert "Hello Phase I" in page.content()


def test_invalid_engine_name_raises_no_display_error_without_touching_playwright():
    """
    An invalid settings.playwright_browser value must fail with a clear,
    typed NoDisplayError -- not a raw AttributeError from
    getattr(playwright_instance, bogus_name) deep inside the try block.
    """
    from runtime.hooks import browser

    settings.playwright_browser = "not_a_real_browser"

    with pytest.raises(browser.NoDisplayError) as exc_info:
        browser.get_page()

    assert "not_a_real_browser" in str(exc_info.value)
    assert "chromium" in str(exc_info.value)  # lists valid choices


def test_firefox_engine_selected_launches_firefox_not_chromium(monkeypatch):
    """
    Verifies the actual dispatch logic (getattr(playwright, engine_name))
    picks the configured engine, using a mock Playwright instance so this
    doesn't depend on the firefox browser binary actually being
    downloaded in this sandbox (it may not be -- same class of
    environment-dependent gap as Chromium's own download restriction
    noted throughout docs/STATUS.md).
    """
    from unittest.mock import MagicMock
    from runtime.hooks import browser

    settings.playwright_browser = "firefox"

    fake_page = MagicMock()
    fake_context = MagicMock()
    fake_context.new_page.return_value = fake_page
    fake_browser = MagicMock()
    fake_browser.new_context.return_value = fake_context
    fake_firefox_engine = MagicMock()
    fake_firefox_engine.launch.return_value = fake_browser
    fake_chromium_engine = MagicMock()

    fake_playwright_instance = MagicMock()
    fake_playwright_instance.firefox = fake_firefox_engine
    fake_playwright_instance.chromium = fake_chromium_engine

    fake_sync_playwright_cm = MagicMock()
    fake_sync_playwright_cm.start.return_value = fake_playwright_instance

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright", lambda: fake_sync_playwright_cm
    )

    page = browser.get_page()

    assert page is fake_page
    fake_firefox_engine.launch.assert_called_once_with(headless=True)
    fake_chromium_engine.launch.assert_not_called()


def test_firefox_launch_failure_wraps_into_no_display_error_not_a_crash(monkeypatch, server):
    """
    Whatever engine is selected, if the underlying Playwright launch()
    call fails (e.g. the browser binary genuinely isn't downloaded), that
    failure must surface as a clean NoDisplayError, not an unhandled
    exception -- confirms the existing except-wrap-into-NoDisplayError
    behavior still covers the new engine-selection code path.

    This used to assert against real ambient machine state ("only
    chromium is installed in this sandbox"), which broke the moment
    firefox was installed anywhere the suite ran (e.g. `playwright
    install firefox` on a dev machine) -- the test then failed not
    because the wrapping behavior regressed, but because its own
    precondition (firefox absent) no longer held. A fake Playwright
    engine whose launch() always raises tests the wrapping behavior
    deterministically, independent of which browser binaries happen to
    be downloaded on whatever machine runs this suite.
    """
    import playwright.sync_api as playwright_sync_api
    from runtime.hooks import browser

    settings.playwright_browser = "firefox"

    class _BrokenEngine:
        def launch(self, *args, **kwargs):
            raise Exception(
                "Executable doesn't exist at .../firefox/firefox.exe\n"
                "Looks like Playwright was just installed or updated. "
                "Please run: playwright install"
            )

    class _FakePlaywrightContext:
        def __init__(self):
            self.chromium = _BrokenEngine()
            self.firefox = _BrokenEngine()
            self.webkit = _BrokenEngine()

        def stop(self):
            pass

    class _FakeSyncPlaywright:
        def start(self):
            return _FakePlaywrightContext()

    monkeypatch.setattr(playwright_sync_api, "sync_playwright", lambda: _FakeSyncPlaywright())

    with pytest.raises(browser.NoDisplayError):
        browser.open_url(server_url(server), wait_seconds=0.1)


def test_record_video_produces_a_real_video_file_on_close(server):
    """
    Phase I2: with settings.record_video on, a real Playwright video file
    must exist on disk after browser.close() -- finalized only once the
    page is closed, which is exactly what close() now does before tearing
    the rest of the session down.
    """
    import os
    from runtime.hooks import browser

    settings.record_video = True
    browser.open_url(server_url(server), wait_seconds=0.1)
    assert browser.has_active_page() is True

    browser.close()

    video_path = browser.get_last_video_path()
    assert video_path is not None
    assert os.path.exists(video_path)
    assert os.path.getsize(video_path) > 0


def test_record_video_off_by_default_produces_no_video_path(server):
    from runtime.hooks import browser

    assert settings.record_video is False
    browser.open_url(server_url(server), wait_seconds=0.1)
    browser.close()

    assert browser.get_last_video_path() is None


def test_record_trace_produces_a_real_trace_file_on_close(server):
    """
    Phase Q (decisions.md D-038): with settings.record_trace on, a real
    Playwright trace .zip must exist on disk after browser.close() --
    unlike video, tracing.stop(path=...) both finalizes and writes the
    file in one call, but it has to run before the context itself is
    torn down, which is exactly what close() now does first.
    """
    import os
    import zipfile
    from runtime.hooks import browser

    settings.record_trace = True
    browser.open_url(server_url(server), wait_seconds=0.1)
    assert browser.has_active_page() is True

    browser.close()

    trace_path = browser.get_last_trace_path()
    assert trace_path is not None
    assert os.path.exists(trace_path)
    assert os.path.getsize(trace_path) > 0
    assert zipfile.is_zipfile(trace_path)


def test_record_trace_off_by_default_produces_no_trace_path(server):
    from runtime.hooks import browser

    assert settings.record_trace is False
    browser.open_url(server_url(server), wait_seconds=0.1)
    browser.close()

    assert browser.get_last_trace_path() is None


def test_record_video_and_record_trace_are_independent(server):
    """Toggling one must not implicitly toggle or suppress the other."""
    from runtime.hooks import browser

    settings.record_video = False
    settings.record_trace = True
    browser.open_url(server_url(server), wait_seconds=0.1)
    browser.close()

    assert browser.get_last_video_path() is None
    assert browser.get_last_trace_path() is not None
