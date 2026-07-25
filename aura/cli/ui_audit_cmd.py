"""
aura ui-audit — aura/cli/ui_audit_cmd.py

Phase B3 (docs/decisions.md D-075): `ui_audit` was listed as an
`IntentKind` since B1 but had no standalone command behind it -- only
reachable as the `--ui-audit` flag bolted onto a full `aura execute`
run. This is the minimal standalone version: navigate, run the same
nav/hero/footer click-and-diff + real HTTP link check
(`orchestrator/ui_audit_runner.run_ui_audit`) `execute --ui-audit`
already runs, print the same summary, no spec/requirement text
involved at all.
"""
from __future__ import annotations

from aura.tui import live_view
from orchestrator.brain import AuraBrain, Intent

console = live_view.console


def ui_audit(url: str, max_elements: int = 12, link_scope: str = "all") -> None:
    console.print(f"[bold]Running UI audit on {url}[/bold]")

    intent = Intent(kind="ui_audit", params={"url": url, "max_elements": max_elements, "link_scope": link_scope})
    result = AuraBrain().handle(intent)

    run_id = result.run_id
    open_error = result.data["open_error"]
    report = result.data["report"]

    console.print(f"[dim](run_id={run_id})[/dim]")
    if open_error:
        console.print(f"[yellow]Could not open the browser automatically ({open_error}); assuming the page is already open.[/yellow]")

    landmarks_found = []
    landmarks_missing = []
    for label, present in (("nav", report.has_nav), ("hero section", report.has_hero), ("footer", report.has_footer)):
        (landmarks_found if present else landmarks_missing).append(label)
    if landmarks_found:
        console.print(f"[green]Detected:[/green] {', '.join(landmarks_found)}")
    if landmarks_missing:
        console.print(f"[yellow]Not detected (may be a real gap, or outside AURA's OCR-based heuristics):[/yellow] {', '.join(landmarks_missing)}")

    if report.possibly_broken:
        labels = ", ".join(c.label for c in report.possibly_broken)
        console.print(f"[yellow]Possibly non-functional (no visible change after click): {labels}[/yellow]")
    if report.unreachable:
        labels = ", ".join(c.label for c in report.unreachable)
        console.print(f"[dim]Could not locate to test-click: {labels}[/dim]")
    if report.page_issues:
        console.print(f"[yellow]Page scan flagged: {', '.join(report.page_issues)}[/yellow]")
    if not report.possibly_broken and not report.page_issues:
        console.print("[green]UI audit clean — no non-functional elements or error indicators found.[/green]")

    lc = report.link_check_result
    if lc is None:
        pass
    elif "error" in lc:
        console.print(f"[dim]Link check: could not run ({lc['error']})[/dim]")
    elif "broken_count" not in lc:
        console.print(f"[dim]Link check: {lc.get('message', 'no navigable links found')}[/dim]")
    elif lc["broken_count"] > 0:
        broken_urls = ", ".join(b["url"] for b in lc["broken_links"][:5])
        more = f" (+{lc['broken_count'] - 5} more)" if lc["broken_count"] > 5 else ""
        console.print(f"[red]Link check: {lc['broken_count']} of {lc['checked']} link(s) broken:[/red] {broken_urls}{more}")
    else:
        console.print(f"[green]Link check: all {lc['checked']} link(s) resolved successfully.[/green]")
