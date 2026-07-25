"""
tests/integration/conftest.py

Phase 0 (docs/AURA_REARCHITECTURE_PLAN.md, docs/decisions.md D-069).
Everything under tests/integration/ runs against a real headless
Chromium and a real local HTTP server (tests/conftest_local_server.py),
no mocks -- these are the acceptance gate for the DOM-first-dispatch,
change-detection, and Brain-routing work that follows this phase.

Requires the Chromium binary. In sandboxes/CI where it isn't installed,
tests here skip cleanly (pytest.skip) with a clear reason instead of
erroring the whole run -- unlike tests/test_real_browser_fixtures.py's
existing real-browser tier, which currently has no such guard and shows
up as a hard error when the binary is missing (see docs/decisions.md
D-067's verification note: 30 failed / 5 errors, all attributable to
this). That's out of scope to change here; this new tier is built with
the skip guard from the start.
"""
from __future__ import annotations

import pytest

_MISSING_BINARY_MARKERS = ("Executable doesn't exist", "playwright install")


@pytest.fixture(autouse=True)
def _force_headless(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "playwright_headless", True)


@pytest.fixture(autouse=True)
def _enable_dom_extractor(monkeypatch):
    # This whole tier exists to validate the DOM-first path -- turn the
    # feature flag on for every test here rather than requiring each
    # test to remember it (config/settings.py's default is False,
    # matching AURA_ENABLE_DOM_EXTRACTOR's opt-in rollout posture).
    from config.settings import settings

    monkeypatch.setattr(settings, "enable_dom_extractor", True)


def open_real_page_or_skip(url: str, wait_seconds: float = 0.3):
    """
    Shared helper: open `url` in a real Playwright/Chromium session,
    skipping the calling test cleanly if the Chromium binary itself
    isn't installed in this environment, rather than failing.
    """
    from runtime.hooks import browser

    try:
        browser.open_url(url, wait_seconds=wait_seconds)
    except Exception as e:
        if any(marker in str(e) for marker in _MISSING_BINARY_MARKERS):
            pytest.skip(f"Chromium binary not available in this environment: {e}")
        raise
    return browser.get_page()
