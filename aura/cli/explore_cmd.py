"""
aura explore — aura/cli/explore_cmd.py

Mode 1 of AURA's autonomy modes (see README.md "Autonomy modes"): give it
just a URL and it behaves like a QA tester with no written instructions --
navigates there, scrolls the whole page (reusing orchestrator/autoscan.py's
error-string scan), finds every clickable-looking element via OCR
(agents/vision/ui_audit.py), clicks each one, checks whether anything
visibly broke, comes back, and tries the next one
(orchestrator/ui_audit_runner.py's run_exploration()). Zero human input,
ever, unlike `aura execute` which always needs either a spec file or a
`--prompt` describing what to do.

An optional --prompt lets you point it at something specific to keep an
eye out for while it explores ("check that the submit button works") --
see orchestrator/ui_audit_runner.py's requirement-prompt matching for
exactly what this can and can't tell you (it's a keyword heuristic, not
language understanding, and is disclosed as such in the output).

This does not (yet) produce an HTML report -- render_html() expects a
full spec-driven RunReport on disk (see reports/render.py), and explore
mode deliberately has no spec. Output is a rich terminal summary plus a
JSON dump under reports/explore_<run_id>.json. Folding this into the HTML
report pipeline is a natural next step, not done here to avoid quietly
reshaping report.html's schema as a side effect of an unrelated feature.
"""
from __future__ import annotations

import json
import time
import uuid

from aura.tui import live_view
from config.settings import settings
from runtime.hooks.browser import normalize_url

console = live_view.console


def explore(
    url: str,
    max_elements: int = 25,
    prompt: str | None = None,
    scroll_scan: bool = True,
    check_links: bool = False,
    link_scope: str = "all",
) -> None:
    """
    Autonomous exploration: navigate to `url`, then click every
    interactive-looking element found (nav, hero, footer, and body bands)
    and report anything that looks broken. No spec, no approval
    checkpoints -- this mode is autonomous by definition.

    check_links / link_scope: the real HTTP-level link check
    (agents/capability/link_checker.py) only runs when check_links is
    True. It previously ran unconditionally on every explore call
    (link_check_scope defaulted to "all" and was always wired up), which
    meant a plain `aura explore <url>` did a live HTTP fetch and status
    check against every link on the page whether or not that was actually
    asked for. It's opt-in now; link_scope only has any effect when
    check_links is set.
    """
    from runtime.hooks import browser

    run_id = f"explore_{uuid.uuid4().hex[:8]}"
    normalized = normalize_url(url)

    console.print(f"[bold]Exploring {normalized}[/bold] (run_id={run_id})")
    console.print("No instructions given -- acting as a QA tester would: navigate, scan, click everything, report back.\n")

    try:
        browser.open_url(normalized)
    except Exception as e:  # noqa: BLE001 - surfaced to the user either way
        console.print(f"[yellow]Could not open the browser automatically ({e}); assuming the page is already open.[/yellow]")

    # Give the page a moment to load before the first screenshot.
    time.sleep(settings.human_action_poll_interval_seconds)

    from runtime.hooks.capture import capture_screenshot

    def provider(rid: str, index: int) -> str:
        return str(capture_screenshot(rid, index))

    if scroll_scan:
        from orchestrator.autoscan import run_autoscan

        console.print("Scanning full page for broken/error content...")
        autoscan_report = run_autoscan(provider, run_id=run_id)
        if autoscan_report.all_issues:
            console.print(f"[yellow]Page scan flagged: {', '.join(autoscan_report.all_issues)}[/yellow]")
        else:
            coverage = "reached the bottom" if autoscan_report.reached_bottom else "hit the scan limit"
            console.print(f"Page scan clean — no error indicators found ({coverage}).")
    else:
        autoscan_report = None

    console.print(f"\nClicking every detected interactive element (up to {max_elements})...")

    from orchestrator.ui_audit_runner import run_exploration

    report = run_exploration(
        provider,
        run_id=run_id,
        max_elements=max_elements,
        requirement_prompt=prompt,
        page_url=normalized if check_links else None,
        link_check_scope=link_scope,
    )

    landmarks_found = [label for label, present in (("nav", report.has_nav), ("hero section", report.has_hero), ("footer", report.has_footer)) if present]
    if landmarks_found:
        console.print(f"[green]Detected:[/green] {', '.join(landmarks_found)}")

    console.print(f"\n[bold]Checked {len(report.checked)} element(s):[/bold]")
    for c in report.checked:
        if not c.clicked:
            console.print(f"  [dim]· {c.label} ({c.band}) — could not locate/click[/dim]")
        elif c.state_changed:
            console.print(f"  [green]✓ {c.label} ({c.band}) — click produced a visible change[/green]")
        else:
            console.print(f"  [yellow]⚠ {c.label} ({c.band}) — no visible change after click[/yellow]")

    if report.page_issues:
        console.print(f"\n[yellow]Page scan flagged: {', '.join(report.page_issues)}[/yellow]")

    if report.link_check_result:
        lc = report.link_check_result
        scope_label = lc.get("scope", link_scope)
        console.print(f"\n[bold]Link check[/bold] (scope='{scope_label}', real HTTP status, not just click-and-diff):")
        if lc.get("error"):
            console.print(f"  [yellow]{lc['error']}[/yellow]")
        else:
            console.print(f"  {lc.get('message', '')}")
            if lc.get("client_rendered_suspected"):
                console.print("  [yellow]This page appears to be client-rendered -- see the message above for what that means for link coverage.[/yellow]")
            for broken in lc.get("broken_links", []):
                status = broken.get("status_code") or broken.get("error") or "unreachable"
                console.print(f"  [red]✗ {broken['url']} — {status}[/red]")
            for redirect in lc.get("redirected_links", []):
                chain = " -> ".join(hop["to_url"] or "?" for hop in redirect.get("redirect_chain", []))
                console.print(f"  [dim]↪ {redirect['url']} redirected ({redirect.get('status_code')}) via {chain or 'unknown chain'} -> {redirect.get('final_url')}[/dim]")
    elif not check_links:
        console.print("\n[dim]Link check skipped (pass --check-links to verify every link's real HTTP status, not just click-and-diff).[/dim]")

    if prompt:
        console.print(f"\n[bold]Requested check:[/bold] \"{prompt}\"")
        for note in report.requirement_notes:
            console.print(f"  [dim]{note}[/dim]")
        if report.requirement_match:
            console.print("[green]Looks covered — but this is a keyword heuristic, not certainty. Review the click log above.[/green]")
        else:
            console.print("[yellow]Doesn't look covered — see notes above.[/yellow]")

    link_check_clean = not report.link_check_result or not report.link_check_result.get("broken_links")
    if not report.possibly_broken and not report.page_issues and link_check_clean:
        console.print("\n[green]Exploration clean — no non-functional elements or error indicators found.[/green]")

    out_dir = settings.reports_dir / f"explore_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "report.json"
    out_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "url": normalized,
                "prompt": prompt,
                "has_nav": report.has_nav,
                "has_hero": report.has_hero,
                "has_footer": report.has_footer,
                "checked": [c.__dict__ for c in report.checked],
                "page_issues": report.page_issues,
                "requirement_match": report.requirement_match,
                "requirement_notes": report.requirement_notes,
                "link_check_requested": check_links,
                "link_check_scope": link_scope if check_links else None,
                "link_check_result": report.link_check_result,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    console.print(f"\nJSON report: {out_path}")
