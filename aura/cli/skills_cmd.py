"""
aura skills — aura/cli/skills_cmd.py

Thin CLI wrapper over orchestrator/skill_store.py:
    aura skills list
    aura skills export --app <id> > pack.json
matching APPFLOW.md §2.9.
"""
from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

from orchestrator import quarantine_store
from orchestrator.skill_store import SkillStore

console = Console()


def quarantine_test(test_id: str, reason: str | None = None) -> None:
    """`aura skills quarantine <test_id>` -- Phase H2. Opt-in only; nothing
    in this codebase quarantines a test automatically."""
    quarantine_store.quarantine(test_id, reason=reason)
    console.print(f"[yellow]Quarantined {test_id}[/yellow]" + (f" -- {reason}" if reason else ""))
    console.print("[dim]`aura execute --all` will skip it until `aura skills unquarantine` or --include-quarantined.[/dim]")


def unquarantine_test(test_id: str) -> None:
    removed = quarantine_store.unquarantine(test_id)
    if removed:
        console.print(f"[green]Unquarantined {test_id}[/green]")
    else:
        console.print(f"[dim]{test_id} wasn't quarantined.[/dim]")


def list_quarantined() -> None:
    entries = quarantine_store.list_quarantined()
    if not entries:
        console.print("[dim]No tests are quarantined.[/dim]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("Test ID")
    table.add_column("Reason")
    table.add_column("Quarantined at")
    for test_id, meta in entries.items():
        table.add_row(test_id, meta.get("reason") or "-", meta.get("quarantined_at", "-"))
    console.print(table)


def list_skills(app_id: str | None = None) -> None:
    store = SkillStore()
    records = store.all(app_id=app_id)
    if not records:
        console.print("[dim]No skills learned yet.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Skill ID")
    table.add_column("Failure signature")
    table.add_column("Fix type")
    table.add_column("Confidence")
    table.add_column("Applied")
    for r in records:
        table.add_row(r.skill_id, r.failure_signature, r.fix_type.value, f"{r.confidence:.2f}", str(r.applied_count))
    console.print(table)


def export_skills(app_id: str | None, out_path: str | None) -> None:
    store = SkillStore()
    payload = store.export_skills(app_id=app_id)
    if out_path:
        Path(out_path).write_text(payload, encoding="utf-8")
        console.print(f"[green]Exported to {out_path}[/green]")
    else:
        # No path given -> print to stdout so `aura skills export --app x > pack.json` works too.
        print(payload)


def import_skills(path: str, app_id: str | None = None) -> None:
    store = SkillStore()
    count = store.import_from_file(Path(path), app_id=app_id)
    console.print(f"[green]Imported {count} skill(s) from {path}[/green]")


def diff_skills(before_path: str, after_path: str) -> None:
    """
    aura skills diff <before.json> <after.json>

    Compares two skill-pack exports (see `aura skills export`) and prints
    what the self-healer learned/changed between them -- lets a team
    review new/changed skills before trusting them in CI.
    """
    before_json = Path(before_path).read_text(encoding="utf-8")
    after_json = Path(after_path).read_text(encoding="utf-8")
    result = SkillStore.diff_snapshots(before_json, after_json)

    summary = result["summary"]
    console.print(
        f"[bold]{summary['added_count']} added[/bold], "
        f"[bold]{summary['changed_count']} changed[/bold], "
        f"[bold]{summary['removed_count']} removed[/bold], "
        f"{summary['unchanged_count']} unchanged"
    )

    if result["added"]:
        console.print("\n[green]Added:[/green]")
        for s in result["added"]:
            console.print(f"  + {s['skill_id']}  ({s['failure_signature']})")

    if result["removed"]:
        console.print("\n[red]Removed:[/red]")
        for s in result["removed"]:
            console.print(f"  - {s['skill_id']}  ({s['failure_signature']})")

    if result["changed"]:
        console.print("\n[yellow]Changed:[/yellow]")
        for c in result["changed"]:
            console.print(f"  ~ {c['skill_id']}")
            for field, delta in c["changes"].items():
                console.print(f"      {field}: {delta['before']!r} -> {delta['after']!r}")

    if not (result["added"] or result["removed"] or result["changed"]):
        console.print("[dim]No differences.[/dim]")
