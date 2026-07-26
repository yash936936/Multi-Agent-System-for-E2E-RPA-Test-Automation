"""
aura execute — aura/cli/execute_cmd.py

Wires together everything built in Phases 1-6 into the flow APPFLOW.md
describes end to end:

    §2.2  requirement ingestion (Planner.generate_spec, shown as progress)
    §2.3  spec approval checklist (human checkpoint -- nothing runs without it)
    §2.4  live step-by-step monitoring, including the low-confidence inline
          approval prompt
    §2.5  self-healed step accept/reject checkpoint
    §2.6  HTML/PDF report generation + terminal summary
    §2.7  escalated steps land in the Needs Review queue (orchestrator/memory.py)

Two modes:
    interactive (default) -- prompts for spec approval, low-confidence
        actions, and heal accept/reject, matching APPFLOW exactly.
    --yes / --unattended -- auto-approves everything, for CI or
        `aura schedule`-triggered nightly runs (TRD §5.5).
"""
from __future__ import annotations

import uuid
from pathlib import Path

import typer
from rich.console import Console

from aura.tui import live_view
from config.settings import settings
from orchestrator.brain import AuraBrain, Intent
from orchestrator.schemas import RunReport, TestStep, VisionActionResult
from orchestrator.spec_validator import SpecValidationError
from reports.junit import render_junit
from reports.render import render_html, render_json, render_pdf
from runtime.hooks.browser import normalize_url

console = Console()


def _find_requirement_file(test_id: str) -> Path:
    """
    Resolves a test_id (e.g. TC-LOGIN-FLOW-001) or a bare filename to a
    file under requirements_input/. Falls back to treating test_id as a
    direct path if it exists, so `aura execute path/to/req.md` also works.
    """
    direct = Path(test_id)
    if direct.exists():
        return direct

    for candidate in settings.requirements_input_dir.glob("*.md"):
        if test_id.lower() in candidate.stem.lower() or test_id.lower() in candidate.read_text(encoding="utf-8").lower():
            return candidate

    raise FileNotFoundError(
        f"Could not find a requirement doc for '{test_id}' under {settings.requirements_input_dir}. "
        "Pass a direct file path, or drop the doc into requirements_input/."
    )


def _print_validation_warnings(warnings: list) -> None:
    """
    Phase T: surfaces non-blocking action/target-type mismatch warnings
    from orchestrator/spec_validator.py. These never block a run (unlike
    the error-severity issues caught as SpecValidationError above) -- just
    a heads-up that a step's description sounded like it was describing a
    backend target rather than a real UI element.
    """
    for w in warnings:
        console.print(f"[yellow]Warning (step {w.step_id}):[/yellow] {w.message}")


def _make_screenshot_provider(live: bool):
    """
    live=True  -> real capture via runtime/hooks/capture.py (needs a display)
    live=False -> not supported here; execute requires a display or a test
                  harness. This CLI path is for real runs against a real
                  target app (APPFLOW's whole premise), unlike
                  tests/test_run_engine.py which injects a synthetic provider directly.
    """
    if not live:
        raise RuntimeError("Non-live screenshot providers are only used in tests, not the CLI.")

    from runtime.hooks.capture import capture_screenshot

    def provider(run_id: str, step_id: int) -> str:
        return str(capture_screenshot(run_id, step_id))

    return provider


def _build_url_smoke_requirement(url: str) -> str:
    # Auto-generated minimal requirement text for `aura execute --url <url>`
    # with no spec file given: just navigate and hand control back to the
    # normal spec-approval / vision-execution / report pipeline.
    #
    # normalize_url() matters here: _NAVIGATE_PATTERNS in spec_generator.py
    # only match https?://..., so a bare domain like "example.com" (no
    # scheme) would silently fail to produce a navigate step at all,
    # leaving TestSpec.steps empty and crashing on the "at least one step"
    # validator instead of running anything.
    url = normalize_url(url)
    return (
        f"# Live URL Smoke Test\n\n"
        f"Given: navigate to {url}\n\n"
        f"The user waits for the page to finish loading.\n"
    )


