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
- **Zero cloud reliance** — no screenshots, requirements, or business data ever leave the machine; the planner has no network-capable code path at all (see decisions.md D-018)

---

## Requirements

| Requirement | Notes |
|---|---|
| Windows 10/11 | Real screenshot/click automation needs a visible, unlocked desktop |
| Python 3.10+ | https://python.org — check "Add to PATH" during install |
| [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) | Separate binary, not a pip package — AURA's vision pipeline shells out to it |
| Playwright Chromium | Run `playwright install chromium` once after `pip install -e .` — Phase C's primary browser-target interaction path launches a real local headless Chromium; this is a one-time local binary install, same category as Tesseract, no cloud dependency |
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

## Autonomy modes: fully autonomous vs. human-in-the-loop

AURA has two genuinely different modes now, not just "pauses more or less."

### Mode A — fully autonomous, zero human input

**`aura explore <url>`** is the purest form: point it at a URL with no spec and no instructions at all, and it behaves like a QA tester who's never seen the page before — navigates, scrolls the whole thing checking for broken/error content, finds every clickable-looking element via OCR (nav, hero, footer, *and* body — not just nav/footer like `--ui-audit`), clicks each one, checks whether anything visibly changed, comes back, and moves to the next one. No approval checkpoints, ever.

```powershell
# Zero instructions -- just explore and report back
aura explore https://example.com

# Same, but also flag whether a specific thing looks covered
aura explore https://example.com --prompt "check the submit button works"

# Cap how many elements it test-clicks (default 25)
aura explore https://example.com --max-elements 40

# Skip the full-page scroll/error scan, just do the click sweep
aura explore https://example.com --no-scroll-scan

# Also run a real HTTP-level link check (off by default -- opt in explicitly)
aura explore https://example.com --check-links

# Same, but restrict the link check to just the footer
aura explore https://example.com --check-links --link-scope footer
```

The `--prompt` check is a **keyword heuristic, not language understanding** — it looks for on-screen text overlapping words from your prompt among everything it saw while exploring, and says so explicitly in the output either way. Treat it as "here's what I noticed that might be relevant," not a verdict.

`aura execute --yes` / `--autonomous` (the two flags do the same thing) is the other flavor of Mode A: fully unattended execution of a **written spec or `--prompt`-described flow**, as before — no spec-approval prompt, no low-confidence pause, no heal accept/reject. Use `explore` when you have no spec at all; use `execute --autonomous` when you do.

### Mode B — human-in-the-loop, `aura execute --interactive`

This is a different thing from "pauses to ask permission." In interactive mode, **AURA never acts on the target at all** — it opens `--url` (if given), then polls the live screen in a loop until it detects that *you* performed the described action, then verifies and reports. It does not time out by default (`--timeout 0`, the default, means wait indefinitely — matching "the execution should not stop until the human clicks").

```powershell
# Opens example.com, then waits (no timeout) for you to click Submit yourself
aura execute --interactive --url https://example.com --prompt "click the submit button"

# Same, but give up after 2 minutes if nothing happens
aura execute --interactive --url https://example.com --prompt "click the submit button" --timeout 120
```

Under the hood this is a new step type, `WAIT_FOR_HUMAN_ACTION` (`orchestrator/schemas.py`), executed by `RunEngine.run_spec()`'s polling branch (`orchestrator/run_engine.py`) — it re-screenshots every `human_action_poll_interval_seconds` (default 2s, `config/settings.py`) and compares against the baseline, so it reacts as soon as you act rather than on a fixed timer.

### The gap this closes (and what's still `--yes`-shaped elsewhere)

