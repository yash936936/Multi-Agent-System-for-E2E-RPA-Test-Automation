@echo off
REM install.bat -- one-click AURA setup for Windows.
REM
REM Double-click this file (or run it from cmd/PowerShell) to set up a
REM complete, working AURA installation: virtual environment, dependencies,
REM Tesseract OCR auto-detection, and a check for a bundled local LLM model.
REM Wraps scripts\setup_windows.ps1 so the person running it doesn't need to
REM know PowerShell execution-policy flags.
REM
REM Safe to re-run.

setlocal
cd /d "%~dp0"

echo ================================================
echo  AURA Setup
echo ================================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo Python was not found on PATH.
    echo.
    echo Install Python 3.10 or later from https://www.python.org/downloads/
    echo During install, make sure "Add python.exe to PATH" is checked.
    echo Then re-run this file.
    echo.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup_windows.ps1"
if errorlevel 1 (
    echo.
    echo Setup did not complete successfully -- see the messages above.
    pause
    exit /b 1
)

echo.
echo ================================================
echo  Setup complete
echo ================================================
echo.
echo To run a test, use run.bat, for example:
echo     run.bat execute --url https://example.com --prompt "Describe what to test"
echo.
pause
