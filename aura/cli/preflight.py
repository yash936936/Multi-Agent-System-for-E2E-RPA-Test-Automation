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
    elif backend == "anthropic":
        if not settings.allow_network_calls:
            return False, (
                "AURA_PLANNER_BACKEND is set to 'anthropic', which requires "
                "AURA_ALLOW_NETWORK_CALLS=true (AURA defaults to fully "
                "offline). Either set that, or switch back to the default "
                "zero-dependency parser with:\n"
                "    AURA_PLANNER_BACKEND=heuristic"
            )
    elif backend not in ("heuristic", "local_llm", "anthropic"):
        return False, (
            f"AURA_PLANNER_BACKEND is set to an unknown value '{backend}'. "
            "Valid options: heuristic | local_llm | anthropic."
        )

    return True, None


def run_preflight_or_exit() -> None:
    """
    Call at the top of any command that will actually run the vision
    pipeline (`execute`). Prints a clear, actionable message and exits
    cleanly rather than letting the run start and crash mid-step.
    """
    import typer

    for check in (check_tesseract_available, check_planner_backend_available):
        ok, message = check()
        if not ok:
            console.print(f"[red]Cannot start:[/red] {message}")
            raise typer.Exit(code=1)