Previously, `execute_prompt()` hardcoded `auto_approve=True` and `--yes` set it for every other path too — tracing the flow, `confirm_spec_approval`, `low_confidence_prompt`, and `confirm_heal_accept` were only ever called `if not auto_approve`, so a `--prompt` or `--yes` run genuinely never paused, start to finish. That's still true and is the *correct* behavior for Mode A — the actual gap wasn't "it doesn't wait for a human," it was that **AURA had no way to act like a professional QA tester with no explicit instructions at all** (give it one step, it does one step) and no way to **deliberately hand control to a human mid-run and wait for them**, rather than just skip a confirmation prompt. `aura explore` and `aura execute --interactive` are exactly those two missing pieces. A plain `aura execute <spec>` (no `--yes`/`--autonomous`/`--interactive`) still uses the original spec-approval / low-confidence / heal-accept checkpoints exactly as before — nothing about that path changed.

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
aura execute <test_id_or_path> --autonomous                      # same as --yes -- explicit name for "no human input at all"
aura execute --interactive --url https://example.com --prompt "click the submit button"              # human-in-the-loop: waits for you, no timeout
aura execute --interactive --url https://example.com --prompt "click the submit button" --timeout 120 # same, but gives up after 2 minutes
aura execute --all --junit-out results.xml                       # CI mode: JUnit XML output, one <testsuite> per spec, exits 1 if anything failed
aura execute --all --include-quarantined                         # also run specs quarantined via `aura skills quarantine` (skipped by default)
aura execute <test_id_or_path> --browser firefox                 # Phase I1: run against Firefox instead of the default Chromium
aura execute <test_id_or_path> --record-video                    # Phase I2: record a real video (DOM path) or a step-boundary slideshow (OS/pixel path)
aura execute --all --parallel 4 --yes                            # Phase J: run up to 4 requirement docs concurrently (ThreadPoolExecutor). Default is 1 (sequential, unchanged behavior).
```

**`--parallel N` (Phase J)** only applies with `--all`. It's intended for unattended batch runs (`--yes`/`--autonomous`) against independent, non-conflicting targets — each worker thread gets its own `RunEngine`/`SkillStore`/`RunMemoryStore` instance, so there's no shared-state correctness risk, but per-spec console output from different threads can interleave, and two workers both driving a real browser on the same physical machine/display will contend for that one screen the same way any two manually-run instances would. `--parallel 1` (the default) preserves the exact original sequential behavior and ordering.

`<test_id_or_path>` can be:
- A direct file path: `aura execute requirements_input\login_flow.md`
- A test ID that fuzzy-matches a filename or file contents under `requirements_input\`: `aura execute TC-LOGIN-FLOW-001`

**Modes:**
- **Interactive-by-default (no flags)** — prompts you to approve the generated spec before it runs, asks for confirmation on low-confidence vision actions, and asks you to accept/reject self-healed steps as they happen. (Not to be confused with the `--interactive` *flag* below, which is a different, stronger mode — see "Autonomy modes" above.)
- **`--yes` / `--autonomous` (unattended)** — auto-approves all of the above. Use this for scheduled/CI runs where no one is watching. Both flags do the same thing; `--autonomous` exists as an explicit, self-documenting name.
- **`--prompt` (unattended by design)** — describe what to test in plain English instead of writing a spec file. No approval checkpoint, since there's no step list to review ahead of time.
- **`--interactive` (human-in-the-loop)** — AURA doesn't act at all; it opens `--url` and waits, polling the screen, until you perform the `--prompt`-described action yourself, then verifies. No timeout by default. See "Autonomy modes" above for the full explanation and the `WAIT_FOR_HUMAN_ACTION` step type behind it.

**CI/CD (`--junit-out <path>`):** writes a standard JUnit XML report — with `--all`, every spec becomes its own `<testsuite>` in one combined file. Exit codes: `0` if every spec run PASSED or PASSED_WITH_HEALING, `1` if anything FAILED/ESCALATED or the invocation couldn't start a run at all. `--interactive` mode has no exit-code contract (it's a live human-wait flow, not something a CI pipeline runs).

**Visual regression (opt-in, per step):** a `TestStep` can set `visual_baseline_key` to get a real pixel-diff comparison (not just OCR text matching) against a persisted baseline image, in addition to whatever else the step already checks. First run for a given key creates the baseline; later runs compare against it and fail if more than `visual_diff_tolerance` (default 2%) of pixels differ. Baselines live in `runtime\baselines\` and, unlike screenshots, **are meant to be committed to the repo** — a baseline that isn't shared across machines/CI defeats the point. On a failing comparison, an amplified diff image is saved alongside the baseline and shown in the HTML report.

**Cross-browser (`--browser chromium|firefox|webkit`, Phase I1):** which Playwright engine `runtime/hooks/browser.py` launches for DOM-path targets. Defaults to `chromium` (unchanged behavior if you never pass this). An invalid value exits 1 with a clear message rather than a stack trace. Note: Firefox/WebKit require their own Playwright browser binaries to be installed (`playwright install firefox webkit`) — if the one you pick isn't installed, you'll get a clear `NoDisplayError`-style message, not a crash.

**Video recording (`--record-video`, Phase I2):** off by default (video files are meaningfully larger than screenshots). When on: if the run uses the DOM/Playwright path, you get a real, native video file (`runtime\videos\<hash>.webm`) referenced in the report under `report_paths["video"]`. If the run uses the OS/pixel fallback path instead (native desktop targets with no live accessibility tree), you get an honestly-labeled step-boundary **slideshow** manifest (`runtime\videos\slideshow_<run_id>\manifest.json`, `report_paths["video_slideshow"]`) — a JSON list of each step's already-captured screenshot in order, explicitly *not* claimed to be continuous video.

### `aura explore` (new)

Fully autonomous, zero-instruction exploration — the other half of "Autonomy modes" above. No spec, no `--prompt` required:

```powershell
aura explore https://example.com                                        # navigate, scroll-scan, click everything, report
aura explore https://example.com --prompt "check the submit button works"  # same, plus a best-effort check for something specific
aura explore https://example.com --max-elements 40                      # raise the click cap (default 25)
aura explore https://example.com --no-scroll-scan                       # skip the full-page error scan, just click things
aura explore https://example.com --check-links                          # also run a real HTTP-level link check (off by default)
aura explore https://example.com --check-links --link-scope footer      # restrict that link check to just <footer> links
aura explore https://example.com --check-links --link-scope nav         # restrict it to just <nav> links
```

Generalizes the same click-and-diff engine `--ui-audit` uses (`orchestrator/ui_audit_runner.py`) from "nav + footer only" to every interactive-looking element on the page (nav, hero, footer, body). Output is a terminal summary plus a JSON report under `reports\explore_<run_id>\report.json` — this mode doesn't (yet) produce an HTML report, since `render_html()` expects a full spec-driven run on disk and `explore` deliberately has neither a spec nor a `RunEngine` pass.

**Real HTTP link check (`agents/capability/link_checker.py`) — opt-in via `--check-links`:** by default `explore` only does the OCR click-and-diff sweep above; pass `--check-links` to *additionally* fetch the page's raw HTML and issue a real HTTP status check against every navigable `<a href>` link. `--link-scope` (`all` by default, or `footer`/`nav`) only has any effect when `--check-links` is also passed — it's not a separate way to trigger the check. This is opt-in rather than automatic because a live HTTP request against every link on the page is a meaningfully different (and heavier/network-dependent) check than the OCR sweep, and shouldn't run silently on a plain `aura explore` call. Two things worth knowing about how this works:
- **Redirects are shown, not hidden.** A link that 301/302-redirects somewhere else still counts as "working" (its final destination is what matters), but the redirect chain — every hop's status code and target — is reported explicitly rather than silently landing on the final URL and looking identical to a direct hit.
- **Client-rendered (React/Next.js/Angular) pages have a real, disclosed coverage limit.** AURA's link check reads the raw HTML returned by a plain HTTP request — the same "no DOM automation" posture as the rest of the vision pipeline — so if a page's links are injected by JavaScript after load rather than present in the server-delivered HTML, they genuinely won't be found. When this happens, the report says so explicitly (`client_rendered_suspected: true` in the JSON output, plus a plain-English explanation in the terminal) instead of looking like a clean pass with nothing to check. Actually checking JS-injected links would require a headless-browser render step (e.g. Playwright), which AURA does not currently do — this is flagged as a known limitation, not silently worked around.

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
aura skills quarantine TC-LOGIN-FLOW-001 --reason "intermittent timing failure"  # mark a test flaky/unreliable
aura skills quarantined                                 # list everything currently quarantined
aura skills unquarantine TC-LOGIN-FLOW-001              # clear a quarantine entry
```

