---
type: progress-log
project: AURA
---

# Progress Log

> Dated entries only. Don't edit past entries — append new ones. Newest at the top.

---

## 2026-07-03 — Comprehensive UI audit + code bug detection ("professional QA tester" feature request)
**What happened:**
- Started with a full debug-qa-finalize pass on the uploaded phase-12 codebase: 119/119 tests passing, `ruff check` clean going in. Found and fixed a repeat instance of the D-011 bug class (unclosed `Image.open()` in `agents/vision/page_health.py`) during the review — same root cause as before, different file. Two tests mocking `Image.open` needed updating to support the context-manager protocol as a result.
- Built `agents/vision/ui_audit.py` + `orchestrator/ui_audit_runner.py`: classifies a page into nav/hero/footer landmark bands via OCR position + vocabulary heuristics, then live-clicks nav/footer elements and screenshot-diffs before/after to flag anything with no visible change as possibly non-functional. Wired to new `aura execute --ui-audit` flag.
- While wiring this into the report, found a real pre-existing gap: `--scroll-test`'s `autoscan_report` was computed and printed to the terminal but never actually passed into `render_html()` — so it never reached the saved report file, only the console. Fixed for both `--scroll-test` and the new `--ui-audit`.
- Built `agents/auditor/code_auditor.py` + `aura debug <path>` command: AST/regex-based bug detection (syntax errors, mutable default args, silently-swallowed exceptions, bare except, TODO markers, unmanaged file handles) plus an optional `ruff` pass. Explicitly detection-only, verified by a dedicated "never modifies the file" test.
- Dogfooded `aura debug .` against AURA's own codebase: found 3 genuine (but intentional/documented) `except NoDisplayError: pass` patterns and 1 known false positive in the auditor's own test file. Both outcomes are honest, expected behavior for a heuristic detector, not the tool malfunctioning.
- Full logged decision: see decisions.md D-013.

**What changed:**
- New files: `agents/vision/ui_audit.py`, `orchestrator/ui_audit_runner.py`, `agents/auditor/code_auditor.py`, `aura/cli/debug_cmd.py`, `tests/test_ui_audit.py`, `tests/test_ui_audit_runner.py`, `tests/test_code_auditor.py`.
- Modified: `agents/vision/page_health.py` (leak fix), `reports/render.py` + `run_report.html.j2` (audit report sections), `aura/cli/execute_cmd.py` + `aura/main.py` (`--ui-audit` wiring, `debug` command), `runtime/hooks/interact.py` (`browser_back`), `tests/test_autoscan.py` (fixed mocks), `tests/test_cli.py` (fixed test double signature).
- Test count: 119 -> 156. `ruff check` clean throughout.

**Known limitations, disclosed rather than hidden:** UI-audit landmark classification is a Y-position + vocabulary heuristic, not real DOM understanding — false negatives on unconventional layouts are expected. The live-click check can't distinguish "broken" from "visually-identical-but-actually-changed" (e.g. a same-looking modal). `code_auditor.py`'s regex checks (`todo-marker`, `unmanaged-file-handle`) can false-positive inside string literals, confirmed by the dogfood run.

**What should happen next:**
- Run `--ui-audit` for real against a live external site with an actual display (only mock-tested so far, same gap category D-009 already closed once for the core executor).
- Reconcile README.md / docs with the accumulated phase 7-12 feature surface.


**What happened:**
- User ran `python -m pytest` on Windows and hit 13 failures, all `OSError: cannot open resource` from Pillow's `ImageFont.truetype()`. Root cause: `target_app/demo_login_app.py` and `tests/test_vision.py` both hardcoded a Linux-only font path (`/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`), which doesn't exist on Windows (or macOS, or a bare Linux box without the `fonts-dejavu` package).
- Fixed by replacing the hardcoded path with `resolve_font(size)` in `target_app/demo_login_app.py`: tries a list of common TrueType font locations across Linux/macOS/Windows, and falls back to Pillow's bundled default font (`ImageFont.load_default(size=...)`) if none exist, so screenshot rendering for tests/demos never hard-fails on missing OS fonts again.
- `tests/test_vision.py` now imports and reuses `resolve_font()` from `target_app.demo_login_app` instead of duplicating its own hardcoded path.
- Verified: (1) resolver still picks up the real DejaVu font on this Linux sandbox, (2) manually forced the "no candidate found" branch to confirm the `load_default()` fallback also produces a working renderable font, (3) full suite re-run: **62/62 passing**.

