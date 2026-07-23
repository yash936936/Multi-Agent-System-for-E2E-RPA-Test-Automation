"""
aura/cli/preflight.py

First-run / pre-execution environment checks -- catches the most common
"it doesn't work" case (Tesseract OCR not installed, or not where AURA
expects it) as early and clearly as possible, instead of letting it
surface as a raw traceback from deep inside agents/vision/locator.py
partway through a run.

This matters most for the PyInstaller-packaged .exe (deployment option 2,
decisions.md D-012), which is explicitly meant to reach non-technical QA
staff who won't recognize a pytesseract stack trace, let alone know what
to do about it. The check is cheap (a single subprocess call to
`tesseract --version`), so it's fine to run before every `execute`.
"""
from __future__ import annotations

from rich.console import Console

console = Console()

_TESSERACT_INSTALL_URL = "https://github.com/UB-Mannheim/tesseract/wiki"


def check_tesseract_available() -> tuple[bool, str | None]:
    """
    Returns (ok, friendly_message). friendly_message is None when ok=True.
    Never raises -- this is meant to be a clean pre-check, not another
    place a stack trace can leak out to a non-technical user.
    """
    from config.settings import settings

    try:
        import pytesseract
    except ImportError:
        return False, (
            "AURA's vision engine (pytesseract) isn't installed in this environment. "
            "If you're running from a packaged .exe, this shouldn't happen -- please "
            "report it. If you're running from source, run: pip install -e \".[dev]\""
        )

    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

    try:
        pytesseract.get_tesseract_version()
    except pytesseract.TesseractNotFoundError:
        configured = settings.tesseract_cmd
        if configured:
            return False, (
                f"AURA looked for Tesseract OCR at:\n    {configured}\n"
                "but couldn't run it there. Double-check that path is correct, or "
                "reinstall Tesseract from:\n    "
                f"{_TESSERACT_INSTALL_URL}"
            )
        return False, (
            "AURA needs Tesseract OCR to read text on screen, and couldn't find it.\n\n"
            "To fix this:\n"
            f"  1. Download and install Tesseract from:\n     {_TESSERACT_INSTALL_URL}\n"
            "  2. Note where it installed (usually C:\\Program Files\\Tesseract-OCR\\tesseract.exe)\n"
            "  3. Create a file named .env next to aura.exe (or in the project folder) containing:\n"
            "         AURA_TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe\n"
            "  4. Run your command again."
        )
    except Exception as e:  # noqa: BLE001 - any other tesseract failure should also be a clean message, not a raw traceback
        return False, f"AURA couldn't verify the Tesseract OCR install ({e}). See {_TESSERACT_INSTALL_URL} for setup help."

    return True, None