`skills diff` is useful for reviewing what the self-healer learned since your last checkpoint before trusting it in an unattended/CI run — shows skills added, removed, and changed (confidence, applied count, proposed fix).

**Quarantine (Phase H2) is opt-in only.** Nothing in AURA quarantines a test automatically — the API's `/api/v1/test-runs/analytics/flaky` endpoint (and the web dashboard's Analytics view) only ever *surfaces candidates* based on real pass/fail history; a human decides whether to act on that by running `aura skills quarantine <test_id>`. Once quarantined, `aura execute --all` skips that spec by default (printing a visible `Skipped -- ... is quarantined` message) — pass `--include-quarantined` to run it anyway without first unquarantining it.

---

## Configuration (.env)

All settings live in `config\settings.py` and can be overridden via a `.env` file in `aura_build\` (prefix `AURA_`) or environment variables. None of these require a network call — everything defaults to fully offline behavior.

| Variable | Default | Purpose |
|---|---|---|
| `AURA_TESSERACT_CMD` | *(none — relies on PATH)* | Full path to `tesseract.exe`; set this on Windows to avoid PATH issues |
| `AURA_VISION_CONFIDENCE_THRESHOLD` | `0.75` | Minimum OCR match confidence before a click/assertion is trusted without asking |
| `AURA_COMPRESSION_MODE` | `max` | `max` \| `balanced` \| `off` — resource usage philosophy (no fixed hardware baseline assumed) |
| `AURA_PLANNER_BACKEND` | `heuristic` | `heuristic` \| `local_llm` — see [Local LLM backend](#local-llm-planner-backend-optional-offline) below |
| `AURA_LOCAL_LLM_MODEL_PATH` | *(none)* | Path to a local `.gguf` model file, required if `planner_backend=local_llm` |
| `AURA_PROJECT_ROOT` | repo root | Override where AURA looks for/writes `runtime\`, `reports\`, etc. |
| `AURA_ENV` | *(none)* | Environment profile name (e.g. `staging`, `prod`) — see [Environment profiles](#environment-profiles-devstagingprod) below |
| `AURA_CAPABILITY_ADAPTERS_ENABLED` | `true` | Hard kill switch for **all** capability adapters (API/DB/Email/File/Excel/PDF/Cloud/Workflow/SharePoint/Automation Anywhere) at once, for a fully air-gapped deployment. Vision/Playwright/Planner are unaffected — this only gates the intentionally network-or-filesystem-facing adapters. |
| `AURA_ALLOWED_CAPABILITY_HOSTS` | *(unset = no restriction)* | Comma-separated host allowlist restricting API/webhook/cloud adapters to known targets. Enforced at `orchestrator/capability_router.py`'s single chokepoint. Note: `azure_adapter`/`gcp_adapter` use SDK default-credential auth with no explicit host param, so they can't be host-allowlisted yet — the kill switch above still covers them. |

### Environment profiles (dev/staging/prod)

If you test against more than one environment (e.g. staging vs. prod URLs/credentials), you don't need separate copies of the whole `.env` file:

```powershell
# One-time: scaffold a starting profile file with every base-.env key as a commented-out placeholder
aura init --env staging

