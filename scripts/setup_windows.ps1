# scripts/setup_windows.ps1
#
# Option 1 deployment (see README.md): local CLI on each QA engineer's own
# machine. Sets up a working AURA dev environment from a clean checkout --
# venv, dependencies, and a .env pointing at Tesseract if it's found.
#
# Usage (from the aura_build/ folder, in PowerShell):
#   .\scripts\setup_windows.ps1
#
# Safe to re-run -- skips steps that are already done.

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host "    [OK] $msg" -ForegroundColor Green
}

function Write-Warn($msg) {
    Write-Host "    [!] $msg" -ForegroundColor Yellow
}

function Test-CommandExists($commandName) {
    return [bool](Get-Command $commandName -ErrorAction SilentlyContinue)
}

# -- 1. Python check --------------------------------------------------------
Write-Step "Checking for Python 3.10+"
try {
    $pyVersion = (python --version) 2>&1
    Write-Ok "Found $pyVersion"
} catch {
    Write-Host ""
    Write-Host "Python was not found on PATH." -ForegroundColor Red
    Write-Host "Install Python 3.10+ from https://python.org (check 'Add to PATH' during install), then re-run this script." -ForegroundColor Red
    exit 1
}

# -- 2. Virtual environment --------------------------------------------------
Write-Step "Setting up virtual environment (.venv)"
if (Test-Path ".venv") {
    Write-Ok ".venv already exists, skipping creation"
} else {
    python -m venv .venv
    Write-Ok "Created .venv"
}

$venvPython = ".venv\Scripts\python.exe"
$venvPip = ".venv\Scripts\pip.exe"

# -- 3. Install AURA + dev dependencies -------------------------------------
Write-Step "Installing AURA and dependencies (this can take a minute)"
& $venvPython -m pip install --upgrade pip --quiet
& $venvPython -m pip install -e ".[dev]" --quiet
Write-Ok "Installed"

# -- 4. Locate Tesseract and write .env --------------------------------------
Write-Step "Looking for Tesseract OCR"
$tesseractPath = $null

if (Test-CommandExists "tesseract.exe") {
    $tesseractPath = (Get-Command tesseract.exe).Source
} elseif (Test-CommandExists "tesseract") {
    $tesseractPath = (Get-Command tesseract).Source
}

$commonPaths = @(
    "C:\Program Files\Tesseract-OCR\tesseract.exe",
    "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
)

if (-not $tesseractPath) {
    foreach ($p in $commonPaths) {
        if (Test-Path $p) {
            $tesseractPath = $p
            break
        }
    }
}

if (-not $tesseractPath -and (Test-CommandExists "winget")) {
    Write-Warn "Tesseract was not found. Trying to install it with winget..."
    & winget install --id UB-Mannheim.TesseractOCR -e --source winget --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -eq 0) {
        if (Test-CommandExists "tesseract.exe") {
            $tesseractPath = (Get-Command tesseract.exe).Source
        } elseif (Test-CommandExists "tesseract") {
            $tesseractPath = (Get-Command tesseract).Source
        } else {
            foreach ($p in $commonPaths) {
                if (Test-Path $p) {
                    $tesseractPath = $p
                    break
                }
            }
        }
    }
}

if ($tesseractPath) {
    Write-Ok "Found Tesseract at $tesseractPath"
    $envContent = "AURA_TESSERACT_CMD=$tesseractPath`n"
    if (Test-Path ".env") {
        Write-Warn ".env already exists -- not overwriting. Add this line manually if it's missing:"
        Write-Host "    AURA_TESSERACT_CMD=$tesseractPath"
    } else {
        Set-Content -Path ".env" -Value $envContent -NoNewline
        Write-Ok "Wrote .env with AURA_TESSERACT_CMD"
    }
} else {
    Write-Warn "Tesseract OCR was not found in the usual install locations."
    Write-Host "    Download it from: https://github.com/UB-Mannheim/tesseract/wiki"
    Write-Host "    After installing, either add it to PATH, or create a .env file containing:"
    Write-Host "        AURA_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe"
}

# -- 5. Check for a bundled local LLM model ----------------------------------
Write-Step "Checking for a bundled local LLM model (models\*.gguf)"
$bundledModel = Get-ChildItem -Path "models" -Filter "*.gguf" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($bundledModel) {
    Write-Ok "Found $($bundledModel.Name) -- AURA will use the local LLM planner backend automatically, no .env editing needed."
    Write-Warn "The local LLM backend also requires the 'llm' extra. If you haven't installed it yet, run:"
    Write-Host "    .\scripts\install_llm_backend.ps1"
} else {
    Write-Ok "None found -- AURA will use the default zero-dependency heuristic parser."
    Write-Host "    (Drop a .gguf file into models\ any time to switch to the local LLM backend automatically.)"
}

# -- 6. Register `aura` as a globally accessible command --------------------
Write-Step "Registering 'aura' as a globally accessible command"

$scriptsDir = (Resolve-Path ".venv\Scripts").Path
$auraExe    = Join-Path $scriptsDir "aura.exe"

if (-not (Test-Path $auraExe)) {
    Write-Warn "aura.exe not found at $auraExe -- pip install may not have completed. Skipping global registration."
} else {
    # Read the current user-level PATH from the registry
    $regPath   = "HKCU:\Environment"
    $currentPath = (Get-ItemProperty -Path $regPath -Name "PATH" -ErrorAction SilentlyContinue).PATH

    if ($null -eq $currentPath) { $currentPath = "" }

    if ($currentPath -notlike "*$scriptsDir*") {
        $newPath = if ($currentPath) { "$currentPath;$scriptsDir" } else { $scriptsDir }
        Set-ItemProperty -Path $regPath -Name "PATH" -Value $newPath -Type ExpandString
        Write-Ok "Added $scriptsDir to user PATH"
        Write-Warn "Open a NEW terminal window for the PATH change to take effect."
    } else {
        Write-Ok "$scriptsDir is already in user PATH"
    }

    # Broadcast WM_SETTINGCHANGE so the running Explorer picks up the new PATH
    # without requiring a log-off / reboot.
    try {
        $signature = @"
[DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(
    IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam,
    uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);
"@
        $type   = Add-Type -MemberDefinition $signature -Name "NativeMethods" -Namespace "Win32" -PassThru
        $result = [UIntPtr]::Zero
        $type::SendMessageTimeout([IntPtr]0xffff, 0x001A, [UIntPtr]::Zero, "Environment", 2, 5000, [ref]$result) | Out-Null
        Write-Ok "Broadcast PATH change to running shell sessions"
    } catch {
        Write-Warn "Could not broadcast PATH change (non-critical) -- open a new terminal to use 'aura' globally."
    }
}

# -- 7. Verify --------------------------------------------------------------
Write-Step "Running the test suite to verify everything's working"
& $venvPython -m pytest -q
if ($LASTEXITCODE -eq 0) {
    Write-Ok "All tests passed -- AURA is ready to use."
} else {
    Write-Warn "Some tests failed. If the failures mention Tesseract, follow the guidance above and re-run this script."
}

Write-Host ""
Write-Host "Setup complete. AURA is ready!" -ForegroundColor Cyan
Write-Host ""
Write-Host "The 'aura' command is now available globally." -ForegroundColor Green
Write-Host "Open a new terminal and try:"
Write-Host "    aura --help"
Write-Host "    aura execute --url https://example.com --prompt ""Describe what to test in plain English"""
Write-Host ""
Write-Host "You can also use the Python wrappers in the project root:"
Write-Host "    python setup.py   -- re-run setup"
Write-Host "    python run.py     -- run aura (shows banner)"