def execute_prompt(
    prompt: str,
    url: str | None = None,
    export_pdf: bool = False,
    scroll_test: bool = False,
    ui_audit: bool = False,
    junit_out: str | None = None,
    continuous_audit: bool | None = None,
) -> "RunReport":
    """
    `aura execute --prompt "<plain English>"` -- fully unattended: the
    person described intent, not a step-by-step spec, so there's no
    approval checkpoint to show them. If --url is also given it's
    prepended as a navigate precondition; otherwise the prompt itself is
    expected to name the target (e.g. "go to example.com and ...").
    """
    requirement_text = prompt
    if url:
        requirement_text = f"Given: navigate to {normalize_url(url)}\n\n" + requirement_text
    return _run_requirement_text(
        requirement_text,
        display_source="(prompt)",
        auto_approve=True,
        refresh_data=False,
        export_pdf=export_pdf,
        scroll_test=scroll_test,
        ui_audit=ui_audit,
        junit_out=junit_out,
        continuous_audit=continuous_audit,
    )


def execute_url(
    url: str,
    auto_approve: bool = False,
    refresh_data: bool = False,
    export_pdf: bool = False,
    scroll_test: bool = False,
    ui_audit: bool = False,
    junit_out: str | None = None,
    continuous_audit: bool | None = None,
) -> "RunReport":
    """
    `aura execute --url <url>` with no test_id/spec file: the "just give
    me a target URL and run a QA test" fast path. Synthesizes a minimal
    requirement doc (navigate + settle) and runs it through the exact same
    approval/execution/report pipeline as a written spec -- nothing about
    downstream behavior (healing, skills, reporting) is special-cased.
    """
    requirement_text = _build_url_smoke_requirement(url)
    return _run_requirement_text(
        requirement_text,
        display_source=f"(auto-generated smoke test for {url})",
        auto_approve=auto_approve,
        refresh_data=refresh_data,
        export_pdf=export_pdf,
        scroll_test=scroll_test,
        ui_audit=ui_audit,
        junit_out=junit_out,
        continuous_audit=continuous_audit,
    )


def execute_interactive(
    prompt: str,
    url: str | None = None,
    timeout: int = 0,
) -> None:
    """
    `aura execute --interactive --prompt "<instruction>"` -- Mode 2,
    human-in-the-loop. Unlike every other execute_* path in this file,
    AURA does not act here: it opens the target (if --url given), then
    polls the live screen in a loop (RunEngine.run_spec's
    WAIT_FOR_HUMAN_ACTION branch) until it detects that *you* performed
    the described action, then verifies and reports. This does not stop
    early just because nothing happened for a while -- `timeout=0` (the
    default) means it waits indefinitely, matching the actual feature
    request ("the execution should not stop until the human clicks").

    Phase B3 (docs/decisions.md D-075): the spec-building + `RunEngine`
    call now lives in
    `orchestrator/brain/router.py::Router._handle_execute_interactive()`;
    `on_waiting` stays a closure built here, forwarded through
    `Intent.params` unchanged -- the Router never calls `live_view` itself.
    """
    console = live_view.console

    console.print(f"[bold]Waiting for you: {prompt}[/bold]")
    if url:
        console.print(f"Target: {url}")
    console.print(
        "AURA will not act on its own -- perform the action yourself; it's watching the screen and will "
        "verify as soon as it detects a change." + ("" if timeout == 0 else f" Giving up after {timeout}s if nothing changes.")
    )
    console.print("[dim]Press Ctrl+C to cancel.[/dim]\n")

    def on_waiting(step_id: int, step, elapsed: float) -> None:
        console.print(f"[dim]  still waiting... ({elapsed:.0f}s)[/dim]")

    intent = Intent(
        kind="execute_interactive",
        params={
            "prompt": prompt,
            "url": url,
            "timeout": timeout,
            "screenshot_provider": _make_screenshot_provider(live=True),
            "on_waiting": on_waiting,
        },
    )

    try:
        brain_result = AuraBrain().handle(intent)
    except SpecValidationError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    result = brain_result.data["result"]
    run_id = brain_result.run_id
    final = result.report
    _print_validation_warnings(result.validation_warnings)

    if final.escalated_steps == 0:
        console.print("\n[green]Detected the change and it checks out — verified.[/green]")
    else:
        reason = "nothing changed before the timeout" if timeout else "the assertion didn't pass after the change"
        console.print(f"\n[yellow]Not verified — {reason}.[/yellow]")

    console.print(f"Screenshots saved under runtime/screenshots/run_{run_id}/ for manual review.")


