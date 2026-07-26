"""
aura audit-report — aura/cli/audit_report_cmd.py

Resolves a real doc/code drift found and flagged (not silently fixed)
during D-072: `docs/STATUS.md`'s D-061 entry claimed `aura audit-report`
shipped as a CLI command, but it never existed -- D-072 built the
underlying merge layer (`orchestrator/run_timeline.py`) and
`aura explain` on top of it, but explicitly deferred `audit-report`
itself. This is that deferred piece, built per the original plan's own
description: "audit-report becomes a thin wrapper that calls into the
same timeline layer, so there's one merge implementation, not two."

`aura audit-report <run_id>` runs both existing `find_anomalies()`
checks (`orchestrator/assertion_audit_log.py`'s D-056 shape --
`escalate=False` with `passed=False`; `orchestrator/click_resolution_log.py`'s
D-067 shape -- `clicked=True` with `state_changed=False`) against that
run_id and prints anything found. `--full` additionally prints the
complete merged timeline (reusing `orchestrator/run_timeline.py`
directly -- the same one `aura explain` uses, not a second
implementation).
"""
from __future__ import annotations

from rich.console import Console

console = Console()


def audit_report(run_id: str, full: bool = False) -> None:
    from orchestrator.assertion_audit_log import assertion_audit_log
    from orchestrator.assertion_audit_log import find_anomalies as find_assertion_anomalies
    from orchestrator.click_resolution_log import click_resolution_log
    from orchestrator.click_resolution_log import find_anomalies as find_click_anomalies

    assertion_anomalies = find_assertion_anomalies(filepath=assertion_audit_log.filepath, run_id=run_id)
    click_anomalies = find_click_anomalies(filepath=click_resolution_log.filepath, run_id=run_id)

    console.print(f"[bold]Audit report for run {run_id}[/bold]\n")

    if not assertion_anomalies and not click_anomalies:
        console.print("[green]No anomalies found.[/green] (No record of a step that "
                       "passed through without escalating despite failing evidence, and no "
                       "click that reported clicked=True with no detected state change.)")
    else:
        if assertion_anomalies:
            console.print(f"[yellow]{len(assertion_anomalies)} assertion anomaly(ies)[/yellow] "
                           "(D-056 shape: escalate=False but passed=False -- a step that should "
                           "have been flagged for review but wasn't):")
            for a in assertion_anomalies:
                console.print(f"  [dim]step {a.get('step_id')}: expected_state={a.get('expected_state')!r}[/dim]")
        if click_anomalies:
            console.print(f"[yellow]{len(click_anomalies)} click anomaly(ies)[/yellow] "
                           "(D-067 shape: clicked=True but state_changed=False -- a possibly "
                           "non-functional element):")
            for c in click_anomalies:
                console.print(f"  [dim]{c.get('label')} ({c.get('band')}) -- resolved via {c.get('resolution_strategy')}, "
                               f"change detection: {c.get('change_detection_method', 'unknown')}[/dim]")

    if full:
        from orchestrator.run_timeline import build_timeline

        events = build_timeline(run_id)
        console.print(f"\n[bold]Full timeline[/bold] ({len(events)} events):")
        for e in events:
            color = {"decision_trace": "cyan", "assertion": "magenta", "click_resolution": "green"}.get(e.kind, "white")
            console.print(f"  [{color}]{e.timestamp}[/{color}]  {e.summary}")
