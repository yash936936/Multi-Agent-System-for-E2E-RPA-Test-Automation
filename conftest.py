"""
Test-suite-wide isolation.

Two real leaks fixed here:

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
"""
from __future__ import annotations

import pytest


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

    yield