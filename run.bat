@echo off
REM run.bat -- launches AURA without needing to manually activate the venv.
REM
REM Usage:
REM     run.bat execute --url https://example.com --prompt "Check the homepage loads"
REM     run.bat execute --url https://example.com --scroll-test
REM     run.bat init
REM
REM Run install.bat first if you haven't set up AURA yet.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\aura.exe" (
    echo AURA isn't set up yet. Run install.bat first.
    pause
    exit /b 1
)

".venv\Scripts\aura.exe" %*
