# scripts/build_exe.ps1
#
# Option 2 deployment (see README.md): standalone aura.exe, no Python needed
# on the target machine. Wraps the exact PyInstaller command verified by
# actually building and running the packaged binary end-to-end (see
# decisions.md D-012) -- including two flags that are easy to miss and
# cause silent failures if left out:
#
#   --hidden-import x3   required because ToolRegistry resolves the
#                         Planner/Vision/DataSynth agent modules dynamically
#                         via importlib from strings in tool_registry.yaml,
#                         which PyInstaller's static analysis can't see.
#                         Without these, the exe launches fine and shows
#                         the spec table, then crashes with
#                         ModuleNotFoundError the moment a step runs.
#
#   --add-data x2         required to bundle the Jinja2 report template
#                         and tool_registry.yaml, neither of which
#                         PyInstaller auto-detects (non-Python data files).
#
# Usage (from the aura_build/ folder, with .venv already set up -- run
# scripts\setup_windows.ps1 first if you haven't):
#   .\scripts\build_exe.ps1
#
# Output: dist\aura.exe

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host "    [OK] $msg" -ForegroundColor Green
}

if (-not (Test-Path ".venv")) {
    Write-Host "No .venv found. Run scripts\setup_windows.ps1 first." -ForegroundColor Red
    exit 1
}

$venvPip = ".venv\Scripts\pip.exe"
$venvPyinstaller = ".venv\Scripts\pyinstaller.exe"

Write-Step "Installing PyInstaller"
& $venvPip install pyinstaller --quiet
Write-Ok "Installed"

Write-Step "Cleaning previous build artifacts"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue build, dist, aura.spec
Write-Ok "Clean"

$bundledModelPreBuild = Get-ChildItem -Path "models" -Filter "*.gguf" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($bundledModelPreBuild) {
    & ".venv\Scripts\python.exe" -c "import llama_cpp" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "A model is present in models\ but llama-cpp-python isn't installed in .venv." -ForegroundColor Yellow
        Write-Host "PyInstaller can only bundle what's actually installed at build time -- the" -ForegroundColor Yellow
        Write-Host "packaged exe would fail to load the local LLM backend. Run this first:" -ForegroundColor Yellow
        Write-Host "    .\scripts\install_llm_backend.ps1" -ForegroundColor Yellow
        Write-Host "Then re-run this build script. Continuing with the heuristic-only build for now." -ForegroundColor Yellow
        Write-Host ""
    }
}

Write-Step "Building aura.exe (this takes a minute or two)"
& $venvPyinstaller --onefile --name aura --console `
    --add-data "config\tool_registry.yaml;config" `
    --add-data "reports\templates;reports\templates" `
    --hidden-import agents.planner.tool `
    --hidden-import agents.vision.tool `
    --hidden-import agents.data_synth.tool `
    aura\main.py

if (-not (Test-Path "dist\aura.exe")) {
    Write-Host "Build failed -- dist\aura.exe was not created. Check the PyInstaller output above." -ForegroundColor Red
    exit 1
}

Write-Ok "Built dist\aura.exe"

# -- Assemble a ready-to-distribute folder: exe + model + sample requirements --
# The model is deliberately NOT embedded inside the --onefile binary itself:
# PyInstaller's onefile mode re-extracts everything bundled that way to a
# fresh temp directory on every single launch, which is fine for small
# template/config files but would mean re-extracting a multi-GB .gguf file
# every time AURA starts. Placing it in a models\ folder next to aura.exe
# instead works with config/settings.py's existing frozen-exe path
# resolution (project_root = the folder aura.exe lives in) -- the model is
# auto-detected there with zero extra wiring, same as the source install.
Write-Step "Assembling distribution folder"
$distDir = "dist\aura_distribution"
if (Test-Path $distDir) { Remove-Item -Recurse -Force $distDir }
New-Item -ItemType Directory -Path $distDir | Out-Null

Copy-Item "dist\aura.exe" $distDir
Copy-Item -Recurse "requirements_input" (Join-Path $distDir "requirements_input")
Copy-Item -Recurse "target_app" (Join-Path $distDir "target_app")

$bundledModel = Get-ChildItem -Path "models" -Filter "*.gguf" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($bundledModel) {
    New-Item -ItemType Directory -Path (Join-Path $distDir "models") | Out-Null
    Copy-Item $bundledModel.FullName (Join-Path $distDir "models")
    Write-Ok "Included local LLM model: $($bundledModel.Name) -- the packaged exe will use it automatically"
} else {
    Write-Ok "No models\*.gguf found -- packaged exe will use the default heuristic parser (no model needed)"
}

Set-Content -Path (Join-Path $distDir "README.txt") -Value @"
AURA -- ready to run.

Requirements on this machine:
  - Tesseract OCR installed (not bundled): https://github.com/UB-Mannheim/tesseract/wiki
    If it's not on PATH, set AURA_TESSERACT_CMD in a .env file next to aura.exe.

Try it:
  aura.exe execute requirements_input\example_login_flow.md --yes
  aura.exe execute --url https://example.com --prompt "Describe what to test"
  aura.exe execute --url https://example.com --scroll-test

No Python install, virtual environment, or pip install required -- everything
except Tesseract OCR (and a models\ folder for the local LLM backend, if present)
is bundled inside aura.exe.
"@

Write-Ok "Distribution folder ready: $distDir"
