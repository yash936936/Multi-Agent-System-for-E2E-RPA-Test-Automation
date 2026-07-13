from __future__ import annotations

import pytest

from tests.conftest_local_server import make_server, server_url

PAGE_V1 = b"""
<html><body>
  <nav><a href="/about">About Us</a></nav>
  <button>Login Button</button>
  <input type="text" placeholder="Username" aria-label="Username Field" />
</body></html>
"""

# Same page, but the button's accessible name drifted slightly (structure
# drift) -- relocate_dom() should still find it via fuzzy re-scoring.
PAGE_V2_DRIFTED = b"""
<html><body>
  <nav><a href="/about">About Us</a></nav>
  <button>Login</button>
  <input type="text" placeholder="Username" aria-label="Username Field" />
</body></html>
"""


@pytest.fixture(autouse=True)
def _reset_browser_session():
    from runtime.hooks import browser

    browser.close()
    yield
    browser.close()


def _page_for(html: bytes):
    from runtime.hooks import browser

    srv = make_server(html)
    browser.open_url(server_url(srv), wait_seconds=0.1)
    return browser.get_page(), srv


def test_locate_dom_finds_exact_button_match():
    from agents.vision.dom_locator import locate_dom

    page, srv = _page_for(PAGE_V1)
    try:
        result = locate_dom(page, "Login Button")
        assert result.found is True
        assert result.role == "button"
        assert result.confidence >= 0.55
        assert result.locator is not None
    finally:
        srv.shutdown()


def test_locate_dom_no_match_reports_top_score_not_silently_empty():
    from agents.vision.dom_locator import locate_dom

    page, srv = _page_for(PAGE_V1)
    try:
        result = locate_dom(page, "Totally Unrelated Nonexistent Target Xyz")
        assert result.found is False
        # Scrapling-style UX: log the top score even on failure.
        assert result.top_score_seen >= 0.0
    finally:
        srv.shutdown()


def test_relocate_dom_self_heals_after_structure_drift():
    from agents.vision.dom_locator import locate_dom, relocate_dom

    page, srv = _page_for(PAGE_V2_DRIFTED)
    try:
        # Primary path fails to confidently match "Login Button" against
        # the drifted text "Login" at the default 0.55 threshold territory
        # -- but relocate()'s relaxed 0.40 threshold should still resolve it.
        result = relocate_dom(page, {"name": "Login Button"})
        assert result.found is True
        assert result.strategy == "relocate"
        assert result.role == "button"
    finally:
        srv.shutdown()


def test_relocate_dom_returns_ties_count_when_ambiguous():
    from agents.vision.dom_locator import relocate_dom

    html = b"""
    <html><body>
      <button>Submit</button>
      <button>Submit</button>
    </body></html>
    """
    page, srv = _page_for(html)
    try:
        result = relocate_dom(page, {"name": "Submit"})
        assert result.found is True
        assert result.ambiguous_count == 2
    finally:
        srv.shutdown()
