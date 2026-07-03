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
& $venvPip install --upgrade pip --quiet
& $venvPip install -e ".[dev]" --quiet
Write-Ok "Installed"

# -- 4. Locate Tesseract and write .env --------------------------------------
Write-Step "Looking for Tesseract OCR"
$commonPaths = @(
    "C:\Program Files\Tesseract-OCR\tesseract.exe",
    "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
)
$tesseractPath = $null
foreach ($p in $commonPaths) {
    if (Test-Path $p) {
        $tesseractPath = $p
        break
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

# -- 6. Verify --------------------------------------------------------------
Write-Step "Running the test suite to verify everything's working"
& $venvPython -m pytest -q
if ($LASTEXITCODE -eq 0) {
    Write-Ok "All tests passed -- AURA is ready to use."
} else {
    Write-Warn "Some tests failed. If the failures mention Tesseract, follow the guidance above and re-run this script."
}

Write-Host ""
Write-Host "Setup complete. To start using AURA:" -ForegroundColor Cyan
Write-Host "    .venv\Scripts\activate"
Write-Host "    aura execute --url https://example.com --prompt ""Describe what to test in plain English"""
