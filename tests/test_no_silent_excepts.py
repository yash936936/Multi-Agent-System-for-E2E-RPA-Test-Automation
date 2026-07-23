"""
tests/test_no_silent_excepts.py

AA3 (docs/decisions.md D-057) -- wires scripts/check_silent_excepts.py
into the normal pytest run so a new silent `except Exception: return
<default>` block fails CI immediately, instead of waiting for someone
to notice the symptom in a live run months later (as happened with
D-055's `_render_with_playwright` bug).
"""
from __future__ import annotations

from pathlib import Path

from scripts.check_silent_excepts import DEFAULT_SCAN_DIRS, find_silent_excepts, ALLOWLIST


def test_no_new_silent_except_blocks_in_core_source():
    repo_root = Path(__file__).resolve().parent.parent

    all_offenses = []
    for scan_dir in DEFAULT_SCAN_DIRS:
        scan_path = repo_root / scan_dir
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

    assert not real_offenses, (
        "Found silent `except Exception: return <default>` block(s) with no logging call: "
        + ", ".join(f"{f.relative_to(repo_root)}:{ln} (returns {val!r})" for f, ln, val in real_offenses)
        + ". Either add a logging.warning/.error/.exception call inside the except block, "
        "or add a reasoned entry to ALLOWLIST in scripts/check_silent_excepts.py."
    )
