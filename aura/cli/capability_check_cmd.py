"""
aura capability-check — aura/cli/capability_check_cmd.py

Phase B3 (docs/decisions.md D-075): `capability_check` was listed as an
`IntentKind` since B1 but had no CLI command at all -- only reachable
as a `CAPABILITY_CHECK` step *inside* a spec, dispatched through
`orchestrator/kernel.py`'s `ToolCall("Capability.check", ...)` contract.
This is that exact same contract, exposed directly: check one backend
capability (an API endpoint, a DB row, a file, ...) without writing a
whole spec around it.
"""
from __future__ import annotations

import json

from aura.tui import live_view
from orchestrator.brain import AuraBrain, Intent

console = live_view.console


def capability_check(capability_type: str, target: str, params: str | None = None, expected: str | None = None) -> None:
    """
    capability_type: one of orchestrator/schemas.py's CapabilityType
    values (api, database, email, file_system, excel, cloud, pdf_ocr,
    workflow, azure_blob, fake, ...) -- run `aura capability-check
    --help` or see that enum for the full current list.
    target: adapter-specific (a URL for api, a table/query for
    database, a path for file_system, etc.) -- same meaning as a spec
    step's `target` field.
    params / expected: JSON strings, parsed here -- same shape as a
    spec step's `capability_params` / `expected` fields.
    """
    parsed_params = json.loads(params) if params else {}
    parsed_expected = json.loads(expected) if expected else {}

    intent = Intent(
        kind="capability_check",
        params={"capability_type": capability_type, "target": target, "params": parsed_params, "expected": parsed_expected},
    )
    result = AuraBrain().handle(intent)

    if result.data["error"]:
        console.print(f"[red]Capability check failed: {result.data['error']}[/red]")
        return

    cap_result = result.data["result"]
    status = "[green]PASSED[/green]" if cap_result.passed else "[red]FAILED[/red]"
    console.print(f"{status} — {capability_type} check against '{target}' (confidence: {cap_result.confidence:.2f})")
    if cap_result.evidence:
        console.print(f"[dim]Evidence: {json.dumps(cap_result.evidence, indent=2, default=str)}[/dim]")
    if cap_result.escalate:
        console.print("[yellow]Flagged for escalation/review.[/yellow]")
