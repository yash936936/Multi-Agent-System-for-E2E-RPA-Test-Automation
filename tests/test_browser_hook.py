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
