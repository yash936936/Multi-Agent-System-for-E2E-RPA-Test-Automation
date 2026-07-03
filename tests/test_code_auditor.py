"""
tests/test_code_auditor.py

Covers agents/auditor/code_auditor.py -- the "go through files and detect
bugs, don't fix them" feature. Each check here corresponds to a real bug
pattern this project's own manual QA passes caught (decisions.md D-011
and the phase-6 finalize sweep).
"""
from __future__ import annotations

from pathlib import Path

from agents.auditor.code_auditor import audit_file, audit_path


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_audit_file_detects_syntax_error(tmp_path):
    f = _write(tmp_path, "broken.py", "def foo(:\n    pass\n")
    findings = audit_file(f)
    assert any(x.rule == "syntax-error" for x in findings)
    assert any(x.severity == "error" for x in findings)


def test_audit_file_detects_mutable_default_arg(tmp_path):
    f = _write(tmp_path, "bad.py", "def foo(items=[]):\n    items.append(1)\n    return items\n")
    findings = audit_file(f)
    assert any(x.rule == "mutable-default-arg" for x in findings)


def test_audit_file_does_not_flag_immutable_default(tmp_path):
    f = _write(tmp_path, "ok.py", "def foo(items=None):\n    items = items or []\n    return items\n")
    findings = audit_file(f)
    assert not any(x.rule == "mutable-default-arg" for x in findings)


def test_audit_file_detects_silent_exception_swallow(tmp_path):
    f = _write(tmp_path, "swallow.py", "try:\n    risky()\nexcept Exception:\n    pass\n")
    findings = audit_file(f)
    assert any(x.rule == "silent-exception-swallow" for x in findings)


def test_audit_file_does_not_flag_except_with_real_handling(tmp_path):
    f = _write(tmp_path, "ok.py", "try:\n    risky()\nexcept Exception as e:\n    log.error(e)\n")
    findings = audit_file(f)
    assert not any(x.rule == "silent-exception-swallow" for x in findings)


def test_audit_file_detects_bare_except(tmp_path):
    f = _write(tmp_path, "bare.py", "try:\n    risky()\nexcept:\n    handle()\n")
    findings = audit_file(f)
    assert any(x.rule == "bare-except" for x in findings)


def test_audit_file_detects_todo_marker(tmp_path):
    f = _write(tmp_path, "todo.py", "x = 1  # TODO: fix this properly\n")
    findings = audit_file(f)
    assert any(x.rule == "todo-marker" for x in findings)


def test_audit_file_detects_unmanaged_file_handle(tmp_path):
    f = _write(tmp_path, "leak.py", "f = open('data.txt')\ndata = f.read()\n")
    findings = audit_file(f)
    assert any(x.rule == "unmanaged-file-handle" for x in findings)


def test_audit_file_does_not_flag_context_managed_open(tmp_path):
    f = _write(tmp_path, "ok.py", "with open('data.txt') as f:\n    data = f.read()\n")
    findings = audit_file(f)
    assert not any(x.rule == "unmanaged-file-handle" for x in findings)


def test_audit_file_clean_file_has_no_findings(tmp_path):
    f = _write(tmp_path, "clean.py", "def add(a, b):\n    return a + b\n")
    findings = audit_file(f)
    assert findings == []


def test_audit_file_never_modifies_the_file(tmp_path):
    f = _write(tmp_path, "bad.py", "def foo(items=[]):\n    return items\n")
    original = f.read_text(encoding="utf-8")
    audit_file(f)
    assert f.read_text(encoding="utf-8") == original


def test_audit_path_scans_directory_recursively(tmp_path):
    (tmp_path / "sub").mkdir()
    _write(tmp_path, "a.py", "def foo(items=[]):\n    return items\n")
    _write(tmp_path / "sub", "b.py", "try:\n    x()\nexcept:\n    pass\n")

    report = audit_path(tmp_path, run_ruff=False)
    assert report.files_scanned == 2
    rules_found = {f.rule for f in report.findings}
    assert "mutable-default-arg" in rules_found
    assert "bare-except" in rules_found or "silent-exception-swallow" in rules_found


def test_audit_path_skips_venv_and_pycache_directories(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / "__pycache__").mkdir()
    _write(tmp_path / ".venv", "lib.py", "def foo(items=[]):\n    return items\n")
    _write(tmp_path / "__pycache__", "cached.py", "def foo(items=[]):\n    return items\n")
    _write(tmp_path, "real.py", "def bar():\n    return 1\n")

    report = audit_path(tmp_path, run_ruff=False)
    assert report.files_scanned == 1


def test_audit_path_single_file(tmp_path):
    f = _write(tmp_path, "single.py", "def foo(items=[]):\n    return items\n")
    report = audit_path(f, run_ruff=False)
    assert report.files_scanned == 1
    assert not report.clean


def test_code_audit_report_errors_and_warnings_properties(tmp_path):
    f = _write(tmp_path, "mixed.py", "def foo(:\n")  # syntax error only
    report = audit_path(f, run_ruff=False)
    assert len(report.errors) >= 1
    assert report.clean is False


def test_code_audit_report_clean_when_no_findings(tmp_path):
    f = _write(tmp_path, "clean.py", "def add(a, b):\n    return a + b\n")
    report = audit_path(f, run_ruff=False)
    assert report.clean is True
    assert report.errors == []
    assert report.warnings == []