def check_planner_backend_available() -> tuple[bool, str | None]:
    """
    Catches the most common "it doesn't work" case for the planner
    backend: AURA_PLANNER_BACKEND set to 'local_llm' (often by copying the
    README's example .env block) without AURA_LOCAL_LLM_MODEL_PATH
    actually pointing at a real .gguf file on disk. Without this check,
    that surfaces as a raw LocalLLMModelNotFoundError traceback from deep
    inside agents/planner/spec_generator.py, partway through spec
    generation -- same failure mode this module already prevents for
    Tesseract. Never raises, same contract as check_tesseract_available.

    Recognizes every backend config/settings.py's own auto-detect matrix
    can resolve to: 'heuristic', 'local_llm', 'cloud_llm' (Phase V,
    D-044), and 'hermes_agent' (Phase W, D-047). This check previously
    only knew about 'heuristic'/'local_llm' and predates the other two --
    that meant a validly auto-detected 'cloud_llm' or 'hermes_agent'
    backend was rejected here as "unknown" even though config/settings.py
    considered it perfectly valid, blocking startup for any operator who
    configured either of those backends.
    """
    from pathlib import Path

    from config.settings import settings

    backend = settings.planner_backend
    valid_backends = ("heuristic", "local_llm", "cloud_llm", "hermes_agent")

    if backend == "local_llm":
        path = settings.local_llm_model_path
        if not path:
            return False, (
                "AURA_PLANNER_BACKEND is set to 'local_llm', but "
                "AURA_LOCAL_LLM_MODEL_PATH isn't set. Point it at a real "
                ".gguf model file in your .env, or switch back to the "
                "default zero-dependency parser with:\n"
                "    AURA_PLANNER_BACKEND=heuristic"
            )
        if not Path(path).exists():
            return False, (
                f"AURA_PLANNER_BACKEND is set to 'local_llm', but the model "
                f"file at:\n    {path}\ndoesn't exist. Either download a "
                ".gguf model and update AURA_LOCAL_LLM_MODEL_PATH to point "
                "at it for real, or switch back to the default "
                "zero-dependency parser with:\n"
                "    AURA_PLANNER_BACKEND=heuristic\n"
                "(Tip: the README's local_llm example path is a placeholder, "
                "not a real path -- it isn't meant to be used as-is.)"
            )
    elif backend == "cloud_llm":
        if not settings.cloud_llm_base_url:
            return False, (
                "AURA_PLANNER_BACKEND is set to 'cloud_llm', but "
                "AURA_CLOUD_LLM_BASE_URL isn't set. Point it at an "
                "OpenAI-compatible endpoint (e.g. "
                "https://generativelanguage.googleapis.com/v1beta/openai for "
                "Gemini), or switch back to the default zero-dependency "
                "parser with:\n"
                "    AURA_PLANNER_BACKEND=heuristic"
            )
    elif backend == "hermes_agent":
        if not settings.hermes_agent_base_url:
            return False, (
                "AURA_PLANNER_BACKEND is set to 'hermes_agent', but "
                "AURA_HERMES_AGENT_BASE_URL isn't set. Point it at a running "
                "Hermes Agent instance's API server (started via "
                "`hermes gateway`, default http://localhost:8642), or switch "
                "back to the default zero-dependency parser with:\n"
                "    AURA_PLANNER_BACKEND=heuristic"
            )
    elif backend not in valid_backends:
        return False, (
            f"AURA_PLANNER_BACKEND is set to an unknown value '{backend}'. "
            f"Valid options: {' | '.join(valid_backends)}."
        )

    return True, None


def check_display_available() -> tuple[bool, str | None]:
    """
    Warns (does not block) when no display/screenshot backend is reachable.
    This was a real gap: earlier crashes in run_engine.py and `aura explore`
    dying silently under a missing tkinter were exactly the class of
    failure preflight is supposed to catch early for other subsystems, but
    didn't cover for this one. This is advisory only, not a hard failure --
    plenty of legitimate runs (pure API/DB/file capability checks) never
    touch the screen at all, so treating "no display" as fatal here would
    block work that doesn't need a display in the first place.
    """
    from runtime.errors import display_guard
    from runtime.hooks.capture import capture_screenshot
    import uuid as _uuid

    try:
        with display_guard() as guard:
            capture_screenshot(f"preflight_{_uuid.uuid4().hex[:6]}", 0)
        if guard.no_display:
            return False, (
                f"No display/screen-capture backend is reachable ({guard.error}). "
                "This is fine for pure API/database/file capability checks, but "
                "`aura execute`'s vision steps and `aura explore` need a live "
                "display (or a virtual one, e.g. Xvfb) to take screenshots."
            )
    except Exception as e:  # noqa: BLE001 - advisory check, never let it crash preflight itself
        return False, f"Could not verify display availability ({e})."
    return True, None