# Edit .env.staging, uncomment/set only the keys that differ from base .env

# Use it for a single command...
aura --env staging execute --all

# ...or set it once for a whole shell session
$env:AURA_ENV = "staging"
aura execute --all
```

`.env` always loads first; `.env.<profile>` (if present) loads second and only overrides the specific keys it sets — everything else still comes from the base file. A profile name with no matching `.env.<profile>` file isn't an error, it just means nothing gets overridden (check `aura --env typo execute ...`'s behavior is identical to no `--env` at all if you're debugging a typo).

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

## Backend capability adapters (beyond the browser/desktop UI)

Beyond vision-based UI testing, AURA can validate non-UI systems directly as part of a test spec, via a `capability_check` step type instead of a `visual_click`/`type_text` step. This is useful for the "click a button in the UI, then confirm the row actually landed in the database" style of test.

| Adapter | Backs | Module |
|---|---|---|
| API | REST/GraphQL calls, status/schema/payload assertions | `agents/capability/api_adapter.py` (`httpx`) |
| Database | Read-only SQL queries, row/type/constraint checks | `agents/capability/db_adapter.py` (`sqlalchemy`) — read-only by design |
| Email | Send-and-poll verification over IMAP/SMTP | `agents/capability/email_adapter.py` |
| File | Local filesystem or SFTP checks (existence, hash, stat) | `agents/capability/file_adapter.py` (`paramiko` for SFTP) |
| Excel | Cell values, formulas, formatting | `agents/capability/excel_adapter.py` (`openpyxl`) |
| PDF | Text/page-count extraction | `agents/capability/pdf_adapter.py` (`pypdf`) |
| Cloud | S3 object existence (detect-only) | `agents/capability/cloud_adapter.py` (`boto3`) — currently only implements the `s3_object_exists` action; other `action` values are accepted but silently fall through to the same check, so don't rely on anything else yet |
| Workflow | Generic webhook/CI trigger (fire-and-forget) | `agents/capability/workflow_adapter.py` (`httpx`) |

A `TestStep` with `action: capability_check` carries `capability_type`, `target`, `capability_params`, and `expected`; the orchestrator routes it through `orchestrator/capability_router.py` to the matching adapter and, on failure, attempts a cross-modal self-heal (`agents/planner/cross_modal_diagnoser.py`) before escalating — the same self-healing philosophy as the UI path, applied to API/DB schema drift.

This surface is fully unit-tested (`tests/test_capabilities.py`, `tests/test_16_categories_verification.py`, per-adapter test files) but is exercised through the CLI/`RunEngine` path, not yet through the REST API below.

---

## Web dashboard & REST API (preview — not production-ready)

`api/main.py` is a FastAPI service (`AURA Universal QA Platform`) with a small web dashboard (`webui/`) and REST endpoints for triggering and inspecting runs, separate from the CLI.

- **Login exists.** `POST /api/v1/auth/login` (username/password) and `POST /api/v1/auth/signup` both issue a real JWT (`api/user_store.py`, PBKDF2-hashed passwords); Google/GitHub OAuth is also available under `/api/v1/auth/oauth/{provider}/login` when the corresponding client ID/secret env vars are set. Every other endpoint requires that JWT (role-gated: `admin`/`executor`/`viewer`).
- **`POST /api/v1/test-runs` actually executes.** A `mode: "guided"` spec runs through the real `RunEngine.run_spec()`; `mode: "autonomous"` runs through the Planner (`RunEngine.run()`). Setting `"full_exploration": true` on an autonomous request instead routes to the same zero-instruction engine `aura explore` uses (`orchestrator/ui_audit_runner.run_exploration`) — same opt-in link-check fields as the CLI's `--check-links`/`--link-scope`:
  ```json
  {
    "mode": "autonomous",
    "target": "https://example.com",
    "full_exploration": true,
    "max_elements": 25,
    "check_links": true,
    "link_scope": "footer"
  }
  ```
  `check_links` defaults to `false` (the real HTTP link check does not run unless explicitly requested) and `link_scope` (`"all"` | `"footer"` | `"nav"`) only has any effect when `check_links` is `true`.
- **Trend analytics & flaky-test detection (Phase H1/H2).** `GET /api/v1/test-runs/analytics/tests/{test_key}` returns per-run history plus a cumulative pass-rate series for one test (`test_key` is whatever `test_id`/`test_name` the run was submitted with — untracked one-off runs with neither field are excluded). `GET /api/v1/test-runs/analytics/tests` lists every tracked `test_key` for the caller's tenant; `GET /api/v1/test-runs/analytics/flaky?min_runs=3&min_transitions=2` surfaces tests whose pass/fail outcome has flip-flopped at least `min_transitions` times across at least `min_runs` completed runs — a candidate list only, never an automatic action. The web dashboard's **Analytics** view renders both. Pair a flaky candidate with `aura skills quarantine <test_id>` (see `aura skills` above) to actually skip it in future `--all` runs.
- **Fine-grained access within a tenant, opt-in (Phase K).** By default, any spec is accessible to any authenticated member of its tenant (role permitting) — nothing about this changes unless you use it. To restrict a user to specific projects: (1) tag a spec by setting `"project_tag": "finance"` in its submitted JSON; (2) as an admin, call `PUT /api/v1/users/{username}/project-tags` with `{"allowed_project_tags": ["finance", "hr"]}` — that user can then only create/view runs for specs tagged with one of those values (plus any untagged spec, always). Send `{"allowed_project_tags": []}` (or omit the key) to clear a restriction back to unrestricted. Admins always bypass this regardless of tags. A user's restriction takes effect on their *next* login — there is no live token revocation in this system (a pre-existing limitation, not specific to this feature), so a token already issued keeps whatever access it had at issuance.
- **No `aura serve` command yet.** Start it manually:
  ```powershell
  pip install -e ".[dev]"
  uvicorn api.main:app --reload
  ```
  Then visit `http://127.0.0.1:8000/` for the dashboard shell, or `http://127.0.0.1:8000/docs` for the interactive API docs.