def execute_test(
    test_id: str,
    auto_approve: bool = False,
    refresh_data: bool = False,
    export_pdf: bool = False,
    url: str | None = None,
    scroll_test: bool = False,
    ui_audit: bool = False,
    junit_out: str | None = None,
    junit_suite_collector: list | None = None,
    continuous_audit: bool | None = None,
) -> RunReport:
    # --- §2.2: ingest requirement, generate spec for preview ---
    req_path = _find_requirement_file(test_id)
    requirement_text = req_path.read_text(encoding="utf-8")
    if url:
        # Prepend a navigate precondition so the backend emits a
        # NAVIGATE_URL step as step 1, ahead of whatever the spec file
        # already describes -- closes the gap where a browser had to
        # already be open at the right page before this command started.
        # Same scheme-normalization as _build_url_smoke_requirement: a
        # bare domain here would silently fail to match _NAVIGATE_PATTERNS.
        requirement_text = f"Given: navigate to {normalize_url(url)}\n\n" + requirement_text
    return _run_requirement_text(
        requirement_text,
        display_source=str(req_path),
        auto_approve=auto_approve,
        refresh_data=refresh_data,
        export_pdf=export_pdf,
        scroll_test=scroll_test,
        ui_audit=ui_audit,
        junit_out=junit_out,
        junit_suite_collector=junit_suite_collector,
        continuous_audit=continuous_audit,
    )