**What changed:**
- `target_app/demo_login_app.py` no longer assumes a specific OS's font layout — this was the one piece of Phase 5/6 that hadn't actually been run anywhere but this Linux build sandbox until now.

**What should happen next:**
- Re-run `python -m pytest` on the Windows machine that reported the original failure to confirm the fix closes it out there too.


## 2026-07-02
**What happened:**
- Executed the full 6-phase build plan (`PHASES.md`) against the design docs from 2026-07-01. AURA now has a real, runnable, offline codebase, not just documentation.
- **Phase 1 — Scaffolding & core contracts:** `pyproject.toml` (pip-installable, `aura` console script), `config/settings.py`, `config/tool_registry.yaml`, `orchestrator/schemas.py` (pydantic models for every TRD §4 schema), CLI stub (`aura init/execute/schedule/skills`).
- **Phase 2 — Orchestrator kernel:** `orchestrator/kernel.py` (tool registry + dispatch + verbatim JSONL audit trace), `orchestrator/guardrails.py` (warn/hard-stop loop guardrails), `orchestrator/skill_store.py` (SQLite skill library with difflib-based similarity search and `agentskills.io`-compatible export/import), `orchestrator/memory.py` (run-state + escalation queue), `orchestrator/scheduler.py` (APScheduler wrapper). **Logged as D-006:** the Hermes Agent API is replaced by this in-repo kernel, since the external host isn't reachable/pinnable from the build environment — the *contract* from D-003 is preserved exactly, only the dispatch backend changed.
- **Phase 3 — Planner & Auditor agent:** `agents/planner/` — offline heuristic requirement parser (`spec_generator.py`, no network call, deterministic), failure diagnoser (`diagnoser.py`) classifying fixes as `retry_strategy` vs `spec_correction`.
- **Phase 4 — Vision Execution Core:** `agents/vision/` — OCR-based element location (`locator.py`, pytesseract), confidence-gated executor (`executor.py`, 0.75 threshold), assertion checker; `runtime/hooks/` for real screenshot capture (`mss`) and OS interaction (`pyautogui`), both with deferred imports so the rest of the system stays testable without a live display.
- **Phase 5 — Data Synth + integration:** `agents/data_synth/` (Faker-based generator + cache), `orchestrator/run_engine.py` (the real WORKFLOW.md sequencer wiring all agents together), `orchestrator/healing_loop.py` (the self-healing sub-loop with guardrail-checked retries), `target_app/demo_login_app.py` (Tkinter demo app + headless-safe synthetic screenshot renderer for tests). End-to-end test proves a full login-flow run completes, resumes correctly after interruption, escalates cleanly on a genuinely broken app, and reuses cached synthetic data.
- **Phase 6 — Reporting, scheduling, CLI/TUI polish (this session):**
  - `reports/templates/run_report.html.j2` + `reports/render.py` — HTML report generator (summary card, per-step detail, skills-learned section, audit trace) matching APPFLOW §2.6, plus optional PDF export via `weasyprint` (`pip install -e '.[report]'`).
  - `aura/cli/init_cmd.py`, `execute_cmd.py`, `schedule_cmd.py`, `skills_cmd.py` + `aura/tui/live_view.py` — every CLI command now does real work instead of printing a stub: `aura init` (setup wizard → `config/local_config.json`), `aura execute` (spec-approval checklist → live step ticker → low-confidence inline approval → self-healed-step accept/reject → report + Needs-Review queue), `aura schedule` (wraps the Phase-2 scheduler, runs unattended via `auto_approve=True`), `aura skills` (list/export/import).
  - Added optional progress-callback hooks (`on_step_start`, `on_step_result`, `on_skill_learned`) to `RunEngine` so the CLI's live view can observe a run without changing the engine's core control flow or breaking any Phase-5 tests (all default to `None`).
  - Added `SkillStore.delete()` to support the heal-reject path in `aura execute`.
  - New tests: `tests/test_reports.py` (renders a real run's artifacts, checks required sections and consistent numbers), `tests/test_cli.py` (init/skills/schedule commands via `typer.testing.CliRunner`; `aura execute` itself is left to the existing `test_run_engine.py` coverage since it needs a live display).
  - **Bug found and fixed during verification:** the report template and terminal summary were printing raw enum reprs (`RunStatus.PASSED` instead of `passed`) because Python 3.11+ changed `str()` behavior for `StrEnum`-style enums — fixed by using `.status.value` explicitly in both `reports/templates/run_report.html.j2` and `aura/tui/live_view.py`. Also fixed a step-count mismatch where the synthesized final-assertion pseudo-step was being counted in "Passed" but not in "Total steps."
- Full test suite: **62/62 passing** after Phase 6, including the new report/CLI tests, verified twice (before and after the enum/count bug fixes).

**What changed:**
- Project moved from "documentation only" to **feature-complete MVP**, matching every surface promised in `APPFLOW.md` and every requirement in `PRD.md`'s functional requirements table, runnable end-to-end offline against the bundled demo app.

**Known limitations carried forward (see STATUS.md):**
- `orchestrator/run_engine.py` calls agent tool functions directly rather than routing every call through `OrchestratorKernel.call_tool()`, so `trace.jsonl` (the audit trail promised in the report's "Full tool-call/tool-response audit trace" section) is empty for runs produced this way. `reports/render.py` degrades gracefully (renders an empty trace) rather than failing, but this is a real gap between the TRD's described architecture and the current wiring.
- `aura execute` requires a live display (real screenshot capture via `mss`/`pyautogui`); it hasn't been exercised against an actual running target app in this sandbox (no display available), only against the Phase 5 synthetic-screenshot test harness.
- Planner's default backend is a deterministic heuristic parser, not a real LLM — sufficient for the bundled example and tests, but requirement docs outside that pattern range will need either backend improvements or enabling the (currently off-by-default) `AnthropicBackend` path in `spec_generator.py`.

**What should happen next:**
- Decide whether to route `run_engine.py` through the kernel for real audit-trail completeness, or formally accept the current direct-call wiring as good enough and update the TRD to match reality.
- Try `aura execute` against `target_app/demo_login_app.py` on a machine with an actual display, to validate the live capture/interact path that's only unit-tested so far.
- Resolve the still-open items from `decisions.md` (sub-agent runtime choice for anything beyond the heuristic Planner backend, target OS priority, license, repo location).


## 2026-07-01
**What happened:**
- Initial project documentation set drafted: `PRD.md`, `TRD.md`, `WORKFLOW.md`, `APPFLOW.md`, and a project overview README, based on the original "Autonomous Offline Multi-Agent System for End-to-End RPA Test Automation" proposal (June 2026, Prakhar Doneria).
- Revised the full doc set to:
  1. Integrate the **Hermes Agent API** as the multi-agent orchestration layer (replacing the original "sequential Python state handler" design).
  2. Remove all references to specific underlying AI models — sub-agents are now defined purely by role and tool contract (Planner/Auditor, Vision Execution Core, Synthetic Data Generator), invoked via Hermes Agent tool calls.
  3. Remove fixed hardware/system specifications (VRAM, RAM, GPU model) — replaced with a resource-agnostic "compress as far as technically possible, on-demand invocation" philosophy.
- Set up this Obsidian vault folder (`AURA/`) with the four core memory files plus a `docs/` subfolder holding the detailed project documents.

**What changed:**
- Project moved from "raw proposal" to "structured, versioned documentation" (PRD/TRD/WORKFLOW/APPFLOW all at v2.1).

**What should happen next:**
- Confirm the open items in `STATUS.md` (next action, runtime choice, blockers).
- Once confirmed, log that decision in `decisions.md` and update `STATUS.md` accordingly.
