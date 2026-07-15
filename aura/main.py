"""
AURA CLI entry point.

Surface matches APPFLOW.md §3 (CLI commands table):
    aura init       -> setup wizard
    aura execute    -> run a test spec (approval checkpoint + live monitor)
    aura schedule   -> manage unattended recurring runs
    aura skills     -> skill library management

Phase 6: every command below now calls real logic (previously stubs):
  - `init`      -> aura/cli/init_cmd.py
  - `execute`   -> orchestrator/run_engine.py via aura/cli/execute_cmd.py
  - `schedule`  -> orchestrator/scheduler.py via aura/cli/schedule_cmd.py
  - `skills`    -> orchestrator/skill_store.py via aura/cli/skills_cmd.py
"""
from __future__ import annotations

import typer
from rich.console import Console

from aura.cli import debug_cmd, execute_cmd, explore_cmd, init_cmd, preflight, schedule_cmd, skills_cmd, trigger_cmd
from config.settings import settings
from orchestrator.schemas import RunReport, RunStatus
from reports.junit import render_junit_suites

console = Console()
app = typer.Typer(
    name="aura",
    help="AURA - Autonomous Unified RPA Agent (offline, vision-first, self-healing QA testing)",
    no_args_is_help=True,
)
app.add_typer(trigger_cmd.trigger_app, name="trigger")

# Phase G2 (decisions.md D-026): the only two statuses that count as a real
# pass for exit-code purposes. IN_PROGRESS should never be the terminal
# status of a returned RunReport (RunEngine always resolves to one of the
# other four before returning) -- treated as a failure here defensively
# rather than assumed unreachable, since "assumed unreachable" is exactly
# the kind of assumption docs/debug.md exists to make people double-check.
_PASSING_STATUSES = {RunStatus.PASSED, RunStatus.PASSED_WITH_HEALING}


def _exit_nonzero_if_failed(reports: list[RunReport]) -> None:
    failed = [r for r in reports if r.status not in _PASSING_STATUSES]
    if failed:
        raise typer.Exit(code=1)


@app.callback()
def _main(
    env: str = typer.Option(
        None,
        "--env",
        envvar="AURA_ENV",
        help=(
            "Environment profile to layer over the base .env (e.g. 'staging', 'prod'). "
            "Looks for a .env.<name> file next to .env; a missing profile file is not "
            "an error, it just means no overrides apply. Can also be set via the "
            "AURA_ENV environment variable instead of this flag."
        ),
    ),
) -> None:
    """
    Runs before every subcommand (Typer app-level callback). Phase G1,
    decisions.md D-025: applies the requested environment profile to the
    already-constructed `settings` singleton *before* any subcommand logic
    reads it, via Settings.reload_profile() (in-place mutation, so every
    module that already did `from config.settings import settings` sees
    the update too -- see config/settings.py's own docstring on why this
    isn't a simple reassignment).
    """
    if env:
        settings.reload_profile(env)


@app.command()
def init(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip interactive prompts, write defaults."),
    env: str = typer.Option(None, "--env", help="Scaffold a .env.<name> profile file alongside the base .env (Phase G1)."),
) -> None:
    """Run the first-time setup wizard (target app type, scheduling, compression policy)."""
    init_cmd.run_init_wizard(non_interactive=yes, env_profile=env)