def _run_requirement_text(
    requirement_text: str,
    display_source: str,
    auto_approve: bool = False,
    refresh_data: bool = False,
    export_pdf: bool = False,
    scroll_test: bool = False,
    ui_audit: bool = False,
    junit_out: str | None = None,
    junit_suite_collector: list | None = None,
    continuous_audit: bool | None = None,
) -> RunReport:
    """
    Phase B3 (docs/decisions.md D-075): the actual orchestration (page
    grounding, spec generation, RunEngine construction/run, the healed-
    skill loop, optional autoscan/ui-audit passes) now lives in
    `orchestrator/brain/router.py::Router._handle_execute_requirement()`.
    Every place this function used to call `live_view` directly during
    the run is now a closure built here and passed through
    `Intent.params` -- `Router` forwards them to `RunEngine` unchanged
    and never calls `live_view` itself (see that module's docstring,
    decision 1). This function still owns: building those closures,
    the approval-checkpoint UI itself (`approve_spec`), report writing
    (`render_json`/`render_html`/PDF/JUnit), and the final terminal
    summary -- exactly the same "Brain returns data, CLI renders it"
    split B1 established for `explore`.
    """
    console = live_view.console

    total_steps_holder: dict[str, int] = {}

    def on_step_start(step_id: int, step: TestStep) -> None:
        desc = step.target_description or step.field_description or step.action.value
        live_view.step_start(step_id, total_steps_holder.get("n", 0), desc)

    def on_step_result(step_id: int, step: TestStep, result: VisionActionResult) -> None:
        desc = step.target_description or step.field_description or step.action.value
        if not result.escalate and result.confidence < settings.vision_confidence_threshold:
            if not live_view.low_confidence_prompt(step_id, result.confidence, auto_approve=auto_approve):
                console.print(f"[dim]Step {step_id} skipped by reviewer.[/dim]")
        live_view.step_result(step_id, total_steps_holder.get("n", 0), desc, result, settings.vision_confidence_threshold)

    def on_skill_learned(step_id: int, skill) -> None:
        live_view.step_healed(step_id, total_steps_holder.get("n", 0), skill.skill_id)

    def approve_spec(spec) -> bool:
        total_steps_holder["n"] = len(spec.steps)
        live_view.render_spec_checklist(spec)
        if not live_view.confirm_spec_approval(auto_approve=auto_approve):
            console.print("[yellow]Run cancelled — spec not approved.[/yellow]")
            raise typer.Exit(code=1)
        return True

    def confirm_heal_accept(step_id: int, skill) -> bool:
        live_view.render_heal_diff(
            step_id=step_id,
            root_cause=skill.root_cause,
            before_screenshot="(see run screenshots dir)",
            after_screenshot="(see run screenshots dir)",
        )
        accepted = live_view.confirm_heal_accept(auto_approve=auto_approve)
        if not accepted:
            console.print(f"[dim]Rejected — skill {skill.skill_id} discarded.[/dim]")
        return accepted

    def on_scan_progress(what: str) -> None:
        if what == "scanning_full_page":
            console.print("Scanning full page for broken/error content...")
        elif what == "running_ui_audit":
            console.print("Running comprehensive UI audit (nav, hero, footer)...")

    intent = Intent(
        kind="execute_spec",
        params={
            "requirement_text": requirement_text,
            "auto_approve": auto_approve,
            "refresh_data": refresh_data,
            "scroll_test": scroll_test,
            "ui_audit": ui_audit,
            "continuous_audit": continuous_audit,
            "screenshot_provider": _make_screenshot_provider(live=True),
            "on_step_start": on_step_start,
            "on_step_result": on_step_result,
            "on_skill_learned": on_skill_learned,
            "approve_spec": approve_spec,
            "confirm_heal_accept": confirm_heal_accept,
            "on_scan_progress": on_scan_progress,
        },
    )

    try:
        with live_view.spinner(f"Running: {display_source}..."):
            brain_result = AuraBrain().handle(intent)
    except SpecValidationError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)

    if brain_result.data.get("cancelled"):
        # approve_spec() above already raises typer.Exit before this can
        # be reached in the interactive-rejection case; this branch only
        # covers a future non-raising approve_spec implementation.
        raise typer.Exit(code=1)

    spec = brain_result.data["spec"]
    result = brain_result.data["result"]
    autoscan_report = brain_result.data["autoscan_report"]
    ui_audit_report = brain_result.data["ui_audit_report"]
    memory = brain_result.data["memory"]

    _print_validation_warnings(result.validation_warnings)

    if autoscan_report is not None:
        if autoscan_report.display_unavailable:
            console.print("[yellow]No display available -- page scan skipped (headless/no-display environment).[/yellow]")
        elif autoscan_report.all_issues:
            console.print(f"[yellow]Page scan flagged: {', '.join(autoscan_report.all_issues)}[/yellow]")
        else:
            coverage = "reached the bottom" if autoscan_report.reached_bottom else "hit the scan limit"
            console.print(f"Page scan clean — no error indicators found ({coverage}).")

    if ui_audit_report is not None:
        landmarks_found = []
        landmarks_missing = []
        for label, present in (("nav", ui_audit_report.has_nav), ("hero section", ui_audit_report.has_hero), ("footer", ui_audit_report.has_footer)):
            (landmarks_found if present else landmarks_missing).append(label)
        if landmarks_found:
            console.print(f"[green]Detected:[/green] {', '.join(landmarks_found)}")
        if landmarks_missing:
            console.print(f"[yellow]Not detected (may be a real gap, or outside AURA's OCR-based heuristics):[/yellow] {', '.join(landmarks_missing)}")

        if ui_audit_report.possibly_broken:
            labels = ", ".join(c.label for c in ui_audit_report.possibly_broken)
            console.print(f"[yellow]Possibly non-functional (no visible change after click): {labels}[/yellow]")
        if ui_audit_report.unreachable:
            labels = ", ".join(c.label for c in ui_audit_report.unreachable)
            console.print(f"[dim]Could not locate to test-click: {labels}[/dim]")
        if ui_audit_report.page_issues:
            console.print(f"[yellow]Page scan flagged: {', '.join(ui_audit_report.page_issues)}[/yellow]")
        if not ui_audit_report.possibly_broken and not ui_audit_report.page_issues:
            console.print("[green]UI audit clean — no non-functional elements or error indicators found.[/green]")

        lc = ui_audit_report.link_check_result
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

    # --- §2.6: report + terminal summary ---
    json_path = render_json(result.run_id, spec=spec.model_dump())
    html_path = render_html(result.run_id, spec=spec.model_dump(), autoscan_report=autoscan_report, ui_audit_report=ui_audit_report)
    console.print(f"\nReport: {html_path}")
    console.print(f"Detailed JSON: {json_path}")
    if export_pdf:
        try:
            pdf_path = render_pdf(html_path)
            console.print(f"PDF: {pdf_path}")
        except RuntimeError as e:
            console.print(f"[yellow]{e}[/yellow]")

    if junit_suite_collector is not None:
        from reports.junit import build_testsuite_element

        junit_suite_collector.append(build_testsuite_element(result.report, suite_name=display_source))
    elif junit_out:
        junit_path = render_junit(result.report, out_path=junit_out)
        console.print(f"JUnit XML: {junit_path}")

    live_view.render_run_summary(result.report)

    # --- §2.7: surface any new escalations ---
    pending = [e for e in memory.pending_escalations() if e["run_id"] == result.run_id]
    if pending:
        console.print()
        live_view.render_escalation_queue(pending)

    return result.report
