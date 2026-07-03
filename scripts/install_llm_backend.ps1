# scripts/install_llm_backend.ps1
#
# Installs the optional local LLM planner backend (llama-cpp-python) using
# a prebuilt CPU wheel from abetlen's wheel index, rather than
# `pip install -e ".[llm]"`'s default source build.
#
# Why: building llama-cpp-python from source vendors llama.cpp's full
# source tree, including a web UI with deeply nested component paths.
# Combined with pip's temp-extraction directory, this reliably exceeds
# Windows' 260-character MAX_PATH limit and fails with an OSError pointing
# at some deeply nested .svelte file under vendor\llama.cpp\tools\ui\...
# A real user hit exactly this. The prebuilt wheel sidesteps it entirely --
# no source extraction, no compilation.
#
# Usage (from the aura_build\ folder, with your venv active):
#   .\scripts\install_llm_backend.ps1
#
# Safe to re-run.

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

# -- 1. Confirm we're in a venv ---------------------------------------------
Write-Step "Checking for an active virtual environment"
if (-not $env:VIRTUAL_ENV) {
    Write-Warn "No active venv detected. Activate yours first, e.g.:"
    Write-Warn "    .\.venv\Scripts\activate"
    exit 1
}
Write-Ok "Using venv at $env:VIRTUAL_ENV"

# -- 2. Remove any partial/failed source-build install ----------------------
Write-Step "Removing any existing llama-cpp-python install"
pip uninstall llama-cpp-python -y 2>$null | Out-Null
Write-Ok "Clean slate"

# -- 3. Install the prebuilt CPU wheel ---------------------------------------
Write-Step "Installing llama-cpp-python from prebuilt CPU wheels (no compilation)"
pip install llama-cpp-python --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
if ($LASTEXITCODE -ne 0) {
    Write-Warn "Prebuilt wheel install failed. This can happen if there's no"
    Write-Warn "prebuilt wheel for your exact Python version. Options:"
    Write-Warn "  1. Try a different Python version (3.10-3.12 have the best wheel coverage)"
    Write-Warn "  2. Enable Windows long paths and build from source instead -- see README.md"
    Write-Warn "     'Local LLM planner backend' section for the exact commands."
    exit 1
}
Write-Ok "llama-cpp-python installed"

# -- 4. Verify the import actually works -------------------------------------
Write-Step "Verifying llama_cpp imports correctly"
python -c "import llama_cpp; print('llama_cpp', llama_cpp.__version__)"
if ($LASTEXITCODE -ne 0) {
    Write-Warn "llama_cpp installed but failed to import -- see the error above."
    exit 1
}
Write-Ok "Import verified"

# -- 5. Remind about the model file + .env -----------------------------------
Write-Step "Next steps"
Write-Host "    1. Download a GGUF model (1-4B params, Q4/Q5 quantized recommended)"
Write-Host "       from a model repository you trust, e.g. Hugging Face."
Write-Host "    2. Save it somewhere under this project, e.g. models\your-model.gguf"
Write-Host "    3. In .env, set:"
Write-Host "           AURA_PLANNER_BACKEND=local_llm"
Write-Host "           AURA_LOCAL_LLM_MODEL_PATH=<full path to your .gguf file>"
Write-Host "    4. Verify before running a real test:"
Write-Host "           python -c ""from aura.cli.preflight import check_planner_backend_available; print(check_planner_backend_available())"""
Write-Host "       Should print (True, None)."
