"""
aura/cli/explain_cmd.py

Re-architecture Phase 1 (docs/AURA_REARCHITECTURE_PLAN.md, docs/decisions.md
D-072): `aura explain <run_id>` -- prints the merged, chronological timeline
of every logged decision for one run (planner backend attempts/escalations,
every click-audit decision, every assertion check), built on
`orchestrator/run_timeline.py`.

`--json` prints the raw merged timeline (machine-readable). The plan's
`--screenshot` overlay flag is intentionally not implemented in this pass --
flagged as follow-on work, not silently dropped (see docs/decisions.md
D-072's "explicitly deferred" note).
"""
from __future__ import annotations

import json

from rich.console import Console

console = Console()


def explain(run_id: str, as_json: bool = False) -> None:
    from orchestrator.run_timeline import build_timeline

    events = build_timeline(run_id)

    if as_json:
        print(json.dumps([e.__dict__ for e in events], indent=2))
        return

    if not events:
        console.print(f"[yellow]No logged decisions found for run_id={run_id!r}. "
                       f"Either the run_id is wrong, or it predates these logs.[/yellow]")
        return

    console.print(f"[bold]Timeline for run {run_id}[/bold] ({len(events)} events)\n")
    for e in events:
        color = {"decision_trace": "cyan", "assertion": "magenta", "click_resolution": "green"}.get(e.kind, "white")
        console.print(f"[{color}]{e.timestamp}[/{color}]  {e.summary}")