- Run state is **in-memory only** — restarting the process loses all run history.

Treat this as an early preview of the direction (see `Roadmap.md` Phase 17), not a supported feature, until the run-execution wiring and a login endpoint land.

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
python -m pytest -q      # full test suite (205 tests as of this doc revision)
ruff check .              # lint
```

---

## Project structure

```
aura_build/
├── install.bat           # One-click Windows setup (wraps scripts/setup_windows.ps1)
├── run.bat               # Launches aura without manually activating .venv
├── models/               # Drop a .gguf file here for the local LLM backend -- auto-detected, no .env editing
├── agents/            # Planner, Vision, DataSynth sub-agents, plus agents/capability/ (API/DB/Email/File/Excel/PDF/Cloud/Workflow adapters, see "Backend capability adapters" above)
├── orchestrator/       # Kernel (tool dispatch + audit trail), run engine, healing loop, skill store, scheduler, autoscan, capability router
├── runtime/hooks/       # Real screenshot capture (mss), interaction (pyautogui), and browser navigation
├── reports/            # HTML/PDF report rendering + Jinja2 templates
├── aura/cli/            # CLI command implementations
├── api/                 # FastAPI service layer -- preview only, see "Web dashboard & REST API" above before relying on it
├── webui/               # Static web dashboard served by api/main.py
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
- [Roadmap.md](./Roadmap.md) — capability-adapter/service-layer phases (13–19), including known gaps in the API/service layer
- [progress.md](./progress.md) — dated build log, newest entry first
