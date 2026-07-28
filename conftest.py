"""
Test-suite-wide isolation.

Three real leaks fixed here:

1. runtime/hooks/interact.py drives pyautogui for real whenever it can be
   imported -- true on any machine with a live desktop session (e.g. a
   Windows dev box), not just "when a display exists". Without this guard,
   running the e2e RunEngine test can move your actual mouse cursor and
   trip PyAutoGUI's corner fail-safe.

2. config/settings.py's Settings loads a real .env file from whatever the
   process cwd happens to be, independent of any `project_root` passed
   into the constructor. If a real .env sits in the repo root (it's
   gitignored, so it's easy to forget it's there) with e.g.
   AURA_LOCAL_LLM_MODEL_PATH set, every Settings(...) call in every test
   picks that value up regardless of what the test is trying to assert.

3. `config.settings.settings` is a single module-level singleton shared by
   every test file in the whole session (not a fresh instance per test),
   and a number of test files mutate its fields directly
   (`settings.playwright_browser = "firefox"`, etc.) rather than via
   `monkeypatch.setattr`. When such a test has no restoring teardown of
   its own, the mutation leaks into every alphabetically-later test file
   for the rest of the pytest run -- confirmed as the real root cause of
   an intermittent `test_executor_dom_path.py` failure on a real Windows
   run: an orphaned, stale duplicate of test_cross_browser.py (which
   *does* correctly save/restore this field around its own tests) set
   `settings.playwright_browser = "firefox"` with no teardown, silently
   disabling `get_click_point_in_page`'s CDP-based coordinate translation
   (it early-returns None whenever `playwright_browser != "chromium"`)
   for every subsequent test in that session, forcing a raw/untranslated
   OS-level click that missed its target. Rather than rely on every test
   file remembering its own save/restore discipline (a stale file can't
   be relied on to have it, by definition), this snapshots and restores
   the handful of fields test files are actually seen mutating directly,
   session-wide, so a leak like this can't survive past the test that
   caused it -- regardless of what other test files (existing, stale, or
   future) do or don't clean up themselves.
"""
from __future__ import annotations

import pytest

from config.settings import settings as _global_settings

_MUTABLE_SETTINGS_FIELDS = (
    "playwright_browser",
    "playwright_headless",
    "record_video",
    "record_trace",
)


@pytest.fixture(autouse=True)
def _isolate_from_real_environment(monkeypatch):
    # Never let tests dispatch real mouse/keyboard events.
    monkeypatch.setenv("AURA_DISABLE_DISPATCH", "1")

    # Never let a real local .env / exported shell env leak into tests
    # that construct Settings() expecting clean defaults.
    for var in (
        "AURA_LOCAL_LLM_MODEL_PATH",
        "AURA_PLANNER_BACKEND",
        "AURA_TESSERACT_CMD",
        "AURA_ALLOW_NETWORK_CALLS",
    ):
        monkeypatch.delenv(var, raising=False)

    # Snapshot/restore fields on the shared settings singleton that tests
    # are seen mutating directly (not via monkeypatch) -- see leak #3
    # above. monkeypatch.setattr would be the ideal fix in each such test,
    # but this session-wide safety net doesn't depend on every test file
    # (including ones that may not even exist in this codebase yet) doing
    # that correctly.
    originals = {field: getattr(_global_settings, field) for field in _MUTABLE_SETTINGS_FIELDS}

    yield

    for field, value in originals.items():
        setattr(_global_settings, field, value)