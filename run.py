"""
run.py
~~~~~~
Convenience Python entry point for AURA.

Launches `aura` from the local .venv without the user needing to
activate the virtual environment first.  Mirrors run.bat but works
cross-platform and shows the AURA banner before handing off to the CLI.

Usage
-----
    python run.py --help
    python run.py execute --url https://example.com --prompt "Check the homepage"
    python run.py init
    python run.py explore https://example.com

All arguments are forwarded verbatim to the `aura` CLI.

Global registration (run once, then use `aura` from any folder):
    python run.py --install-global
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

# ── Project root ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent


def _find_aura_exe() -> Path:
    """Locate the `aura` executable inside the project's .venv."""
    if platform.system() == "Windows":
        candidates = [
            ROOT / ".venv" / "Scripts" / "aura.exe",
            ROOT / ".venv" / "Scripts" / "aura",
        ]
    else:
        candidates = [
            ROOT / ".venv" / "bin" / "aura",
        ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    return None


def _print_banner() -> None:
    """Print the AURA banner (best-effort)."""
    try:
        sys.path.insert(0, str(ROOT))
        from ui.logo import print_banner
        print_banner()
    except Exception:
        print("\n  AURA - Autonomous Unified RPA Agent\n")


# ── Global registration ───────────────────────────────────────────────────────
_SHIM_DIR = Path.home() / ".aura" / "bin"


def _add_to_user_path(directory: Path) -> bool:
    """Append *directory* to the current user's PATH and broadcast the change.

    Uses `setx` (not just a registry write) so that all open CMD and
    PowerShell windows receive the WM_SETTINGCHANGE broadcast immediately.
    Returns True if the PATH was actually modified.
    """
    import winreg  # only available on Windows

    key_path = r"Environment"
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ | winreg.KEY_WRITE
    ) as key:
        try:
            current, _ = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            current = ""

    dir_str = str(directory)
    parts = [p for p in current.split(";") if p]
    already_present = dir_str.lower() in [p.lower() for p in parts]

    if already_present:
        # Still call setx to broadcast, in case a previous run only used
        # winreg (which doesn't broadcast to open terminals).
        new_value = current
        modified = False
    else:
        new_value = ";".join(parts + [dir_str])
        modified = True

    # setx writes the registry AND broadcasts WM_SETTINGCHANGE so that
    # every open CMD / PowerShell window picks up the new PATH immediately.
    subprocess.run(
        ["setx", "PATH", new_value],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return modified


def install_global() -> None:
    """Create a global `aura` shim so the command works from any folder."""
    aura_exe = _find_aura_exe()
    if aura_exe is None:
        print()
        print("  \033[91m[ERROR]\033[0m  AURA is not set up yet.", file=sys.stderr)
        print("           Run  python install.py  first to install everything.", file=sys.stderr)
        print()
        sys.exit(1)

    _SHIM_DIR.mkdir(parents=True, exist_ok=True)

    if platform.system() == "Windows":
        bat = _SHIM_DIR / "aura.bat"
        bat.write_text(
            f'@echo off\r\n"{aura_exe}" %*\r\n',
            encoding="utf-8",
        )
        # Also drop a .cmd alias for PowerShell compatibility
        cmd = _SHIM_DIR / "aura.cmd"
        cmd.write_text(
            f'@echo off\r\n"{aura_exe}" %*\r\n',
            encoding="utf-8",
        )
        shim_path = bat
    else:
        shim = _SHIM_DIR / "aura"
        shim.write_text(
            f'#!/usr/bin/env sh\nexec "{aura_exe}" "$@"\n',
            encoding="utf-8",
        )
        shim.chmod(0o755)
        shim_path = shim

    print(f"  \033[92m[OK]\033[0m  Shim created → {shim_path}")

    if platform.system() == "Windows":
        modified = _add_to_user_path(_SHIM_DIR)
        if modified:
            print(f"  \033[92m[OK]\033[0m  Added {_SHIM_DIR} to your user PATH.")
            print()
            print("  \033[93m[ACTION REQUIRED]\033[0m  Open a NEW terminal (or restart VS Code) and run:")
            print("         aura --help")
        else:
            print(f"  \033[92m[OK]\033[0m  {_SHIM_DIR} is already on your PATH.")
            print("         You can now run  aura  from any folder!")
    else:
        print(f"  Add the following line to your shell profile (~/.bashrc, ~/.zshrc, etc.):")
        print(f'      export PATH="{_SHIM_DIR}:$PATH"')


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    # Handle global registration before anything else
    if "--install-global" in sys.argv:
        _print_banner()
        install_global()
        sys.exit(0)

    # Show banner only when no args (plain `python run.py`) or when --help
    show_banner = len(sys.argv) == 1 or "--help" in sys.argv or "-h" in sys.argv
    if show_banner:
        _print_banner()

    aura_exe = _find_aura_exe()

    if aura_exe is None:
        print()
        print("  \033[91m[ERROR]\033[0m  AURA is not set up yet.", file=sys.stderr)
        print("           Run  python install.py  first to install everything.", file=sys.stderr)
        print()
        sys.exit(1)

    # Forward all CLI arguments to the real aura entry point
    cli_args = sys.argv[1:]

    # If called with no arguments, show the help screen
    if not cli_args:
        cli_args = ["--help"]

    result = subprocess.run(
        [str(aura_exe)] + cli_args,
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
