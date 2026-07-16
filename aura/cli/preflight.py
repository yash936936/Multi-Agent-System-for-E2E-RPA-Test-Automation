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
    """
    from pathlib import Path

    from config.settings import settings

    backend = settings.planner_backend

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
    elif backend not in ("heuristic", "local_llm"):
        return False, (
            f"AURA_PLANNER_BACKEND is set to an unknown value '{backend}'. "
            "Valid options: heuristic | local_llm."
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
