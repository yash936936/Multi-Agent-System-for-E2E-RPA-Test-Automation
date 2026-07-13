"""
aura debug — aura/cli/debug_cmd.py

The "go through files and detect bugs, don't fix them" command. Wraps
agents/auditor/code_auditor.py with the same Rich-table presentation
style as `aura execute`'s spec checklist, so this feels like one
consistent tool rather than a bolted-on separate script.

Detection only, by design (see code_auditor.py's module docstring) --
this command never modifies the files it scans.
"""
from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


def run_debug(path: str, out: str | None = None, no_ruff: bool = False) -> None:
    from agents.auditor.code_auditor import audit_path

    target = Path(path)
    if not target.exists():
        console.print(f"[red]No such file or directory: {path}[/red]")
        raise SystemExit(1)

    console.print(f"Scanning {target} for bugs (detection only — nothing will be modified)...")
    report = audit_path(target, run_ruff=not no_ruff)

    if report.clean:
        console.print(f"[green]Clean — no issues found across {report.files_scanned} file(s).[/green]")
        if out:
            _write_report_file(report, Path(out))
            console.print(f"Full report written to {out}")
        return

    table = Table(title=f"Code audit — {report.files_scanned} file(s) scanned")
    table.add_column("Severity", style="bold")
    table.add_column("File")
    table.add_column("Line", justify="right")
    table.add_column("Rule")
    table.add_column("Message")

    severity_style = {"error": "red", "warning": "yellow", "info": "dim"}
    # Errors first, then warnings, then info -- most actionable first.
    order = {"error": 0, "warning": 1, "info": 2}
    for finding in sorted(report.findings, key=lambda f: (order.get(f.severity, 9), f.file, f.line)):
        style = severity_style.get(finding.severity, "")
        table.add_row(
            f"[{style}]{finding.severity}[/{style}]" if style else finding.severity,
            finding.file,
            str(finding.line),
            finding.rule,
            finding.message,
        )

    console.print(table)
    console.print(
        f"\n{len(report.errors)} error(s), {len(report.warnings)} warning(s), "
        f"{len(report.findings) - len(report.errors) - len(report.warnings)} info finding(s)."
    )

    if out:
        _write_report_file(report, Path(out))
        console.print(f"Full report written to {out}")


def _write_report_file(report, out_path: Path) -> None:
    lines = ["# Code audit report", "", f"Files scanned: {report.files_scanned}", ""]
    if report.clean:
        lines.append("Clean — no issues found.")
    else:
        for finding in report.findings:
            lines.append(f"- **[{finding.severity}]** `{finding.file}:{finding.line}` ({finding.rule}) — {finding.message}")
    out_path.write_text("\n".join(lines), encoding="utf-8")
