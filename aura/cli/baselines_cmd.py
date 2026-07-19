"""
aura baselines — aura/cli/baselines_cmd.py

Phase Z (decisions.md D-052): closes the "natural, small follow-up" D-027
explicitly flagged and left undone -- a CLI command for reviewing/
approving a new visual-regression baseline when a legitimate UI change
causes an expected diff, instead of the only prior option (manually
deleting the file under runtime/baselines/ and re-running).

    aura baselines list
    aura baselines approve <key> --screenshot <path>
    aura baselines reject <key>
"""
from __future__ import annotations

from rich.console import Console
from rich.table import Table

from agents.vision import visual_regression

console = Console()


def list_baselines() -> None:
    """`aura baselines list` -- shows every stored baseline key, its size,
    when it was last updated, and whether it currently has an unresolved
    (failing) diff pending review."""
    rows = visual_regression.list_baselines()
    if not rows:
        console.print("[dim]No visual-regression baselines stored yet under runtime/baselines/.[/dim]")
        return

    table = Table(title="Visual regression baselines")
    table.add_column("Key")
    table.add_column("Size")
    table.add_column("Last updated")
    table.add_column("Pending diff?")
    for row in rows:
        pending = "[yellow]YES -- run 'approve' or 'reject'[/yellow]" if row["has_pending_diff"] else "[green]no[/green]"
        table.add_row(row["baseline_key"], f"{row['size_bytes']:,} bytes", row["modified_at"], pending)
    console.print(table)


def approve_baseline(baseline_key: str, screenshot_path: str) -> None:
    """`aura baselines approve <key> --screenshot <path>` -- accepts the
    screenshot at `screenshot_path` as the new baseline for `key`,
    replacing the old one, and clears any pending diff flag. Use this
    after confirming a flagged visual difference was an intentional UI
    change, not a regression."""
    try:
        new_path = visual_regression.approve_baseline_from_path(baseline_key, screenshot_path)
    except visual_regression.BaselineNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise SystemExit(1)
    except (FileNotFoundError, OSError) as exc:
        console.print(f"[red]Could not read screenshot at '{screenshot_path}': {exc}[/red]")
        raise SystemExit(1)
    console.print(f"[green]Approved new baseline for '{baseline_key}'[/green] -> {new_path}")


def reject_diff(baseline_key: str) -> None:
    """`aura baselines reject <key>` -- discards the pending diff artifact
    without touching the stored baseline. Use this after confirming a
    flagged visual difference WAS a real regression -- the stored baseline
    is left as-is (the correct/expected appearance), and the flag clears so
    it doesn't keep showing as pending once you've filed a bug for it."""
    cleared = visual_regression.reject_pending_diff(baseline_key)
    if cleared:
        console.print(f"[yellow]Cleared pending diff flag for '{baseline_key}'[/yellow] -- baseline itself is unchanged.")
    else:
        console.print(f"[dim]No pending diff found for '{baseline_key}' -- nothing to clear.[/dim]")
