#!/usr/bin/env python3
"""
scripts/remove_stale_tests.py

Deletes test files confirmed to be orphaned leftovers from before earlier
phases removed/renamed the code they test against (see docs/decisions.md
D-091/D-092). These accumulate when a delivered zip is extracted on top
of an existing working directory: extraction adds/updates files but
never deletes ones that no longer exist in the new archive.

One of these (tests/test_browser_hooks.py) is not just noise -- it
mutates the shared `settings` singleton with no teardown and was
confirmed to leak into and break an unrelated, otherwise-passing test
later in the same run (D-092). Safe to delete: each one is superseded by
a current, non-stale equivalent already in this codebase (see the
mapping below).

Usage: python scripts/remove_stale_tests.py [--dry-run]
"""
from __future__ import annotations

import sys
from pathlib import Path

_STALE_FILES = [
    # path                                          superseded by
    "tests/integration/test_explore_against_fixtures.py",  # explore removed in Phase 0; see tests/test_ui_audit_runner.py
    "tests/test_explore_cmd.py",                            # -> tests/test_audit_report_cmd.py, tests/test_ui_audit.py
    "tests/test_browser_hooks.py",                           # -> tests/test_browser_hook.py, tests/test_cross_browser.py
    "tests/test_reporting.py",                               # -> tests/test_decision_trace_log.py, tests/test_click_resolution_log.py
    "tests/test_vision_dom.py",                              # -> tests/test_executor_dom_path.py
]


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    root = Path(__file__).resolve().parent.parent

    removed = []
    missing = []
    for rel_path in _STALE_FILES:
        path = root / rel_path
        if not path.exists():
            missing.append(rel_path)
            continue
        if dry_run:
            print(f"[dry-run] would remove: {rel_path}")
        else:
            path.unlink()
            print(f"Removed: {rel_path}")
        removed.append(rel_path)

    if missing:
        print("\nAlready absent (nothing to do):")
        for rel_path in missing:
            print(f"  {rel_path}")

    if not removed:
        print("Nothing to remove -- your working directory is already clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
