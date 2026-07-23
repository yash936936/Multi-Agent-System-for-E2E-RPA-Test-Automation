"""
tests/test_real_browser_fixtures.py

AB1 (docs/decisions.md D-057's backlog) -- real-(headless-)browser test
tier. Unlike most of this codebase's tests, these run against an actual
Chromium instance and an actual local HTTP server, no mocks, so they
exercise the exact conditions that mocked tests missed all session:
real JS execution timing, real DOM hydration, real OCR against a real
screenshot.

See tests/test_browser_hook.py for the scroll-direction/Lenis fixture
tests (plain tall page, Lenis-driven page) -- those share
tests/fixtures/pages.py's PLAIN_TALL_PAGE/LENIS_TALL_PAGE with this file
rather than duplicating them here.
"""
from __future__ import annotations

import pytest

from tests.conftest_local_server import make_server, server_url
from tests.fixtures.pages import FAKE_500_ERROR_PAGE, SPA_CLIENT_ROUTING_PAGE


@pytest.fixture(autouse=True)
def _force_headless(monkeypatch):
    # Same rationale as tests/test_browser_hook.py's fixture of the same
    # name: lets these tests launch a real Chromium in a headless/no-
    # display CI environment instead of requiring a real display.
    from config.settings import settings

    monkeypatch.setattr(settings, "playwright_headless", True)


def test_link_check_finds_client_injected_links_via_live_page_html():
    """
    AB1 regression test for D-055's real bug, now exercised against an
    actual browser + actual server instead of mocks: a plain httpx GET
    against a client-rendered SPA sees no <a href> at all (the page's
    real HTML is just a bare mount point) -- but once a real browser has
    hydrated the page, LinkCheckAdapter.run() with live_page_html must
    find the real, JS-injected links rather than reporting 0.
    """
    from agents.capability.link_checker import LinkCheckAdapter
    from orchestrator.schemas import CapabilityCheckInput, CapabilityType
    from runtime.hooks import browser

    srv = make_server(SPA_CLIENT_ROUTING_PAGE)
    try:
        url = server_url(srv)
        browser.open_url(url, wait_seconds=0.3)  # let the setTimeout hydration actually run
        live_html = browser.get_page().content()
        browser.close()

        adapter = LinkCheckAdapter()
        result = adapter.run(
            CapabilityCheckInput(
                capability=CapabilityType.LINK_CHECK,
                target=url,
                params={"scope": "all", "live_page_html": live_html},
            )
        )

        assert result.evidence["used_live_page"] is True
        assert result.evidence["rendered_via_playwright"] is False
        # The pre-hydration HTML the plain httpx GET would see has zero
        # <a href> tags -- only the hydrated DOM (captured via live_page_html)
        # has the real /work, /about, /contact, /services/ai, github links.
        assert result.evidence["checked"] >= 4
    finally:
        srv.shutdown()


def test_link_check_falls_back_to_its_own_playwright_render_when_no_live_page_given():
    """
    Companion test clarifying the actual contract: when there's no
    already-open browser session to reuse (live_page_html not supplied),
    LinkCheckAdapter's own standalone Playwright render is exactly what's
    supposed to run -- and it works fine in that isolated case, since
    D-055's bug was specifically about a SECOND sync_playwright()
    instance conflicting with an already-active one, not about the
    standalone fallback being broken in general.
    """
    from agents.capability.link_checker import LinkCheckAdapter
    from orchestrator.schemas import CapabilityCheckInput, CapabilityType

    srv = make_server(SPA_CLIENT_ROUTING_PAGE)
    try:
        url = server_url(srv)
        adapter = LinkCheckAdapter()
        result = adapter.run(
            CapabilityCheckInput(
                capability=CapabilityType.LINK_CHECK,
                target=url,
                params={"scope": "all"},  # no live_page_html supplied
            )
        )
        assert result.evidence["used_live_page"] is False
        assert result.evidence["rendered_via_playwright"] is True
        assert result.evidence["checked"] >= 4
    finally:
        srv.shutdown()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Tracked known limitation (docs/decisions.md D-056): the shape-based "
        "structural fallback in check_assertion() can tell 'nothing rendered' "
        "from 'something rendered', but not yet 'the right thing rendered' "
        "from 'an error rendered'. This test is expected to fail (xfail) "
        "until that's fixed -- if it ever unexpectedly passes, pytest will "
        "flag it (strict=True) as a signal to remove this marker and treat "
        "the limitation as closed."
    ),
)
def test_known_limitation_error_page_is_not_yet_detected_as_a_failed_assertion():
    """
    Real end-to-end reproduction of D-056's documented gap: a genuine
    500-error page, OCR'd for real (no mocks), against a sentence-shaped
    assertion describing successful load. Today this incorrectly passes,
    because the fallback only checks "is there readable text at all" --
    an error page has plenty. Kept as a real, running test (not just
    prose in decisions.md) specifically so a future fix is caught
    automatically instead of silently landing unnoticed.
    """
    from agents.vision.assertions import check_assertion
    from runtime.hooks import browser

    srv = make_server(FAKE_500_ERROR_PAGE)
    try:
        browser.open_url(server_url(srv), wait_seconds=0.1)
        from runtime.hooks.capture import capture_screenshot

        screenshot_path = capture_screenshot("aa1_known_limitation_run", 1)
        passed = check_assertion(
            screenshot_path,
            "The dashboard page has fully loaded and is displaying correctly.",
        )
        # Documents today's actual (wrong) behavior: this assertion
        # currently passes on an error page. The assert below is
        # deliberately the "bad" outcome -- xfail(strict=True) above is
        # what turns "this test's assertion holds" into a visible,
        # tracked gap rather than a silent false positive.
        assert passed is False
    finally:
        browser.close()
        srv.shutdown()
