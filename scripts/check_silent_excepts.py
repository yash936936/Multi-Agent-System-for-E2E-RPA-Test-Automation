"""
scripts/check_silent_excepts.py

AA3 (docs/decisions.md D-057) -- mechanical guard against silent
`except Exception: return <default>` blocks with no logging call. Every
real bug found in this session's debugging pass that involved a swallowed
exception fit this exact shape:

- `agents/capability/link_checker.py`'s `_render_with_playwright()`:
  `except Exception: return None` swallowed the nested-sync-Playwright
  conflict completely -- no log line, no way to tell "this failed" from
  "this legitimately found nothing" without reading the source.
- `agents/vision/assertions.py`'s `_check_page_rendered()` (before D-057):
  `except Exception: return True` treated "OCR tooling is broken" the
  same as "OCR ran and found content" with zero visibility.

This script (and the pytest wrapper below) doesn't ban `except Exception`
outright -- broad catches are sometimes the right call at a boundary --
it only flags catches that both (a) immediately return a
success/failure-shaped default (None/True/False/{}/[]/a bare literal)
and (b) have no logging call anywhere in the except block. That
combination is exactly what makes a failure invisible.

Usage:
    python3 scripts/check_silent_excepts.py            # scan default dirs
    python3 scripts/check_silent_excepts.py path1 path2 # scan specific paths

Exits non-zero (and prints every offending file:line) if any are found
outside the allowlist below.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

DEFAULT_SCAN_DIRS = ["agents", "orchestrator", "runtime", "aura", "reports", "config", "api"]

# Each entry: (relative_file_path, line_number_of_the_except_handler).
# Add an entry here (with a comment explaining why) for any genuinely
# intentional silent catch, rather than weakening the check itself.
# Line numbers are of the `except Exception` line itself.
ALLOWLIST: set[tuple[str, int]] = {
    # DOM snapshot extraction: a JS evaluate() failure here (detached
    # page, mid-navigation) is treated identically to "found nothing" by
    # every caller already (dom_locator.py's own snapshot/locate failure
    # shape matches this on purpose) -- logging every occurrence would be
    # noisy for what's an expected, frequent condition during normal
    # page-transition scanning, not a rare/actionable failure.
    ("agents/vision/dom_extractor.py", 153),
    # locator.bounding_box() failing just means "couldn't measure this
    # element's geometry right now" (stale reference, mid-animation) --
    # executor.py's own docstring above this function already documents
    # this as "evidence of couldn't measure, not a bug," and it falls
    # through to a documented tie-break path, not a silent wrong answer.
    ("agents/vision/dom_locator.py", 156),
    # run_ui_audit's real-link-check integration already has its own
    # try/except at the call site in orchestrator/ui_audit_runner.py
    # (see the `_logger.info(...)` a few lines above this one) -- the
    # inner except here is a narrower, deliberately-silent guard so a
    # partial/best-effort browser-content read never blocks the OCR-only
    # audit result that's already been computed by this point.
    ("orchestrator/ui_audit_runner.py", 117),
    # get_click_point_in_page's own docstring is explicit: "Returns None
    # -- never raises -- whenever this can't be computed" (no active
    # page, non-Chromium engine, unexpected window layout). This is the
    # expected/common path in several legitimate configurations, not a
    # rare failure -- logging it would be noisy, and the documented
    # contract already treats None as a normal, not exceptional, result
    # that callers (agents/vision/executor.py) explicitly check for and
    # fall back on.
    ("runtime/hooks/browser.py", 324),
}

_SUCCESS_SHAPED_RETURNS = {"None", "True", "False", "0", "[]", "{}", '""', "''"}


def _return_value_str(node: ast.Return) -> str | None:
    if node.value is None:
        return "None"
    try:
        return ast.unparse(node.value)
    except Exception:
        return None


def _contains_logging_call(nodes: list[ast.stmt]) -> bool:
    for stmt in nodes:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Call):
                func = sub.func
                # Matches logging.warning(...), logger.info(...), self._logger.error(...), etc.
                if isinstance(func, ast.Attribute) and func.attr in (
                    "debug", "info", "warning", "warn", "error", "exception", "critical", "log",
                ):
                    return True
    return False


def find_silent_excepts(path: Path) -> list[tuple[Path, int, str]]:
    """Returns (file, lineno, return_repr) for every offending handler in one file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return []

    offenses: list[tuple[Path, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        # Only care about broad `except Exception` (with or without `as e`),
        # not narrow/specific exception types -- those are usually already
        # a deliberate, well-scoped decision.
        if not (isinstance(node.type, ast.Name) and node.type.id == "Exception"):
            continue

        top_level_returns = [s for s in node.body if isinstance(s, ast.Return)]
        if not top_level_returns:
            continue  # doesn't immediately return a default -- re-raises, or does other handling

        has_logging = _contains_logging_call(node.body)
        if has_logging:
            continue

        for ret in top_level_returns:
            val = _return_value_str(ret)
            if val is not None and (val in _SUCCESS_SHAPED_RETURNS or val.strip("\"'") == ""):
                offenses.append((path, node.lineno, val))

    return offenses


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    scan_paths = [repo_root / p for p in (argv or DEFAULT_SCAN_DIRS)]

    all_offenses: list[tuple[Path, int, str]] = []
    for scan_path in scan_paths:
        if not scan_path.exists():
            continue
        for py_file in scan_path.rglob("*.py"):
            if "test" in py_file.parts or "__pycache__" in py_file.parts:
                continue
            all_offenses.extend(find_silent_excepts(py_file))

    real_offenses = [
        (f, ln, val) for (f, ln, val) in all_offenses
        if (str(f.relative_to(repo_root)), ln) not in ALLOWLIST
    ]

    if real_offenses:
        print("Silent `except Exception: return <default>` blocks found (no logging call):\n")
        for f, ln, val in sorted(real_offenses):
            print(f"  {f.relative_to(repo_root)}:{ln} -- returns {val!r}")
        print(
            f"\n{len(real_offenses)} offense(s). Each should either log the exception "
            "(logging.warning/.error/.exception with the caught exception included) or, "
            "if genuinely intentional, be added to ALLOWLIST in this script with a comment "
            "explaining why swallowing it silently is correct."
        )
        return 1

    print(f"No silent except-Exception blocks found (scanned {len(all_offenses)} candidate handlers, all clean or allowlisted).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
