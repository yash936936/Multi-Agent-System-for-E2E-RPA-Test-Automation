# AURA — Autonomous Unified RPA Agent

Offline, vision-first, self-healing QA test automation. AURA "looks" at your
application through screenshots and reasons about what it sees — the way a
human tester would — instead of relying on brittle DOM selectors/element IDs
that break with every minor UI change.

This README is the practical operating guide: install, commands, configuration,
and two supported ways to deploy it on Windows. For architecture/design docs,
see the [Docs](#docs) section at the bottom.

---

## Table of contents

- [What it does](#what-it-does)
- [Requirements](#requirements)
- [Option 1 — Local CLI (recommended to start)](#option-1--local-cli-recommended-to-start)
- [Quick start](#quick-start)
- [Full command reference](#full-command-reference)
  - [`aura init`](#aura-init)
  - [`aura execute`](#aura-execute)
  - [`aura schedule`](#aura-schedule)
  - [`aura skills`](#aura-skills)
- [Configuration (.env)](#configuration-env)
- [Local LLM planner backend (optional, offline)](#local-llm-planner-backend-optional-offline)
- [Reports & output locations](#reports--output-locations)
- [Option 2 — Standalone Windows .exe (PyInstaller)](#option-2--standalone-windows-exe-pyinstaller)
- [Troubleshooting (Windows)](#troubleshooting-windows)
- [Running the test suite](#running-the-test-suite)
- [Project structure](#project-structure)
- [Docs](#docs)

---

## What it does

- **Planner** — turns a plain-English requirement doc (Markdown) into a structured, steppable test spec
- **Vision Execution Core** — takes real screenshots, locates elements via OCR, clicks/types like a human would
- **Synthetic Data Generator** — produces realistic + edge-case test data (usernames, emails, boundary values, etc.)
- **Self-healing loop** — when a step fails, diagnoses why, tries a fix, and remembers it as a reusable "skill" so the same failure doesn't need re-diagnosing next time
- **Guardrails** — stops runaway retry loops instead of hammering a broken step forever
- **Zero cloud reliance** — no screenshots, requirements, or business data ever leave the machine unless you explicitly opt into the reference `AnthropicBackend` path (off by default)

---

## Requirements

| Requirement | Notes |
|---|---|
| Windows 10/11 | Real screenshot/click automation needs a visible, unlocked desktop |
| Python 3.10+ | https://python.org — check "Add to PATH" during install |
| [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) | Separate binary, not a pip package — AURA's vision pipeline shells out to it |
| A display session | The target app under test must be visible on screen while a run executes (see [Troubleshooting](#troubleshooting-windows) for locked-screen/RDP notes) |

---

## Option 1 — Local CLI (recommended to start)

Best for: active development, exploratory testing, fast iteration when a test spec or requirement doc isn't stable yet. Every QA engineer runs it on their own workstation, on demand, no shared infrastructure required.

### Install

**One-click (recommended):** double-click `install.bat` in the project root (or run it from a terminal). Sets up the venv, installs AURA, detects Tesseract, and reports whether a bundled local LLM model was found — no PowerShell execution-policy flags to fight with.

Once done, run tests with `run.bat` instead of activating the venv yourself every time:
```powershell
run.bat execute --url https://example.com --prompt "Describe what to test"
```

**Automated PowerShell (equivalent, if you prefer running the script directly):**

```powershell
cd aura_build
.\scripts\setup_windows.ps1
```

This creates the venv, installs AURA, auto-detects Tesseract if it's in a common install location and writes `.env` for you, then runs the test suite to confirm everything works. Safe to re-run.

**Manual (if you'd rather do it step by step, or the script doesn't fit your setup):**

```powershell
cd aura_build
python -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install -e ".[dev]"
```

### Point AURA at your Tesseract install

Create a `.env` file in `aura_build\` (same folder as `pyproject.toml`):

```
AURA_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

(Adjust the path if you installed Tesseract somewhere else. This sidesteps PATH issues entirely — no need to edit your system PATH or fight different shells.)

### Verify it's working

```powershell
python -m pytest -q
aura --help
```

If `aura --help` doesn't work directly, use `python -m aura.main --help` instead — both are equivalent, `aura` is just a shorter alias installed by `pip install -e .`.

---

## Quick start

```powershell
# 1. First-time setup (target app type, scheduling preference, compression policy)
aura init

# 2. Run a single requirement doc
aura execute requirements_input\example_login_flow.md

# 3. Run every requirement doc in requirements_input\ in one go
aura execute --all

# 4. Open the generated report
start reports\run_<run_id>\report.html
```

---

## Full command reference

### `aura init`

First-time setup wizard: target app type, scheduled-run opt-in + local notification channel, compression policy. Writes to `config\local_config.json` (gitignored) so later commands don't re-prompt.

```powershell
aura init            # interactive wizard
aura init --yes       # skip prompts, write defaults
```

### `aura execute`

Runs a test: spec generation → approval checkpoint → live vision-execution loop → report.

```powershell
aura execute <test_id_or_path>              # run one requirement doc
aura execute --all                          # run every .md file in requirements_input\
aura execute <test_id_or_path> --yes        # auto-approve everything (unattended/CI mode)
aura execute <test_id_or_path> --refresh-data   # force-regenerate synthetic data instead of reusing the cache
aura execute <test_id_or_path> --pdf        # also export the report as PDF (needs the 'report' extra, see below)
aura execute --url https://example.com/login                     # no spec needed: auto smoke test against a live URL
aura execute <test_id_or_path> --url https://example.com/login   # navigate there first, then run the spec's steps
aura execute --prompt "Check the pricing page and verify the Sign Up button works"   # plain-English test, fully unattended
aura execute --url https://example.com --scroll-test             # after the main run, scroll the full page checking for broken/error content
```

`<test_id_or_path>` can be:
- A direct file path: `aura execute requirements_input\login_flow.md`
- A test ID that fuzzy-matches a filename or file contents under `requirements_input\`: `aura execute TC-LOGIN-FLOW-001`

**Modes:**
- **Interactive (default)** — prompts you to approve the generated spec before it runs, asks for confirmation on low-confidence vision actions, and asks you to accept/reject self-healed steps as they happen.
- **`--yes` (unattended)** — auto-approves all of the above. Use this for scheduled/CI runs where no one is watching.
- **`--prompt` (unattended by design)** — describe what to test in plain English instead of writing a spec file. No approval checkpoint, since there's no step list to review ahead of time.

### Testing a live website

AURA is vision-first, not DOM-based — it screenshots whatever's on screen and reads it with OCR, so a website in a browser window is tested exactly the same way as the bundled Tkinter demo app. As of this release, AURA can open the browser itself instead of requiring someone to pre-position it at the right page:

```powershell
# Fastest path: point AURA at a URL, no requirement doc needed.
# Opens the URL in your default browser, waits for it to settle, done.
aura execute --url https://example.com/login

# Write real steps/assertions in a requirement doc, and let --url handle
# getting the browser to the starting page:
aura execute requirements_input\example_login_flow.md --url https://example.com/login
```

Under the hood this adds a new `navigate_url` step type (`orchestrator/schemas.py::ActionType.NAVIGATE_URL`), dispatched by `runtime/hooks/browser.py` (stdlib `webbrowser`, no Selenium/Playwright — stays consistent with AURA's screen-reading architecture, zero new dependencies). `--url` works by prepending `Given: navigate to <url>` ahead of your requirement text, so you can also just write that line directly in a requirement doc instead of passing the flag:

```markdown
# Login Flow — example.com

Given: navigate to https://example.com/login

The user clicks the "Sign In" button, top-right.
The user enters a username into the Email field.
...
```

The Planner's heuristic backend recognizes `navigate to <url>`, `go to <url>`, `open <url>`, and `browser is open at <url>` phrasing anywhere in the doc and automatically inserts a `navigate_url` step as step 1, renumbering the rest — no manual wiring needed per spec.

**Known limitation:** the settle time after navigation is a fixed wait (default 2.5s), not a real "page fully loaded" signal — AURA has no DOM/network hook to wait on. Slow-loading pages may need an extra `The user waits for the page to load.` step (mapped to a no-op wait) or a longer implicit delay.

### Testing with a plain-English prompt

`--prompt` skips writing a spec file entirely — describe what to test in plain language and AURA generates and runs the steps unattended (no approval checkpoint, since there's no step list to review beforehand):

```powershell
aura execute --url https://example.com --prompt "Verify the pricing page loads and the Sign Up button is visible"
```

Prompt quality matters: name concrete, visible elements (button labels, headings) the same way you'd describe them to someone looking at the screen. With the default heuristic backend, prompts work best when they closely match the `navigate to / click / type into / verify` phrasing shown above. The local LLM backend (below) handles looser, more natural phrasing.

### Autonomous full-page scan

`--scroll-test` adds an unattended pass after the main run: AURA scrolls the page from top to bottom, screenshotting and OCR-checking each view for common broken-page indicators (404/500/502/503, "access denied", "something went wrong", etc.), stopping once scrolling stops changing the page or after a 25-scroll safety cap:

```powershell
aura execute --url https://example.com --scroll-test
```

This is a generic health check, not a substitute for real assertions about your page's content — combine it with `--prompt` or a written spec for anything specific.

### `aura schedule`

Manage recurring unattended runs (in-process scheduler; see [Option 2 notes below](#windows-task-scheduler-alternative) for a Windows-native alternative).

```powershell
aura schedule add "0 2 * * *" TC-LOGIN-FLOW-001   # cron expression + test id
aura schedule list
aura schedule remove <job_id>
```

Cron format is standard 5-field (`minute hour day month weekday`). Example above runs nightly at 2 AM.

### `aura skills`

Inspect, export, import, or diff the local self-healing skill library (what AURA has learned from past failures).

```powershell
aura skills list                                       # show all learned skills
aura skills list --app my_target_app                    # filter by app
aura skills export --out skills_backup.json             # snapshot to a file
aura skills export --app my_target_app --out pack.json  # snapshot for one app only
aura skills import --out pack.json                      # load skills from a file
aura skills import --out pack.json --app my_target_app  # tag imported skills with an app id
aura skills diff --before old_export.json --after new_export.json   # what changed between two snapshots
```

`skills diff` is useful for reviewing what the self-healer learned since your last checkpoint before trusting it in an unattended/CI run — shows skills added, removed, and changed (confidence, applied count, proposed fix).

---

## Configuration (.env)

All settings live in `config\settings.py` and can be overridden via a `.env` file in `aura_build\` (prefix `AURA_`) or environment variables. None of these require a network call — everything defaults to fully offline behavior.

| Variable | Default | Purpose |
|---|---|---|
| `AURA_TESSERACT_CMD` | *(none — relies on PATH)* | Full path to `tesseract.exe`; set this on Windows to avoid PATH issues |
| `AURA_VISION_CONFIDENCE_THRESHOLD` | `0.75` | Minimum OCR match confidence before a click/assertion is trusted without asking |
| `AURA_COMPRESSION_MODE` | `max` | `max` \| `balanced` \| `off` — resource usage philosophy (no fixed hardware baseline assumed) |
| `AURA_ALLOW_NETWORK_CALLS` | `false` | Must be explicitly set `true` to use the reference cloud (`AnthropicBackend`) planner path — leave `false` to guarantee zero data egress |
| `AURA_PLANNER_BACKEND` | `heuristic` | `heuristic` \| `local_llm` \| `anthropic` — see [Local LLM backend](#local-llm-planner-backend-optional-offline) below |
| `AURA_LOCAL_LLM_MODEL_PATH` | *(none)* | Path to a local `.gguf` model file, required if `planner_backend=local_llm` |
| `AURA_PROJECT_ROOT` | repo root | Override where AURA looks for/writes `runtime\`, `reports\`, etc. |

Example `.env`:
```
AURA_TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
AURA_VISION_CONFIDENCE_THRESHOLD=0.8
```

---

## Local LLM planner backend (optional, offline)

By default, AURA parses requirement docs with a deterministic heuristic parser — zero dependencies, but can be brittle against loosely-structured real-world requirement text. For better natural-language understanding while staying fully offline, you can switch to a small local LLM:

```powershell
pip install -e ".[llm]"
```

⚠️ **Windows note:** the command above builds `llama-cpp-python` from source, which vendors llama.cpp's full source tree (including a web UI with deeply nested component paths). This can fail with an error like:
```
OSError: [Errno 2] No such file or directory: '...\vendor\llama.cpp\tools\ui\src\lib\components\...\SomeDeeplyNested.svelte'
```
That's Windows' 260-character `MAX_PATH` limit being exceeded during extraction, not a real problem with your setup. Fastest fix — use the install helper script, which installs a prebuilt CPU wheel instead of building from source:
```powershell
.\scripts\install_llm_backend.ps1
```
Or do it manually / troubleshoot further:

1. **Prebuilt wheel (what the script above does):**
   ```powershell
   pip uninstall llama-cpp-python -y
   pip install llama-cpp-python --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
   ```
2. **Or enable long path support** (admin PowerShell, then reboot, then retry `pip install -e ".[llm]"`):
   ```powershell
   New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
   git config --system core.longpaths true
   ```

Download any small instruction-tuned model in **GGUF format** from a model repository you trust (1–4B parameters, Q4/Q5 quantized is plenty for this structured-extraction task; larger, e.g. 7B, works too if your hardware supports it).

**Zero-config path:** drop the `.gguf` file into `models\` in the project root. AURA auto-detects it on startup and switches to the local LLM backend automatically — no `.env` editing needed:
```powershell
mkdir models
move C:\Downloads\qwen2.5-3b-instruct-q4_k_m.gguf models\
aura execute --url https://example.com --prompt "..."
```
If multiple `.gguf` files are present, the alphabetically first one is used. To pin a specific model or path explicitly, set `.env`:

```
AURA_PLANNER_BACKEND=local_llm
AURA_LOCAL_LLM_MODEL_PATH=<REPLACE_WITH_YOUR_ACTUAL_.gguf_FILE_PATH>
```

⚠️ **Do not copy-paste the line above as-is** — `<REPLACE_WITH_YOUR_ACTUAL_.gguf_FILE_PATH>` is a placeholder, not a real path. If you leave `AURA_PLANNER_BACKEND=local_llm` set without pointing `AURA_LOCAL_LLM_MODEL_PATH` at a `.gguf` file that actually exists on disk, `aura execute` will fail with `LocalLLMModelNotFoundError` on every run. If you don't want the local LLM backend, leave `AURA_PLANNER_BACKEND` unset (or set it to `heuristic`) — that's the zero-dependency default and what most setups should use.

No model is downloaded automatically — you control exactly what model runs on your machine, which matters if you're in a compliance-sensitive environment. Runs entirely on-device via `llama-cpp-python`; no network call is made at any point.

---

## Reports & output locations

| What | Where |
|---|---|
| HTML/PDF reports | `reports\run_<run_id>\report.html` (and `report.pdf` if `--pdf` was used) |
| Raw JSON results | `reports\run_<run_id>\raw_results.json` |
| Full audit trace (every tool call) | `reports\run_<run_id>\trace.jsonl` |
| Screenshots taken during a run | `runtime\screenshots\run_<run_id>\` |
| Synthetic data cache | `runtime\data_cache\` |
| Learned skills (SQLite) | `orchestrator\skills_store\` |
| Run/resume state (SQLite) | `orchestrator\memory\` |

Every report opens with a plain-English "What this test does" summary at the top, generated from the structured test spec — useful for sharing with non-technical stakeholders.

---

## Option 2 — Standalone Windows .exe (PyInstaller)

Best for: distributing AURA to QA staff who shouldn't have to set up Python/pip/venv themselves — they just run an `.exe`. Same execution model as Option 1 underneath (still needs the target app visible on an unlocked screen); this only changes *how it's installed*, not how it runs.

### Build the .exe

**Automated (recommended):**

```powershell
.\scripts\build_exe.ps1
```

Wraps the exact build command verified below, cleans previous build artifacts, and stages a verification copy in a temp folder with the demo app so you can confirm it actually works before distributing it.

**Manual:**

From an activated venv with the project installed (Option 1 setup):

```powershell
pip install pyinstaller
```

```powershell
pyinstaller --onefile --name aura --console ^
  --add-data "config\tool_registry.yaml;config" ^
  --add-data "reports\templates;reports\templates" ^
  --hidden-import agents.planner.tool ^
  --hidden-import agents.vision.tool ^
  --hidden-import agents.data_synth.tool ^
  aura\main.py
```

This produces `dist\aura.exe`. Every flag above was necessary and verified by actually building and running the packaged binary end-to-end, not assumed — a couple of things were non-obvious enough to call out:

- **`--hidden-import` is required, not optional.** `ToolRegistry` resolves the Planner/Vision/DataSynth agent modules dynamically from string names in `config\tool_registry.yaml` (via `importlib.import_module`). PyInstaller's static analysis can't see string-based imports, so without these three flags the exe launches fine and even shows the spec table, then crashes with `ModuleNotFoundError` the moment it tries to actually run a step.
- **`--add-data` is required for the same reason** — the Jinja2 report template and the tool registry YAML are non-Python data files PyInstaller won't auto-detect.
- **Tesseract is not bundled.** PyInstaller packages your Python code and dependencies, not external binaries. Each machine running `aura.exe` still needs Tesseract installed separately (or ship it alongside and set `AURA_TESSERACT_CMD` to a path next to the exe).
- **Reports/skills/memory persist next to the exe, not in a temp folder.** This was a real bug caught during testing: `settings.project_root` originally resolved via a path that, for a frozen executable, pointed inside PyInstaller's temporary extraction directory — meaning every report the packaged exe wrote would have silently disappeared the moment the process exited. This is now fixed (project_root detects `sys.frozen` and uses the exe's own directory instead) — no action needed on your part, just noting it so you know report output belongs next to wherever you put `aura.exe`, not somewhere hidden.

### Verify the build actually works before distributing it

`build_exe.ps1` assembles a ready-to-distribute folder at `dist\aura_distribution\` containing `aura.exe`, sample requirement docs, the demo app, and your `models\*.gguf` file if present — verify against that folder directly rather than just checking the exe launches:

```powershell
cd dist\aura_distribution
aura.exe execute requirements_input\example_login_flow.md --yes
```

Confirm the run completes with a real report at `dist\aura_distribution\reports\...\report.html`, not an error partway through.

### Distribute it

Zip and hand out `dist\aura_distribution\` as-is:
1. `aura.exe`
2. `models\*.gguf`, if you're shipping the local LLM backend (auto-detected, zero config on the receiving end)
3. A short note: install Tesseract OCR first (link is in `README.txt` inside the folder)

Recipients run `aura.exe execute --url <site> --prompt "..."` from that folder — no Python, pip, or venv required on their machine, and no `.env` editing if a model is bundled.

### Windows Task Scheduler alternative

If you later want *unattended* nightly runs (not just an easy install for on-demand use), pair the exe with Windows Task Scheduler:
1. Log into the target machine via RDP once, then **disconnect** (don't log off) — this keeps the desktop rendered in the background, which AURA's screenshot/OCR hooks need to see.
2. Create a Task Scheduler task set to "Run only when user is logged on," pointed at `aura.exe execute --all --yes`.
3. **Important:** make sure the machine's idle/lock policy won't lock that session — a locked screen blackens the desktop and breaks OCR. A disconnected-but-unlocked RDP session is what you want.

---

## Troubleshooting (Windows)

**`Cannot start: AURA needs Tesseract OCR to read text on screen, and couldn't find it.`**
This is AURA's own pre-run check catching a missing Tesseract install before a run starts (rather than letting it crash mid-step) — follow the steps in the message. If you used `scripts\setup_windows.ps1`, it already tried to auto-detect and configure this for you.

**`tesseract is not installed or it's not in your PATH`**
Install Tesseract from https://github.com/UB-Mannheim/tesseract/wiki, then set `AURA_TESSERACT_CMD` in `.env` to the full path of `tesseract.exe`. This avoids depending on PATH at all, which is more reliable across different shells (PowerShell vs Git Bash vs cmd often have different PATH state).

**`UnicodeEncodeError: 'charmap' codec can't encode character...`**
This was a real bug (fixed) where file writes didn't specify UTF-8 encoding, defaulting to Windows' `cp1252` codepage. If you see this on a version predating the fix, update to the latest build.

**`PermissionError: [WinError 32] The process cannot access the file...`**
Usually a symptom of another process still holding a file open (commonly cascades from the Tesseract error above during test cleanup). If it persists independently, it may indicate an image file handle not being released promptly — check you're on a build with the `agents\vision\locator.py` context-manager fix.

**Vision/click actions do nothing / errors about no display**
The target application must be visible and the screen unlocked while AURA runs — it drives real mouse/keyboard/screenshots, not a headless browser. If running over RDP, disconnect rather than log off (see [Windows Task Scheduler alternative](#windows-task-scheduler-alternative) above) — a locked screen blocks screen capture.

---

## Running the test suite

```powershell
python -m pytest -q      # full test suite
ruff check .              # lint
```

---

## Project structure

```
aura_build/
├── install.bat           # One-click Windows setup (wraps scripts/setup_windows.ps1)
├── run.bat               # Launches aura without manually activating .venv
├── models/               # Drop a .gguf file here for the local LLM backend -- auto-detected, no .env editing
├── agents/            # Planner, Vision, DataSynth sub-agents
├── orchestrator/       # Kernel (tool dispatch + audit trail), run engine, healing loop, skill store, scheduler, autoscan
├── runtime/hooks/       # Real screenshot capture (mss), interaction (pyautogui), and browser navigation
├── reports/            # HTML/PDF report rendering + Jinja2 templates
├── aura/cli/            # CLI command implementations
├── config/              # Settings, tool registry
├── scripts/              # setup_windows.ps1 (Option 1), build_exe.ps1 (Option 2), install_llm_backend.ps1 (optional local LLM planner)
├── requirements_input/  # Your requirement docs (Markdown) live here
├── target_app/          # Bundled demo login app, for trying AURA out risk-free
└── tests/               # Full pytest suite
```

---

## Docs

Design/architecture documents (product requirements, technical architecture, agent workflow, end-user flow):

- [Project Overview](./docs/PROJECT_OVERVIEW.md)
- [PRD](./docs/PRD.md) — goals, personas, requirements, success metrics
- [TRD](./docs/TRD.md) — architecture, tool-calling protocol, data schemas
- [WORKFLOW](./docs/WORKFLOW.md) — agent-to-agent operational sequence
- [APPFLOW](./docs/APPFLOW.md) — end-user experience flow
- [decisions.md](./decisions.md) — running log of every architectural decision and why it was made
- [STATUS.md](./STATUS.md) — current build status, known gaps, closed items
