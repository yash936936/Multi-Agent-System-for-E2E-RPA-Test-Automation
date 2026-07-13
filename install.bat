@echo off
REM install.bat -- one-click AURA setup for Windows.
REM
REM Double-click this file (or run it from cmd/PowerShell) to set up a
REM complete, working AURA installation: virtual environment, dependencies,
REM Tesseract OCR auto-detection, global `aura` command registration, and a
REM check for a bundled local LLM model.
REM
REM Wraps setup.py (Python) which in turn calls scripts\setup_windows.ps1 for
REM any PowerShell-only steps.  After setup the terminal window is closed
REM automatically unless you pass --no-close.
REM
REM Usage:
REM   install.bat              -- full setup, close window when done
REM   install.bat --no-close   -- full setup, keep window open
REM   install.bat --skip-tests -- skip pytest (faster)
REM
REM Safe to re-run.

setlocal
cd /d "%~dp0"

echo.
echo ================================================================
echo   AURA Setup
echo ================================================================
echo.

REM ── Require Python ────────────────────────────────────────────────
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on PATH.
    echo.
    echo   Install Python 3.10 or later from https://www.python.org/downloads/
    echo   During install, make sure "Add python.exe to PATH" is checked.
    echo   Then re-run this file.
    echo.
    pause
    exit /b 1
)

REM ── Delegate to install.py ──────────────────────────────────────────
REM   Pass through any extra flags the user gave to install.bat
python "%~dp0install.py" %*
if errorlevel 1 (
    echo.
    echo [ERROR] Setup did not complete successfully -- see the messages above.
    pause
    exit /b 1
)

REM setup.py closes the terminal itself unless --no-close was passed.
REM If we reach this line the user requested --no-close.
pause