def check_playwright_browser_available() -> tuple[bool, str | None]:
    """
    Advisory check for whether Playwright and its browser binaries are
    installed -- used by `agents/capability/playwright_validator.py` (Phase
    21) and `aura explore`'s link-checking fallback. Non-fatal: most runs
    don't touch this capability at all.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False, (
            "Playwright isn't installed. Needed only for capability='web_validation' "
            "checks (docs/TRD.md §11.4). Install with: pip install .[automation_anywhere] "
            "&& playwright install chromium"
        )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
    except Exception as e:  # noqa: BLE001 - advisory check
        return False, (
            f"Playwright is installed but its browser binary isn't ({e}). "
            "Run: playwright install chromium"
        )
    return True, None


def check_capability_adapter_dependencies() -> list[str]:
    """
    Advisory-only: reports which optional capability-adapter dependencies
    (paramiko, boto3, azure-storage-blob, google-cloud-storage) aren't
    importable in this environment. Returns a list of human-readable
    warning strings (empty if everything importable is present). Never
    raises and never blocks -- most runs only use a handful of adapters,
    so a missing SDK for one you're not using shouldn't stop anything.
    """
    warnings: list[str] = []
    optional_modules = {
        "paramiko": "SFTP support in agents/capability/file_adapter.py",
        "boto3": "agents/capability/cloud_adapter.py (S3)",
        "azure.storage.blob": "agents/capability/azure_adapter.py",
        "google.cloud.storage": "agents/capability/gcp_adapter.py",
    }
    for module_name, used_by in optional_modules.items():
        try:
            __import__(module_name)
        except ImportError:
            warnings.append(f"'{module_name}' isn't installed -- {used_by} will fail if used.")
    return warnings


def run_preflight_or_exit() -> None:
    """
    Call at the top of any command that will actually run the vision
    pipeline (`execute`). Prints a clear, actionable message and exits
    cleanly rather than letting the run start and crash mid-step.

    Tesseract and the planner backend remain hard blockers (every vision
    step needs both). Display/Playwright/adapter-dependency checks are
    advisory only -- printed as warnings, never blocking -- since many
    legitimate runs don't need all of them (e.g. a pure API/DB capability
    check never touches the screen or a browser).
    """
    import typer

    for check in (check_tesseract_available, check_planner_backend_available):
        ok, message = check()
        if not ok:
            console.print(f"[red]Cannot start:[/red] {message}")
            raise typer.Exit(code=1)

    for advisory_check in (check_display_available, check_playwright_browser_available):
        ok, message = advisory_check()
        if not ok:
            console.print(f"[yellow]Warning:[/yellow] {message}")

    for adapter_warning in check_capability_adapter_dependencies():
        console.print(f"[dim]Note: {adapter_warning}[/dim]")


def run_doctor() -> bool:
    """
    AC2: `aura doctor` -- a standalone, proactive preflight the operator
    can run *before* attempting a real execution, rather than only
    discovering environment problems (Tesseract missing, Hermes Agent
    unreachable, no Playwright browser, etc.) as a mid-run crash or a
    silently-degraded capability. This is deliberately a thin wrapper
    around the same check_* functions run_preflight_or_exit() already
    calls -- no new detection logic, just a full, always-non-blocking
    report of every one of them in one place, plus a summary verdict.

    Unlike run_preflight_or_exit(), this never raises/exits: it's meant to
    be run standalone (`aura doctor`), read by a human, and left at that --
    exit code communicates overall health (0 = all hard checks pass, 1 =
    at least one hard-blocker check failed) without ever halting execute()
    itself. Returns True if every hard-blocking check passed (advisory
    warnings don't affect this).

    Checks run in the same grouping run_preflight_or_exit() uses --
    hard blockers first (every vision step needs both), then advisory
    checks (display, Playwright, Hermes/planner-backend reachability via
    check_planner_backend_available which already covers the
    'hermes_agent' backend's base-url-configured check), then optional
    capability-adapter dependency notes.
    """
    console.print("[bold]AURA environment check[/bold]\n")

    all_hard_ok = True
    console.print("[bold]Hard requirements[/bold] (block every `aura execute` run)")
    for label, check in (
        ("Tesseract OCR", check_tesseract_available),
        ("Planner backend config", check_planner_backend_available),
    ):
        ok, message = check()
        all_hard_ok = all_hard_ok and ok
        if ok:
            console.print(f"  [green]✓[/green] {label}")
        else:
            console.print(f"  [red]✗ {label}[/red]\n    {message}")

    console.print("\n[bold]Advisory[/bold] (only needed for some capabilities/steps)")
    for label, advisory_check in (
        ("Display / screenshot backend", check_display_available),
        ("Playwright browser binary", check_playwright_browser_available),
    ):
        ok, message = advisory_check()
        if ok:
            console.print(f"  [green]✓[/green] {label}")
        else:
            console.print(f"  [yellow]⚠ {label}[/yellow]\n    {message}")

    adapter_warnings = check_capability_adapter_dependencies()
    if adapter_warnings:
        console.print("\n[bold]Optional capability-adapter dependencies[/bold]")
        for w in adapter_warnings:
            console.print(f"  [dim]· {w}[/dim]")
    else:
        console.print("\n[bold]Optional capability-adapter dependencies[/bold]\n  [green]✓[/green] all present")

    console.print()
    if all_hard_ok:
        console.print("[green bold]AURA is ready to run `aura execute`.[/green bold]")
    else:
        console.print(
            "[red bold]AURA cannot run `aura execute` yet[/red bold] -- fix the [red]✗[/red] items above first. "
            "Warnings ([yellow]⚠[/yellow]) don't block execution but mean some capabilities/steps will be unavailable."
        )
    return all_hard_ok
