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


def test_dom_scroll_returns_false_when_no_active_page():
    """No live page yet -- dom_scroll must report failure (not raise) so
    callers like orchestrator/autoscan.py know to fall back to the
    OS-level interact.scroll() path."""
    from runtime.hooks import browser

    assert browser.has_active_page() is False
    assert browser.dom_scroll(-600) is False


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


# AB1 (docs/decisions.md D-057 backlog): these now live in
# tests/fixtures/pages.py as PLAIN_TALL_PAGE/LENIS_TALL_PAGE, shared with
# tests/test_real_browser_fixtures.py rather than duplicated here.
from tests.fixtures.pages import PLAIN_TALL_PAGE as TALL_PAGE
from tests.fixtures.pages import LENIS_TALL_PAGE as LENIS_PAGE


@pytest.fixture(autouse=True)
def _force_headless(monkeypatch):
    # Regression tests below need a browser that actually launches in this
    # (headless, no-display) CI environment -- every pre-existing test in
    # this file uses the project's default headed launch, which requires
    # a real display and can't run here at all (see the Xvfb error on the
    # two pre-existing tests above). Forcing headless=True only for these
    # new tests lets them exercise a *real* Chromium + real scrollBy/Lenis
    # behavior in CI, rather than mocking page.evaluate and only testing
    # that the right string was passed.
    from config.settings import settings

    monkeypatch.setattr(settings, "playwright_headless", True)


def test_dom_scroll_moves_page_downward_on_a_plain_tall_page(server=None):
    """
    Regression test for the actual reported bug: --scroll-test ran its
    full iteration budget but the page never visibly moved off the hero
    section. Root cause: dom_scroll's delta_y follows this codebase's
    pyautogui-based convention (negative = scroll down, matching
    interact.scroll()), but was passed straight through to
    window.scrollBy(), which uses the OPPOSITE native sign (positive Y =
    down). Starting at scrollY=0, a "scroll down" call became
    scrollBy(0, negative), which clamps to 0 and never moves at all --
    confirmed directly against a real headless page before this fix.
    """
    from runtime.hooks import browser

    srv = make_server(TALL_PAGE)
    try:
        browser.open_url(server_url(srv), wait_seconds=0.1)
        before = browser.get_scroll_position()
        assert before is not None
        y0, remaining0 = before
        assert y0 == 0

        ok = browser.dom_scroll(-600)  # "scroll down" in this codebase's convention
        assert ok is True

        y1, remaining1 = browser.get_scroll_position()
        assert y1 > y0, "page should have moved DOWN (scrollY increased), not stayed at the top"
        assert remaining1 < remaining0
    finally:
        browser.close()
        srv.shutdown()


def test_dom_scroll_moves_page_downward_on_a_lenis_driven_page():
    """
    Regression test for the Lenis-specific half of the same bug: a
    Lenis-powered page (`<html class="lenis">`, as on the real portfolio
    site this was found on) intercepts native scrolling entirely, so even
    a correctly-signed window.scrollBy() is a silent no-op. dom_scroll()
    must detect window.lenis and drive it directly via lenis.scrollTo().
    """
    from runtime.hooks import browser

    srv = make_server(LENIS_PAGE)
    try:
        browser.open_url(server_url(srv), wait_seconds=0.1)
        before = browser.get_scroll_position()
        assert before is not None
        y0, remaining0 = before
        assert y0 == 0

        ok = browser.dom_scroll(-600)
        assert ok is True

        y1, remaining1 = browser.get_scroll_position()
        assert y1 > y0, "Lenis scroll position should have advanced, not stayed at 0"
        assert remaining1 < remaining0
    finally:
        browser.close()
        srv.shutdown()
