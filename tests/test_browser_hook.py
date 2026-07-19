from __future__ import annotations

import pytest

from tests.conftest_local_server import make_server, server_url

PAGE = b"""
<html><body><h1>Hello Phase C</h1><button>Click me</button></body></html>
"""


@pytest.fixture
def server():
    srv = make_server(PAGE)
    yield srv
    srv.shutdown()


@pytest.fixture(autouse=True)
def _reset_browser_session():
    from runtime.hooks import browser

    browser.close()
    yield
    browser.close()


def test_open_url_launches_real_chromium_and_navigates(server):
    from runtime.hooks import browser

    url = browser.open_url(server_url(server), wait_seconds=0.1)
    assert url == server_url(server)
    assert browser.has_active_page() is True

    page = browser.get_page()
    assert "Hello Phase C" in page.content()


def test_has_active_page_false_before_any_navigation():
    from runtime.hooks import browser

    assert browser.has_active_page() is False


def test_close_resets_session(server):
    from runtime.hooks import browser

    browser.open_url(server_url(server), wait_seconds=0.1)
    assert browser.has_active_page() is True

    browser.close()
    assert browser.has_active_page() is False


def test_normalize_url_adds_scheme():
    from runtime.hooks import browser

    assert browser.normalize_url("example.com") == "https://example.com"
    assert browser.normalize_url("https://example.com") == "https://example.com"


def test_open_url_no_display_raises_no_display_error(monkeypatch, server):
    from runtime.hooks import browser

    def boom(*a, **k):
        raise RuntimeError("no chromium here")

    monkeypatch.setattr("playwright.sync_api.sync_playwright", boom)

    with pytest.raises(browser.NoDisplayError):
        browser.open_url(server_url(server))


# --------------------------------------------------------------------------
# is_headless() (D-046 bug fix) -- agents/vision/executor.py's OCR-skip
# gate reads this. These don't need a real browser: the "no session
# launched yet" default and the reset-on-close behavior are both testable
# without ever calling get_page().
# --------------------------------------------------------------------------

def test_is_headless_defaults_true_before_any_session_launched():
    # No browser has been launched at all -- "assume can't see it" is the
    # safe default, same direction as settings.playwright_headless itself.
    from runtime.hooks import browser

    assert browser.is_headless() is True


def test_is_headless_resets_to_default_after_close():
    # A stale False (headed) from a previous session must not leak into
    # the next one just because close() forgot to clear it -- this is
    # exactly the class of bug flagged for _last_video_path/_last_trace_path
    # in close()'s own comments; is_headless() needs the same discipline.
    from runtime.hooks import browser

    browser._session._headless = False  # simulate a just-finished headed session
    assert browser.is_headless() is False
    browser.close()
    assert browser.is_headless() is True


def test_playwright_headless_setting_defaults_true():
    from config.settings import Settings

    assert Settings().playwright_headless is True

