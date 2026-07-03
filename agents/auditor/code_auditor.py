"""
Code auditor — agents/auditor/code_auditor.py

The "if it's going through files, detect bugs (don't fix them)" mode.
Static analysis only — no code execution, no network calls, matches
AURA's offline posture (decisions.md D-002) the same way the rest of the
system does. Two layers:

  1. AST-based structural checks (syntax errors, mutable default args,
     bare `except:`, silent `except Exception: pass`) -- deterministic,
     zero dependencies beyond the stdlib `ast` module.
  2. An optional `ruff` pass, if installed, for a much broader lint sweep
     (unused imports, unreachable code, etc) -- used as a supplementary
     signal, not a hard requirement, so this still works in an
     environment without ruff installed.

Every check here mirrors something this project's own QA passes have
caught by hand over the course of development (see decisions.md D-011:
unclosed PIL Image handles; the bare-except/mutable-default/silent-except
sweep run during the phase-6 finalize pass) -- this module exists to
automate exactly that manual review process.

Deliberately detection-only: CodeAuditFinding has no "fix" action and
nothing in this module writes to the files it inspects. A human (or a
separate, explicitly-invoked tool) decides what to do about a finding.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CodeAuditFinding:
    file: str
    line: int
    rule: str
    severity: str  # "error" | "warning" | "info"
    message: str


@dataclass
class CodeAuditReport:
    files_scanned: int
    findings: list[CodeAuditFinding] = field(default_factory=list)

    @property
    def errors(self) -> list[CodeAuditFinding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> list[CodeAuditFinding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def clean(self) -> bool:
        return len(self.findings) == 0


_BARE_EXCEPT_RE = re.compile(r"^\s*except\s*:\s*$")
_TODO_RE = re.compile(r"#\s*(TODO|FIXME|XXX)\b", re.IGNORECASE)
_UNMANAGED_OPEN_RE = re.compile(r"^\s*\w[\w.\[\]]*\s*=\s*open\(")


def _check_syntax(file_path: Path, source: str) -> tuple[ast.AST | None, list[CodeAuditFinding]]:
    try:
        tree = ast.parse(source, filename=str(file_path))
        return tree, []
    except SyntaxError as e:
        return None, [
            CodeAuditFinding(
                file=str(file_path),
                line=e.lineno or 0,
                rule="syntax-error",
                severity="error",
                message=f"SyntaxError: {e.msg}",
            )
        ]


def _check_mutable_defaults(file_path: Path, tree: ast.AST) -> list[CodeAuditFinding]:
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for default in node.args.defaults + node.args.kw_defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                findings.append(
                    CodeAuditFinding(
                        file=str(file_path),
                        line=node.lineno,
                        rule="mutable-default-arg",
                        severity="warning",
                        message=f"Function '{node.name}' has a mutable default argument (list/dict/set) — shared across all calls, a classic source of hard-to-trace bugs.",
                    )
                )
    return findings


def _check_silent_except(file_path: Path, tree: ast.AST) -> list[CodeAuditFinding]:
    findings = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body_is_pass_only = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
        if body_is_pass_only:
            exc_desc = "bare except" if node.type is None else f"except {ast.dump(node.type, annotate_fields=False) if not isinstance(node.type, ast.Name) else node.type.id}"
            findings.append(
                CodeAuditFinding(
                    file=str(file_path),
                    line=node.lineno,
                    rule="silent-exception-swallow",
                    severity="warning",
                    message=f"{exc_desc}: caught and silently ignored (bare 'pass') — errors here vanish without a trace.",
                )
            )
    return findings


def _check_bare_except_lines(file_path: Path, lines: list[str]) -> list[CodeAuditFinding]:
    findings = []
    for i, line in enumerate(lines, start=1):
        if _BARE_EXCEPT_RE.match(line):
            findings.append(
                CodeAuditFinding(
                    file=str(file_path),
                    line=i,
                    rule="bare-except",
                    severity="warning",
                    message="Bare 'except:' catches everything including KeyboardInterrupt/SystemExit — use 'except Exception:' at minimum.",
                )
            )
    return findings


def _check_todo_markers(file_path: Path, lines: list[str]) -> list[CodeAuditFinding]:
    findings = []
    for i, line in enumerate(lines, start=1):
        if _TODO_RE.search(line):
            findings.append(
                CodeAuditFinding(file=str(file_path), line=i, rule="todo-marker", severity="info", message=line.strip())
            )
    return findings


def _check_unmanaged_file_handles(file_path: Path, lines: list[str]) -> list[CodeAuditFinding]:
    """
    Flags `x = open(...)` assignments not immediately preceded by `with` on
    the same logical statement -- the exact pattern that caused a real,
    shipped bug in this project (decisions.md D-011: PIL Image.open()
    without a context manager leaked a file handle and blocked cleanup on
    Windows). Simple line-based heuristic, not a full data-flow analysis --
    flags candidates for a human/deeper tool to confirm, doesn't claim
    certainty.
    """
    findings = []
    for i, line in enumerate(lines, start=1):
        if _UNMANAGED_OPEN_RE.match(line) and "with " not in line:
            findings.append(
                CodeAuditFinding(
                    file=str(file_path),
                    line=i,
                    rule="unmanaged-file-handle",
                    severity="info",
                    message="File opened without 'with' — confirm the handle is explicitly closed, or use a context manager (this exact pattern caused a real leaked-handle bug in this project; see decisions.md D-011).",
                )
            )
    return findings


def audit_file(file_path: Path) -> list[CodeAuditFinding]:
    try:
        source = file_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as e:
        return [CodeAuditFinding(file=str(file_path), line=0, rule="unreadable-file", severity="error", message=str(e))]

    lines = source.splitlines()
    tree, syntax_findings = _check_syntax(file_path, source)
    findings = list(syntax_findings)

    if tree is not None:
        findings.extend(_check_mutable_defaults(file_path, tree))
        findings.extend(_check_silent_except(file_path, tree))

    findings.extend(_check_bare_except_lines(file_path, lines))
    findings.extend(_check_todo_markers(file_path, lines))
    findings.extend(_check_unmanaged_file_handles(file_path, lines))

    return findings


def audit_path(path: str | Path, run_ruff: bool = True) -> CodeAuditReport:
    """
    Walks `path` (a single .py file, or a directory scanned recursively
    for .py files) and returns a CodeAuditReport. Detection only -- never
    modifies any file it scans.
    """
    root = Path(path)
    if root.is_file():
        files = [root] if root.suffix == ".py" else []
    else:
        files = sorted(root.rglob("*.py"))
        # Skip virtual envs / build artifacts / caches -- scanning those
        # produces noise about code the user doesn't own and can't fix.
        files = [
            f for f in files
            if not any(part in {".venv", "venv", "__pycache__", "build", "dist", ".git", "node_modules"} for part in f.parts)
        ]

    all_findings: list[CodeAuditFinding] = []
    for f in files:
        all_findings.extend(audit_file(f))

    if run_ruff:
        all_findings.extend(_run_ruff(root))

    return CodeAuditReport(files_scanned=len(files), findings=all_findings)


def _run_ruff(root: Path) -> list[CodeAuditFinding]:
    """
    Optional supplementary pass via ruff (already a project dev dependency),
    for a much broader lint sweep than the hand-written checks above cover.
    Best-effort: if ruff isn't installed or the call fails for any reason,
    returns an empty list rather than failing the whole audit -- the
    AST/regex checks above are the guaranteed baseline.
    """
    import json
    import subprocess

    try:
        result = subprocess.run(
            ["ruff", "check", str(root), "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if not result.stdout.strip():
        return []

    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    findings = []
    for entry in entries:
        findings.append(
            CodeAuditFinding(
                file=entry.get("filename", str(root)),
                line=(entry.get("location") or {}).get("row", 0),
                rule=f"ruff:{entry.get('code', '?')}",
                severity="warning",
                message=entry.get("message", ""),
            )
        )
    return findings
