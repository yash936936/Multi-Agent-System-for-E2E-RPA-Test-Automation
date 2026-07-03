"""
Live TUI views — aura/tui/live_view.py

`rich`-based rendering for the human-facing surfaces described in
APPFLOW.md:
    §2.3  spec-approval checklist
    §2.4  live step ticker
    §2.5  healed-step accept/reject checkpoint
    §2.7  "Needs Review" escalation queue

Kept free of any orchestrator/agent imports beyond the schema types, so
this module is just presentation — aura/cli/execute_cmd.py owns the
control flow and calls into these functions.
"""
from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from orchestrator.schemas import TestSpec, VisionActionResult

console = Console()


# --------------------------------------------------------------------------
# APPFLOW §2.3 — spec approval checklist
# --------------------------------------------------------------------------

def render_spec_checklist(spec: TestSpec) -> None:
    console.print(f"\n[bold]{spec.test_id}[/bold]: {spec.requirement_ref}")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Step", width=6)
    table.add_column("Action")
    table.add_column("Target / Field")
    table.add_column("Expected state")
    for step in spec.steps:
        target = step.target_description or step.field_description or ""
        table.add_row(str(step.step_id), step.action.value, target, step.expected_state or "")
    console.print(table)
    if spec.data_requirements:
        console.print(f"[dim]Data requirements: {', '.join(spec.data_requirements)}[/dim]")


def confirm_spec_approval(auto_approve: bool = False) -> bool:
    """Human checkpoint — nothing executes against the live app without this."""
    if auto_approve:
        console.print("[dim]--yes passed, skipping interactive approval.[/dim]")
        return True
    console.print()
    answer = console.input("[bold]Approve this test spec for execution? \\[y/N]: [/bold]").strip().lower()
    return answer == "y"


# --------------------------------------------------------------------------
# APPFLOW §2.4 — live step ticker
# --------------------------------------------------------------------------

def step_start(step_id: int, total: int, description: str) -> None:
    console.print(f"▶ Step {step_id}/{total}: {description}  [dim][executing...][/dim]")


def step_result(step_id: int, total: int, description: str, result: VisionActionResult, confidence_threshold: float) -> None:
    if result.escalate:
        console.print(f"⚠ Step {step_id}/{total}: {description}  [bold red]FAILED — self-healing...[/bold red]")
        return
    tag = "[green]✓ executed[/green]" if result.confidence >= confidence_threshold else "[yellow]⚠ low confidence[/yellow]"
    console.print(f"▶ Step {step_id}/{total}: {description}  [confidence: {result.confidence:.2f} {tag}]")


def step_healed(step_id: int, total: int, skill_id: str) -> None:
    console.print(f"[green]✓[/green] Step {step_id}/{total}: healed via skill [bold]{skill_id}[/bold]")


def low_confidence_prompt(step_id: int, confidence: float, auto_approve: bool = False) -> bool:
    """
    APPFLOW §2.4: "Vision agent 62% confident — approve this click? [y/N/skip]"
    auto_approve=True is the CI/unattended-mode path.
    """
    if auto_approve:
        return True
    pct = round(confidence * 100)
    answer = console.input(
        f"[yellow]Vision agent {pct}% confident on step {step_id} — approve this action? \\[y/N/skip]: [/yellow]"
    ).strip().lower()
    return answer == "y"


# --------------------------------------------------------------------------
# APPFLOW §2.5 — healed-step accept/reject checkpoint
# --------------------------------------------------------------------------

def render_heal_diff(step_id: int, root_cause: str, before_screenshot: str, after_screenshot: str) -> None:
    panel = Panel(
        f"[bold]Root cause:[/bold] {root_cause}\n"
        f"[dim]before:[/dim] {before_screenshot}\n"
        f"[dim]after:[/dim]  {after_screenshot}",
        title=f"Self-healed step {step_id}",
        border_style="yellow",
    )
    console.print(panel)


def confirm_heal_accept(auto_approve: bool = False) -> bool:
    if auto_approve:
        return True
    answer = console.input("[bold]Accept this healing (skill persists)? \\[Y/n]: [/bold]").strip().lower()
    return answer != "n"


# --------------------------------------------------------------------------
# APPFLOW §2.7 — Needs Review escalation queue
# --------------------------------------------------------------------------

def render_escalation_queue(rows: list[dict]) -> None:
    if not rows:
        console.print("[green]No pending escalations.[/green]")
        return
    table = Table(title="Needs Review", show_header=True, header_style="bold red")
    table.add_column("ID")
    table.add_column("Run")
    table.add_column("Step")
    table.add_column("Reason")
    for row in rows:
        table.add_row(str(row["id"]), row["run_id"], str(row["step_id"]), row["reason"])
    console.print(table)


# --------------------------------------------------------------------------
# Run summary card (echoes the HTML report's top card in-terminal)
# --------------------------------------------------------------------------

def render_run_summary(report) -> None:
    status_value = report.status.value if hasattr(report.status, "value") else str(report.status)
    status_color = {
        "passed": "green",
        "passed_with_healing": "yellow",
        "failed": "red",
        "escalated": "red",
    }.get(status_value, "white")

    console.print(
        Panel(
            f"[bold]{report.total_steps}[/bold] total · "
            f"[green]{report.self_healed_steps}[/green] self-healed · "
            f"[red]{report.escalated_steps}[/red] escalated · "
            f"{report.duration_seconds}s",
            title=f"Run {report.run_id} — [{status_color}]{status_value}[/{status_color}]",
        )
    )
