"""
Regression test for docs/decisions.md D-092: the root conftest.py's
autouse fixture now snapshots/restores a handful of `settings` singleton
fields around every test, specifically to stop a mutation made directly
on the singleton in one test file (no monkeypatch, no teardown) from
leaking into every alphabetically-later test file for the rest of the
session -- confirmed as the real root cause of an intermittent
test_executor_dom_path.py failure on a real Windows run, caused by a
since-identified stale/orphaned duplicate of test_cross_browser.py that
predated this isolation and had no restoring teardown of its own.

This test simulates that exact leak shape directly (mutate the
singleton with no teardown, inside what looks like "another test run")
and confirms the *next* test still sees the original value -- proving
the autouse fixture's own yield-then-restore logic actually protects
against it, independent of whether the offending file still exists.
"""
from __future__ import annotations

from config.settings import settings


def test_a_leaks_a_direct_settings_mutation_with_no_teardown():
    """
    Simulates the exact shape of the bug: a test mutates the shared
    singleton directly, the way the stale test_browser_hooks.py did, with
    no monkeypatch and no restoring teardown of its own. Named to sort
    alphabetically before the assertion test below, matching how
    test_browser_hooks.py (b) sorted before test_executor_dom_path.py (e)
    in the real failing run.
    """
    assert settings.playwright_browser == "chromium"
    settings.playwright_browser = "firefox"
    # Deliberately no restore here -- the root conftest.py autouse fixture
    # is what's responsible for cleaning this up between tests, not this
    # test's own discipline (a stale file, by definition, won't have any).


def test_b_previous_tests_direct_mutation_did_not_leak_here():
    """
    If the root conftest.py fix were missing (or broken), this would see
    "firefox" left over from the test above, exactly as
    test_dual_verification_disagreement_falls_back_when_winner_dispatch_fails
    silently did on a real Windows run -- which made
    get_click_point_in_page() return None for a reason invisible to that
    test's own code or fixtures, forcing an untranslated OS-level click
    that missed its target.
    """
    assert settings.playwright_browser == "chromium", (
        "settings.playwright_browser leaked across test files -- the root "
        "conftest.py autouse isolation fixture should have restored it "
        "after the previous test."
    )