@app.command()
def execute(
    test_id: str = typer.Argument(None, help="Test spec ID or requirement file to execute, e.g. TC-LOGIN-FLOW-001"),
    all: bool = typer.Option(False, "--all", help="Execute every requirement doc in requirements_input/"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Auto-approve spec, low-confidence actions, and healed steps (unattended mode). Alias: --autonomous."),
    autonomous: bool = typer.Option(False, "--autonomous", help="Same as --yes -- explicit name for Mode A (no human input at all). See README 'Autonomy modes'."),
    refresh_data: bool = typer.Option(False, "--refresh-data", help="Force-regenerate synthetic data instead of reusing the cache."),
    pdf: bool = typer.Option(False, "--pdf", help="Also export the report as PDF (requires the 'report' extra)."),
    url: str = typer.Option(None, "--url", help="Live website URL to test."),
    prompt: str = typer.Option(None, "--prompt", help='Plain-English instruction for what to test, e.g. --prompt "Check the pricing page and verify the Sign Up button works". Runs fully unattended unless combined with --interactive.'),
    scroll_test: bool = typer.Option(False, "--scroll-test", help="After the main steps, scroll the full page top-to-bottom checking for broken/error content, unattended."),
    ui_audit: bool = typer.Option(False, "--ui-audit", help="Comprehensive UI audit: checks nav, hero section, and footer are present, and test-clicks nav/footer links to flag anything that produces no visible change."),
    interactive: bool = typer.Option(False, "--interactive", help='Mode B (human-in-the-loop): AURA does not act. It opens --url (if given) and waits, polling the screen, until you perform the action described by --prompt yourself -- no timeout by default. See README "Autonomy modes".'),
    timeout: int = typer.Option(0, "--timeout", help="Only used with --interactive: give up after this many seconds if nothing changes. 0 (default) means wait indefinitely."),
    junit_out: str = typer.Option(None, "--junit-out", help="Write results as JUnit XML to this path (for CI test-report consumption). With --all, every spec's outcome becomes one <testsuite> in a single combined file."),
) -> None:
    """Execute a test: approval checkpoint -> live vision-execution loop -> report.

    Exit codes (Phase G2, decisions.md D-026): 0 = every spec run this
    invocation PASSED or PASSED_WITH_HEALING; 1 = at least one spec
    FAILED or was ESCALATED, or the invocation couldn't start a run at
    all (no test_id/--all/--url/--prompt given, or --all found no
    requirement docs). There is no separate "run itself errored" code --
    an unhandled exception during a run already propagates as a non-zero
    exit via Python's own default traceback-and-exit-1 behavior, which
    external tooling (CI) already treats the same as "this step failed."
    """
    preflight.run_preflight_or_exit()
    auto_approve = yes or autonomous

    if interactive:
        if not prompt:
            console.print('[red]--interactive requires --prompt "<what to wait for>".[/red]')
            raise typer.Exit(code=1)
        execute_cmd.execute_interactive(prompt, url=url, timeout=timeout)
        return

    if prompt:
        # --prompt is inherently unattended: the person described intent in
        # plain English rather than approving a spec line by line, so there
        # is no meaningful approval checkpoint to show them.
        report = execute_cmd.execute_prompt(prompt, url=url, export_pdf=pdf, scroll_test=scroll_test, ui_audit=ui_audit, junit_out=junit_out)
        _exit_nonzero_if_failed([report])
        return

    if all:
        targets = sorted(settings.requirements_input_dir.glob("*.md"))
        if not targets:
            console.print("[yellow]No requirement docs found in requirements_input/.[/yellow]")
            raise typer.Exit(code=1)
        junit_suites: list = [] if junit_out else None
        reports = []
        for path in targets:
            console.print(f"\n=== {path.name} ===")
            reports.append(execute_cmd.execute_test(
                str(path), auto_approve=auto_approve, refresh_data=refresh_data, export_pdf=pdf,
                url=url, scroll_test=scroll_test, ui_audit=ui_audit, junit_suite_collector=junit_suites,
            ))
        if junit_out and junit_suites:
            combined_path = render_junit_suites(junit_suites, out_path=junit_out)
            console.print(f"\nCombined JUnit XML: {combined_path}")
        _exit_nonzero_if_failed(reports)
        return

    if not test_id:
        if url:
            report = execute_cmd.execute_url(url, auto_approve=auto_approve, refresh_data=refresh_data, export_pdf=pdf, scroll_test=scroll_test, ui_audit=ui_audit, junit_out=junit_out)
            _exit_nonzero_if_failed([report])
            return
        console.print("[red]Provide a test_id/requirement file, or pass --all, --url, or --prompt.[/red]")
        raise typer.Exit(code=1)

    report = execute_cmd.execute_test(test_id, auto_approve=auto_approve, refresh_data=refresh_data, export_pdf=pdf, url=url, scroll_test=scroll_test, ui_audit=ui_audit, junit_out=junit_out)
    _exit_nonzero_if_failed([report])


@app.command()
def explore(
    url: str = typer.Argument(..., help="URL to explore with zero instructions -- Mode A's purest form: no spec, no --prompt required."),
    max_elements: int = typer.Option(25, "--max-elements", help="Cap on how many detected clickable elements to test-click."),
    prompt: str = typer.Option(None, "--prompt", help='Optional plain-English thing to keep an eye out for while exploring, e.g. --prompt "check the submit button works". Best-effort keyword match, not a guarantee -- see README.'),
    no_scroll_scan: bool = typer.Option(False, "--no-scroll-scan", help="Skip the full-page scroll/error scan before clicking elements."),
    check_links: bool = typer.Option(False, "--check-links", help="Also run a real HTTP-level link check (actual status codes, not just click-and-diff). Off by default -- opt in explicitly."),
    link_scope: str = typer.Option("all", "--link-scope", help='Only used with --check-links. Which links get checked: "all" (default -- every navigable link on the page), "footer", or "nav".'),
) -> None:
    """
    Fully autonomous exploration: give it a URL, nothing else. AURA
    navigates, scrolls the whole page, finds every clickable-looking
    element via OCR, clicks each one, checks nothing broke, and reports
    back -- no spec file, no --prompt required, zero human input.
    """
    preflight.run_preflight_or_exit()
    explore_cmd.explore(url, max_elements=max_elements, prompt=prompt, scroll_scan=not no_scroll_scan, check_links=check_links, link_scope=link_scope)


@app.command()
def debug(
    path: str = typer.Argument(..., help="File or directory to scan for bugs."),
    out: str = typer.Option(None, "--out", help="Also write the full findings list to a Markdown file."),
    no_ruff: bool = typer.Option(False, "--no-ruff", help="Skip the supplementary ruff lint pass (useful if ruff isn't installed)."),
) -> None:
    """Scan Python file(s) for common bug patterns and report them — detection only, never modifies code."""
    debug_cmd.run_debug(path, out=out, no_ruff=no_ruff)


@app.command()
def schedule(
    action: str = typer.Argument(..., help="add | remove | list"),
    cron: str = typer.Argument(None, help='Cron expression, e.g. "0 2 * * *" (required for add)'),
    test_id: str = typer.Argument(None, help="Required for add/remove"),
) -> None:
    """Manage unattended scheduled runs."""
    if action == "add":
        if not cron or not test_id:
            console.print("[red]Usage: aura schedule add \"<cron>\" <test_id>[/red]")
            raise typer.Exit(code=1)
        schedule_cmd.add(cron, test_id)
    elif action == "remove":
        job_id = cron  # positionally, `aura schedule remove <job_id>`
        if not job_id:
            console.print("[red]Usage: aura schedule remove <job_id>[/red]")
            raise typer.Exit(code=1)
        schedule_cmd.remove(job_id)
    elif action == "list":
        schedule_cmd.list_jobs()
    else:
        console.print(f"[red]Unknown action '{action}'. Use add | remove | list.[/red]")
        raise typer.Exit(code=1)


@app.command()
def skills(
    action: str = typer.Argument(..., help="list | export | import | diff"),
    app_name: str = typer.Option(None, "--app", help="App identifier filter/tag"),
    out: str = typer.Option(None, "--out", help="Output file for export, or input file for import"),
    before: str = typer.Option(None, "--before", help="Earlier skill-pack export (required for diff)"),
    after: str = typer.Option(None, "--after", help="Later skill-pack export (required for diff)"),
) -> None:
    """Inspect, export, import, or diff the local self-healing skill library."""
    if action == "list":
        skills_cmd.list_skills(app_id=app_name)
    elif action == "export":
        skills_cmd.export_skills(app_id=app_name, out_path=out)
    elif action == "import":
        if not out:
            console.print("[red]Usage: aura skills import --out <path>[/red]")
            raise typer.Exit(code=1)
        skills_cmd.import_skills(out, app_id=app_name)
    elif action == "diff":
        if not before or not after:
            console.print("[red]Usage: aura skills diff --before <old_export.json> --after <new_export.json>[/red]")
            raise typer.Exit(code=1)
        skills_cmd.diff_skills(before, after)
    else:
        console.print(f"[red]Unknown action '{action}'. Use list | export | import | diff.[/red]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
