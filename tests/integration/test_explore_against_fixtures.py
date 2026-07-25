"""
tests/integration/test_explore_against_fixtures.py

Phase 0 (docs/AURA_REARCHITECTURE_PLAN.md, docs/decisions.md D-069).

Runs `orchestrator.ui_audit_runner.run_exploration` -- the actual engine
behind `aura explore` -- against real static HTML fixtures
(tests/fixtures/pages.py) served over a real local HTTP server and
rendered in a real headless Chromium, and asserts the report against a
committed answer key (tests/fixtures/answer_keys.py).

This is deliberately NOT a mock-based test. D-067's three real bugs
(footer heading falsely clickable, dom_smart_back()'s blind go_back()
masking a no-op click as a pass, --interactive accepting any screen
change) all slipped past 700+ existing unit tests precisely because
those tests assert behavior given assumed inputs -- they can't catch
"the assumption about what a real page looks like was wrong." These
tests are the acceptance gate every phase in
docs/AURA_REARCHITECTURE_PLAN.md after Phase 0 is validated against.
"""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from tests.conftest_local_server import make_server, server_url
from tests.fixtures.answer_keys import (
    ICON_ONLY_NAV_ANSWER_KEY,
    MARKETING_SITE_ANSWER_KEY,
    SPA_MUTATION_ANSWER_KEY,
)
from tests.fixtures.pages import ICON_ONLY_NAV_PAGE, MARKETING_SITE_PAGE, SPA_MUTATION_PAGE
from tests.integration.conftest import open_real_page_or_skip

pytestmark = pytest.mark.integration


def _real_screenshot_provider(tmp_dir: Path):
    """
    A ScreenshotProvider (orchestrator/ui_audit_runner.py's
    (run_id, index) -> path contract) backed by a real Playwright
    page.screenshot() call -- NOT runtime/hooks/capture.py's mss-based
    full-monitor capture. This tier only ever has a live Playwright page
    (that's the whole point), so there's no reason to route through the
    OS-level screenshot path at all here; using it would also make these
    tests fail in any headless CI container with no virtual display,
    defeating the purpose of a CI-runnable integration tier.
    """
    from runtime.hooks import browser

    def provider(run_id: str, index: int) -> str:
        path = tmp_dir / f"{run_id}_{index}.png"
        browser.get_page().screenshot(path=str(path))
        return str(path)

    return provider


def _find(report, element_id_or_label_substr: str):
    for c in report.checked:
        if element_id_or_label_substr.lower() in c.label.lower():
            return c
    return None


def test_marketing_site_landmarks_and_click_outcomes_match_answer_key():
    with tempfile.TemporaryDirectory() as d:
        tmp_dir = Path(d)
        srv = make_server(MARKETING_SITE_PAGE)
        try:
            url = server_url(srv)
            open_real_page_or_skip(url)

            from orchestrator.ui_audit_runner import run_exploration

            run_id = f"it_{uuid.uuid4().hex[:8]}"
            report = run_exploration(
                _real_screenshot_provider(tmp_dir),
                run_id,
                max_elements=25,
            )
        finally:
            from runtime.hooks import browser

            browser.close()
            srv.shutdown()

    key = MARKETING_SITE_ANSWER_KEY
    assert report.has_nav is key["has_nav"]
    assert report.has_hero is key["has_hero"]
    assert report.has_footer is key["has_footer"]

    # The footer heading is plain text, not a control -- it must never
    # appear as a checked (attempted-click) candidate at all. This is
    # the exact false positive D-067 fixed (docs/decisions.md D-067.5).
    heading_result = _find(report, key["must_not_be_clickable_text"])
    assert heading_result is None, (
        f"Footer heading {key['must_not_be_clickable_text']!r} was treated as a "
        "clickable candidate -- this is the exact false-positive class D-067 fixed."
    )

    # The genuinely dead button: a real click attempt is legitimate (it
    # IS a real <button>), but it must report state_changed=False, not
    # a false pass. This is the "reported passed but nothing happened"
    # bug class (docs/decisions.md D-067.6).
    dead = _find(report, "do nothing")
    assert dead is not None, "Dead button should have been a click candidate"
    assert dead.clicked is True
    assert dead.state_changed is key["dead_button_expected_state_changed"]

    # The real target="_blank" link: must be recognized as opening a
    # new tab, never silently folded into either state_changed=True (a
    # false "something happened here" on the original page) or a false
    # no-op.
    linkedin = _find(report, "linkedin")
    assert linkedin is not None
    assert linkedin.new_tab_opened is key["new_tab_link_expected_new_tab_opened"]

    # The real CTA: a genuine same-page DOM mutation, must be detected.
    cta = _find(report, "sign up")
    assert cta is not None
    assert cta.state_changed is key["working_button_expected_state_changed"]


def test_spa_mutation_without_navigation_is_detected():
    with tempfile.TemporaryDirectory() as d:
        tmp_dir = Path(d)
        srv = make_server(SPA_MUTATION_PAGE)
        try:
            url = server_url(srv)
            open_real_page_or_skip(url)
            url_before_click = url

            from orchestrator.ui_audit_runner import run_exploration

            run_id = f"it_{uuid.uuid4().hex[:8]}"
            report = run_exploration(_real_screenshot_provider(tmp_dir), run_id, max_elements=10)

            from runtime.hooks import browser

            url_after = browser.get_page().url
        finally:
            from runtime.hooks import browser

            browser.close()
            srv.shutdown()

    key = SPA_MUTATION_ANSWER_KEY
    assert report.has_nav is key["has_nav"]

    menu = _find(report, "menu")
    assert menu is not None
    assert menu.state_changed is key["menu_toggle_expected_state_changed"]
    # No real navigation should have happened for an in-page toggle --
    # this is the specific thing dom_smart_back()'s pre-D-067 blind
    # go_back() would have broken: it would have navigated the page
    # away regardless of whether the click itself did anything.
    assert (url_after != url_before_click) is key["menu_toggle_expected_url_changed"]


def test_icon_only_nav_detected_via_dom_not_ocr():
    with tempfile.TemporaryDirectory() as d:
        tmp_dir = Path(d)
        srv = make_server(ICON_ONLY_NAV_PAGE)
        try:
            url = server_url(srv)
            open_real_page_or_skip(url)

            from orchestrator.ui_audit_runner import run_exploration

            run_id = f"it_{uuid.uuid4().hex[:8]}"
            report = run_exploration(_real_screenshot_provider(tmp_dir), run_id, max_elements=10)
        finally:
            from runtime.hooks import browser

            browser.close()
            srv.shutdown()

    key = ICON_ONLY_NAV_ANSWER_KEY
    # This page has zero OCR-readable nav text -- has_nav=True here can
    # only come from the DOM-sourced element / merged-landmark fix
    # (docs/decisions.md D-067.5, agents/vision/dom_extractor.py's
    # to_ui_elements band classification).
    assert report.has_nav is key["has_nav"]
