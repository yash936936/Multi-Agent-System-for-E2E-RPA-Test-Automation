"""
install.py
~~~~~~~~~~
Convenience Python wrapper around the AURA installation process.

Run this instead of (or in addition to) install.bat:

    python install.py

What it does
------------
1.  Shows the AURA banner.
2.  Checks Python >= 3.10.
3.  Creates / verifies the .venv virtual environment.
4.  Pip-installs AURA + dev extras (editable install).
5.  Locates Tesseract OCR and updates .env.
6.  Registers the `aura` command globally on this machine so it is
    accessible from any directory or terminal without activating the venv.
7.  Runs the test suite to verify the installation.
8.  Closes the terminal window gracefully (optional, see --no-close).

Usage
-----
    python install.py              # full install + close terminal
    python install.py --no-close   # full install, keep terminal open
    python install.py --skip-tests # skip pytest run (faster)
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# ── Project root (directory that contains this file) ─────────────────────────
ROOT = Path(__file__).resolve().parent


# ── Helpers ──────────────────────────────────────────────────────────────────
def _banner() -> None:
    """Print the AURA ASCII banner (best-effort)."""
    try:
        sys.path.insert(0, str(ROOT))
        from ui.logo import print_banner
        print_banner()
    except Exception:
        print("\n  AURA - Autonomous Unified RPA Agent\n")


def _step(msg: str) -> None:
    _w = shutil.get_terminal_size((80, 24)).columns
    print(f"\n{'=' * _w}")
    print(f"  ==>  {msg}")
    print("=" * _w)


def _ok(msg: str) -> None:
    print(f"    \033[92m[OK]\033[0m  {msg}")


def _warn(msg: str) -> None:
    print(f"    \033[93m[!]\033[0m   {msg}", file=sys.stderr)


def _fail(msg: str) -> None:
    print(f"\n  \033[91m[FAIL]\033[0m  {msg}\n", file=sys.stderr)
    sys.exit(1)


def _run(*cmd: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(cmd),
        cwd=ROOT,
        check=check,
        capture_output=capture,
        text=True,
    )


# ── Step implementations ──────────────────────────────────────────────────────

def check_python() -> None:
    _step("Checking Python version")
    vi = sys.version_info
    if (vi.major, vi.minor) < (3, 10):
        _fail(
            f"Python 3.10+ is required, but you are running {vi.major}.{vi.minor}.\n"
            "  Download a newer version from https://python.org and re-run setup.py."
        )
    _ok(f"Python {vi.major}.{vi.minor}.{vi.micro}")


def setup_venv() -> Path:
    _step("Setting up virtual environment (.venv)")
    venv_dir = ROOT / ".venv"
    if venv_dir.exists():
        _ok(".venv already exists — skipping creation")
    else:
        _run(sys.executable, "-m", "venv", str(venv_dir))
        _ok("Created .venv")

    if platform.system() == "Windows":
        python_exe = venv_dir / "Scripts" / "python.exe"
    else:
        python_exe = venv_dir / "bin" / "python"

    if not python_exe.exists():
        _fail(f"Expected venv Python at {python_exe} — something went wrong during venv creation.")
    return python_exe


def install_package(python_exe: Path) -> None:
    _step("Installing AURA and dependencies  (may take a minute…)")
    _run(str(python_exe), "-m", "pip", "install", "--upgrade", "pip", "--quiet")
    # Upgrade setuptools + wheel in the venv FIRST so the editable install
    # uses the same (compatible) versions rather than the isolated build-env
    # versions, which can trigger the "Exactly one .egg-info" assertion in
    # setuptools 75+ when package discovery runs inside a temp directory.
    _run(
        str(python_exe), "-m", "pip", "install",
        "--upgrade", "setuptools>=75.6.0", "wheel",
        "--quiet",
    )
    try:
        # --no-build-isolation tells pip to reuse the venv's setuptools/wheel
        # instead of spinning up a new isolated environment in %TEMP%.  This is
        # the standard practice for editable installs of local projects and
        # avoids the egg-info generation failure seen with setuptools 75+.
        _run(
            str(python_exe), "-m", "pip", "install",
            "-e", ".[dev]",
            "--no-build-isolation",
            "--quiet",
        )
    except subprocess.CalledProcessError:
        _warn("pip install returned a non-zero exit code — see output above.")
        _warn("If the error mentions 'setup.py egg_info', run:")
        _warn("  pip install --upgrade setuptools wheel")
        _warn("and then re-run setup.py.")
        sys.exit(1)
    _ok("All packages installed")



def locate_tesseract() -> Path | None:
    """Return path to tesseract.exe if found, else None."""
    # 1. Already on PATH
    found = shutil.which("tesseract") or shutil.which("tesseract.exe")
    if found:
        return Path(found)

    # 2. Common Windows install locations
    if platform.system() == "Windows":
        candidates = [
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        ]
        for c in candidates:
            if c.exists():
                return c
    return None


def configure_env(tesseract_path: Path | None) -> None:
    _step("Configuring .env")
    env_file = ROOT / ".env"

    if tesseract_path:
        _ok(f"Found Tesseract at {tesseract_path}")
        if env_file.exists():
            content = env_file.read_text(encoding="utf-8")
            if "AURA_TESSERACT_CMD" not in content:
                with env_file.open("a", encoding="utf-8") as f:
                    f.write(f"\nAURA_TESSERACT_CMD={tesseract_path}\n")
                _ok("Appended AURA_TESSERACT_CMD to existing .env")
            else:
                _ok(".env already contains AURA_TESSERACT_CMD — not overwriting")
        else:
            env_file.write_text(f"AURA_TESSERACT_CMD={tesseract_path}\n", encoding="utf-8")
            _ok("Created .env with AURA_TESSERACT_CMD")
    else:
        _warn("Tesseract OCR not found in standard locations.")
        print("    Download: https://github.com/UB-Mannheim/tesseract/wiki")
        print("    Then add to .env:  AURA_TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe")


def register_global_command(python_exe: Path) -> None:
    """
    Make `aura` (and `Aura`) available as a machine-wide command.

    Strategy (Windows)
    ------------------
    The .venv Scripts folder already contains `aura.exe` (placed there by
    `pip install -e .` via pyproject.toml [project.scripts]).  We add that
    folder to the *user* PATH environment variable so that `aura` works from
    any terminal without activating the venv.

    Strategy (Unix/macOS)
    ---------------------
    Create a symlink /usr/local/bin/aura → .venv/bin/aura  (requires sudo
    only if /usr/local/bin is not user-writable).  Also symlinks `Aura`.
    """
    _step("Registering `aura` as a globally accessible command")

    if platform.system() == "Windows":
        scripts_dir = python_exe.parent          # .venv\Scripts
        aura_exe    = scripts_dir / "aura.exe"

        if not aura_exe.exists():
            _warn(f"aura.exe not found at {aura_exe}. Skipping global registration.")
            _warn("Make sure `pip install -e .` completed without errors.")
            return

        # Read current user PATH
        import winreg
        reg_key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Environment",
            0,
            winreg.KEY_READ | winreg.KEY_SET_VALUE,
        )
        try:
            current_path, _ = winreg.QueryValueEx(reg_key, "PATH")
        except FileNotFoundError:
            current_path = ""

        scripts_str = str(scripts_dir)
        if scripts_str.lower() not in current_path.lower():
            new_path = f"{current_path};{scripts_str}" if current_path else scripts_str
            winreg.SetValueEx(reg_key, "PATH", 0, winreg.REG_EXPAND_SZ, new_path)
            _ok(f"Added {scripts_str} to user PATH")
            print("    \033[93m[!]\033[0m   Open a NEW terminal window for the PATH change to take effect.")
        else:
            _ok(f"{scripts_str} is already in user PATH")

        winreg.CloseKey(reg_key)

        # Broadcast the WM_SETTINGCHANGE message so the current Explorer session
        # picks up the PATH change without a full log-off.
        try:
            import ctypes
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x001A
            ctypes.windll.user32.SendMessageTimeoutW(
                HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", 2, 5000, None
            )
        except Exception:
            pass  # non-critical

    else:
        # Unix / macOS
        venv_bin  = python_exe.parent
        aura_bin  = venv_bin / "aura"
        link_dir  = Path("/usr/local/bin")
        link_aura = link_dir / "aura"
        link_Aura = link_dir / "Aura"

        if not aura_bin.exists():
            _warn(f"aura binary not found at {aura_bin}. Skipping global registration.")
            return

        for link_path, target in [(link_aura, aura_bin), (link_Aura, aura_bin)]:
            if link_path.exists() or link_path.is_symlink():
                link_path.unlink()
            try:
                link_path.symlink_to(target)
                _ok(f"Created symlink {link_path} → {target}")
            except PermissionError:
                _warn(f"Could not write to {link_dir} — run as root/sudo or add {venv_bin} to your PATH manually.")
                break


def run_tests(python_exe: Path) -> None:
    _step("Running test suite to verify installation")
    result = _run(str(python_exe), "-m", "pytest", "-q", check=False)
    if result.returncode == 0:
        _ok("All tests passed — AURA is ready to use!")
    else:
        _warn("Some tests failed. Check the output above for details.")
        _warn("If failures are Tesseract-related, install Tesseract and re-run setup.py.")


def close_terminal() -> None:
    """Best-effort: close the terminal / console window after a short delay."""
    _step("Setup complete — closing this window in 5 seconds …")
    import time
    for remaining in range(5, 0, -1):
        print(f"\r  Closing in {remaining}s …", end="", flush=True)
        time.sleep(1)
    print()

    if platform.system() == "Windows":
        # Close the parent cmd/PowerShell console window
        try:
            import ctypes
            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass
        # Fallback: taskkill the parent process
        try:
            ppid = os.getppid()
            subprocess.run(["taskkill", "/PID", str(ppid), "/F"], check=False)
        except Exception:
            pass
    else:
        # Unix: send SIGHUP to parent shell
        try:
            import signal
            os.kill(os.getppid(), signal.SIGHUP)
        except Exception:
            pass


# ── Main ──────────────────────────────────────────────────────────────────────

# pip subcommands that should be handled by the build backend, not us.
_PIP_COMMANDS = {
    "egg_info", "install", "bdist_wheel", "sdist",
    "bdist_egg", "develop", "build",
}


def main() -> None:
    # ── pip guard ────────────────────────────────────────────────────────────
    # When pip performs an editable install it runs `setup.py egg_info` (and
    # similar subcommands) as a subprocess.  Our argparse would reject those
    # args and cause the install to fail.  Detect that case and bail out
    # silently so pip can carry on with its own logic.
    if len(sys.argv) > 1 and sys.argv[1] in _PIP_COMMANDS:
        sys.exit(0)

    parser = argparse.ArgumentParser(
        description="AURA setup — install dependencies and register the `aura` command globally.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--no-close",
        action="store_true",
        help="Keep the terminal open after setup finishes (useful for debugging).",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip the pytest verification step.",
    )
    args = parser.parse_args()

    _banner()

    check_python()
    python_exe = setup_venv()
    install_package(python_exe)
    tesseract = locate_tesseract()
    configure_env(tesseract)
    register_global_command(python_exe)

    if not args.skip_tests:
        run_tests(python_exe)

    print()
    print("  \033[92m✓ AURA installation complete!\033[0m")
    print()
    print("  Quick-start:")
    print("    aura --help")
    print("    aura execute --url https://example.com --prompt \"Describe what to test\"")
    print()

    if not args.no_close:
        close_terminal()


if __name__ == "__main__":
    main()
