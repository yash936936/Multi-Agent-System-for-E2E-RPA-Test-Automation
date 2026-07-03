---
type: status
project: AURA
last_updated: 2026-07-03
---

# STATUS

> This file should always reflect the *current* state — overwrite freely, don't accumulate history here (that belongs in `progress.md`).

## Where things stand
AURA is a **feature-complete, runnable MVP**, well past the original 6-phase build plan (`PHASES.md`) — subsequent phases added live-website testing, a comprehensive UI audit mode, and a code bug-detection command.

Core (Phases 1-6): scaffolding, orchestrator kernel, Planner/Auditor, Vision Execution Core, Synthetic Data + self-healing loop, Reporting/scheduling/CLI. See earlier entries in this file's history (git blame / progress.md) for details — all still accurate.

**Since then:**
- **Live website testing** — `aura execute --url <url>` runs a QA test against any live site by opening it in the default browser (`runtime/hooks/browser.py`, stdlib `webbrowser`, zero new dependencies) and driving the same OCR/click pipeline used for desktop apps. `--prompt "<plain English>"` runs fully unattended from a natural-language description instead of a written spec. Confirmed working against a real external site (telusdigital.com) by the person building this, per the execution log referenced in decisions.md D-013.
- **Comprehensive UI audit** (`--ui-audit`) — classifies the page into nav/hero/footer landmarks (`agents/vision/ui_audit.py`) and live-clicks nav/footer elements to flag anything producing no visible change (`orchestrator/ui_audit_runner.py`). Findings now flow into the actual HTML report, not just the terminal (decisions.md D-013).
- **Full-page scroll scan** (`--scroll-test`) — generic OCR error-string scan while scrolling (`orchestrator/autoscan.py`), findings also now persisted to the report (previously silently dropped after printing to console — real gap, fixed in D-013).
- **Code bug detection** (`aura debug <path>`) — static analysis (AST + regex + optional `ruff` pass) that flags bug patterns without fixing them (`agents/auditor/code_auditor.py`). Every check mirrors a real bug class this project caught by hand during earlier QA passes (D-011, the phase-6 finalize sweep).

**156/156 tests passing**, `ruff check` clean.

Every CLI command does real work: `aura init`, `aura execute` (+ `--url`/`--prompt`/`--scroll-test`/`--ui-audit`/`--all`/`--yes`/`--refresh-data`/`--pdf`), `aura debug`, `aura schedule`, `aura skills` (+ `diff`).

## Next action
> Pick one:
> 1. Run a real `--ui-audit` pass against a live external site with a display available, to validate the live-click/screenshot-diff loop end-to-end the way D-009 validated the base vision pipeline (only unit-tested with mocks so far, same category of gap D-009 already closed once for the core executor).
> 2. Reconcile README.md / docs with the phase 7-12 additions — the CLI reference predates `--url`/`--prompt`/`--scroll-test`/`--ui-audit`/`aura debug`.
> 3. Something else — confirm.

## Blockers / open questions
- **Local LLM planner backend needs a real verification run** — `LocalLLMBackend` (settings.planner_backend = "local_llm") is implemented and plumbing-tested, but actual model inference hasn't been run in this build environment. Verify on a normal dev machine before treating it as production-ready. `"heuristic"` remains the default and is fully verified.
- **Vault/repo conventions** — still no code repository link, license, or naming convention confirmed.

## Closed since last update
- **Audit-trail gap (D-007)** — closed via D-008: `run_engine.py`/`healing_loop.py` now route every Planner/Vision/DataSynth call through `OrchestratorKernel.call_tool()`, so `trace.jsonl` populates for real runs.
- **Live-display verification** — closed via D-009: real screenshot capture, OCR locate, and a real dispatched click were verified against `target_app/demo_login_app.py` under a live X server, including confirming the click actually advanced the UI.
- **Local (offline) LLM planner backend** — added via D-010: `LocalLLMBackend` runs spec generation through a local GGUF model via `llama-cpp-python`, zero network calls. Plumbing verified (71/71 tests); actual model inference not yet verified in this sandbox (no prebuilt wheel here) — needs a real run on a normal dev machine before relying on it.
- **PIL Image file-handle leak (D-011)** — found and fixed during full-codebase review: `agents/vision/locator.py` now uses a context manager for `Image.open()`, closing the likely real root cause of the Windows `PermissionError` teardown failures seen earlier.
- **PyInstaller packaging (Option 2 deployment) — actually built and end-to-end tested (D-012)** — found and fixed two real bugs: (1) `ToolRegistry`'s dynamic `importlib` imports weren't visible to PyInstaller's static analysis, causing a `ModuleNotFoundError` crash at execute time despite a clean launch; fixed via `--hidden-import` flags, now in README.md. (2) `settings.project_root` resolved into PyInstaller's temporary extraction directory for a frozen exe, meaning all report/skill/memory output would silently vanish on exit; fixed via a `sys.frozen`-aware default in `config/settings.py`. Verified by running the packaged binary from a clean directory against the live demo app: real capture/OCR/click, all steps executed, report correctly persisted next to the exe.

## New features this pass
- **Skill-library diff** (`aura skills diff --before <old.json> --after <new.json>`) — compares two skill-pack exports and reports added/removed/changed skills (confidence, applied_count, proposed_fix, fix_type), for reviewing what self-healing learned before trusting it in CI.
- **"Explain this test"** (`agents/planner/explainer.py`) — generates a plain-English narrative of what a TestSpec checks, now embedded at the top of every HTML report for non-technical stakeholders.

## Not yet implemented (deferred from the roadmap discussion)
Scoped out of this pass for time; still worth doing:
- Video/GIF diff on step failure
- Element-drift heatmap across runs
- Multi-monitor/resolution profiles
- Local digest notifications (Slack/Teams/email) for scheduled runs
- Confidence-threshold auto-tuning from historical pass/fail data

## Needs review
- Confirm personas in `README.md` still match actual intended users.
- Decide the audit-trail gap above.
- Confirm whether `PRD.md §7`'s four phases (now superseded in practice by the 6-phase `PHASES.md` build plan, which is complete) should be reconciled/updated in the PRD itself so the docs and the code agree.
