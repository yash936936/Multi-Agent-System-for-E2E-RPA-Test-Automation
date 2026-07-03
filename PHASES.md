---
type: build-plan
project: AURA
created: 2026-07-01
---

# AURA — Build Plan (6 Phases)

## Engineering note before we start

The docs (`TRD.md`, `APPFLOW.md`) name **"Hermes Agent API"** (`hermes-agent.nousresearch.com`) as the orchestration layer. That host isn't reachable from this environment (network egress is restricted to package registries and GitHub), and it isn't a pinnable, inspectable dependency. Rather than block the build on an external service we can't verify or install, Phase 2 implements an **in-repo tool-calling orchestration kernel** that satisfies the exact contract described in the TRD:

- named tool registry with input/output schemas
- `tool_call` / `tool_response` structured protocol
- loop guardrails (`warn_after` / `hard_stop_after`, exact-failure and no-progress detection)
- local skill memory store with similarity lookup
- scheduling hook

This is logged as a build decision (`D-006`) in `decisions.md` at the end of Phase 2. If the real Hermes Agent framework becomes available later, only `orchestrator/kernel.py`'s dispatch layer needs to change — every tool contract (Planner/Vision/DataSynth) stays identical, which is the whole point of the tool-call abstraction in the TRD.

Everything else — vision-first testing, confidence gating, self-healing skills, synthetic data, reporting — is built for real, runnable, offline execution in this sandbox using Python.

---

## Phase 1 — Project Scaffolding & Core Contracts

**Goal:** A running, importable skeleton with all shared data contracts, config, and CLI entry point — no agent logic yet.

| File | Purpose / Contents |
|---|---|
| `pyproject.toml` | Package metadata, dependencies (typer/click for CLI, pydantic for schemas, rich for TUI, pillow/mss for screenshots, pytesseract, jinja2 for reports, weasyprint or similar for PDF), entry point `aura`. |
| `config/settings.py` | Central `Settings` (pydantic-settings): paths (`runtime/`, `reports/`, `orchestrator/skills_store/`), confidence threshold (0.75), guardrail thresholds (from TRD §5.4), compression mode flag. |
| `config/tool_registry.yaml` | Static declaration of the four tools (`Planner.generate_spec`, `Planner.diagnose`, `Vision.execute_step`, `DataSynth.generate`) mirroring TRD §5.1 — name, input schema ref, output schema ref. |
| `orchestrator/schemas.py` | Pydantic models for every schema in TRD §4: `TestSpec`, `TestStep`, `VisionActionResult`, `SkillRecord`, `RunReport`. Single source of truth so all agents share identical types. |
| `orchestrator/__init__.py`, `agents/__init__.py`, `agents/planner/__init__.py`, `agents/vision/__init__.py`, `agents/data_synth/__init__.py`, `runtime/__init__.py`, `reports/__init__.py` | Package init files. |
| `aura/main.py` (CLI entry) | `typer` app stub with commands `init`, `execute`, `schedule`, `skills` (no-op bodies for now, wired in later phases) — matches APPFLOW §3 CLI surface. |
| `.gitignore` | Ignore `runtime/screenshots/*`, `orchestrator/memory/*.db`, `reports/run_*`, `__pycache__`, `.venv`. |
| `tests/test_schemas.py` | Round-trip validation tests for every schema in `orchestrator/schemas.py`. |

**Update details:** No prior code exists (confirmed — repo is docs-only). This phase creates every directory listed in `docs/PROJECT_OVERVIEW.md §4` and makes the package `pip install -e .`-able.

---

## Phase 2 — Orchestrator Kernel (Tool-Calling, Guardrails, Skill Memory)

**Goal:** The "hub" — implements the Hermes-Agent-equivalent contract described above, fully offline.

| File | Purpose / Contents |
|---|---|
| `orchestrator/kernel.py` | `ToolRegistry` (register/dispatch tools by name against `tool_registry.yaml`), `OrchestratorKernel.call_tool(name, args) -> tool_response`, verbatim JSONL audit logging to `reports/run_<id>/trace.jsonl` (NFR in TRD §7). |
| `orchestrator/guardrails.py` | `LoopGuardrail` class implementing TRD §5.4 YAML config: tracks exact-failure count and same-tool-failure count per step; returns `continue / warn / hard_stop`. |
| `orchestrator/skill_store.py` | SQLite-backed skill library (`orchestrator/skills_store/skills.db`), `agentskills.io`-compatible JSON export/import (`export_skills`, `import_skills`), embedding-free similarity search over `failure_signature` (TF-IDF or difflib ratio — no network model needed). |
| `orchestrator/memory.py` | Lightweight session/run-state store (SQLite) for in-flight run recovery (TRD §7 "Recoverability") — persists last-completed step per run so an interrupted run resumes. |
| `orchestrator/report_aggregator.py` | Collects `VisionActionResult` + `SkillRecord` streams during a run into the final `RunReport` object (schema from Phase 1), stubbed HTML/PDF paths (rendering built in Phase 6). |
| `orchestrator/scheduler.py` | Cron-like scheduler (`APScheduler`) wrapping `aura schedule add "<cron>" <test_id>`, matching APPFLOW §2.8. |
| `tests/test_guardrails.py`, `tests/test_skill_store.py` | Unit tests: guardrail warn/hard-stop transitions match TRD §5.4 thresholds exactly; skill store round-trips + similarity lookup returns expected top match. |
| `decisions.md` (update) | Append **D-006**: log the Hermes Agent API → in-repo kernel substitution decision described above. |

---

## Phase 3 — Planner & Auditor Agent

**Goal:** Turn requirement docs into structured `TestSpec`s, and diagnose failures into `SkillRecord`s.

| File | Purpose / Contents |
|---|---|
| `agents/planner/tool.py` | Registers `Planner.generate_spec` and `Planner.diagnose` with the kernel's `ToolRegistry` (input/output = Phase 1 schemas). |
| `agents/planner/parser.py` | Ingests Markdown/PDF/plain-text requirement docs (`pypdf` for PDF, raw read for md/txt) into a normalized requirement-text blob. |
| `agents/planner/spec_generator.py` | Core `generate_spec(requirement_text) -> TestSpec` logic — uses an LLM call (pluggable backend: local model via configured endpoint, or Anthropic API if a key is present) prompted to emit TRD §4.1-shaped JSON; validates against the pydantic schema, one re-prompt on validation failure (WORKFLOW §Step 1.3). |
| `agents/planner/diagnoser.py` | `diagnose(failed_step, before_screenshot, after_screenshot, logs) -> SkillRecord` — root-cause reasoning matching TRD §4.3 shape; classifies fix as `retry_strategy` vs `spec_correction` per WORKFLOW §Step 5.3. |
| `agents/planner/prompts.py` | System/user prompt templates for spec generation and diagnosis, kept separate from logic for easy iteration. |
| `requirements_input/example_login_flow.md` | Sample requirement doc (login flow) used for Phase 3/4 integration testing, matching the `TC-LOGIN-001` example already in TRD §4.1 / APPFLOW §2.3. |
| `tests/test_planner.py` | Given `example_login_flow.md`, asserts `generate_spec` returns a schema-valid `TestSpec` with the expected step count/structure; asserts `diagnose` returns a schema-valid `SkillRecord`. |

---

## Phase 4 — Vision Execution Core

**Goal:** Screenshot-based UI understanding and OS-level interaction with confidence gating.

| File | Purpose / Contents |
|---|---|
| `agents/vision/tool.py` | Registers `Vision.execute_step` with the kernel. |
| `runtime/hooks/capture.py` | Screenshot capture via `mss` (cross-platform, no cloud). |
| `runtime/hooks/interact.py` | OS-level mouse/keyboard dispatch via `pyautogui` (click/type/scroll) — the "runtime hook layer" from TRD §2.3 / §6. |
| `agents/vision/locator.py` | Maps a step's `target_description` to on-screen coordinates: OCR text matching (`pytesseract`) for text targets, template/edge matching (`opencv-python`) for icon/button targets; returns `(x, y)` + confidence score. |
| `agents/vision/executor.py` | `execute_step(screenshot, step, skill_hint=None) -> VisionActionResult` — applies confidence gate at 0.75 (TRD §5.3 / WORKFLOW §Step 4.3), injects any skill hint into the search region before locating. |
| `agents/vision/assertions.py` | Post-action assertion checker — compares post-action screenshot region against `expected_state` (OCR/visual-diff based). |
| `tests/test_vision.py` | Synthetic-screenshot fixtures (generated with PIL) with a known button; asserts `locator` finds it above 0.75 confidence, and a deliberately-obscured case falls below threshold. |

---

## Phase 5 — Synthetic Data Generator + Self-Healing Feedback Loop

**Goal:** Wire Planner + Vision + DataSynth together into the full WORKFLOW.md sequence, including the self-healing sub-loop.

| File | Purpose / Contents |
|---|---|
| `agents/data_synth/tool.py` | Registers `DataSynth.generate` with the kernel. |
| `agents/data_synth/generator.py` | `generate(data_requirements) -> dict` — realistic values (via `Faker`) plus deliberate edge cases (unicode names, boundary-length strings, malformed formats) per PRD FR4. |
| `agents/data_synth/cache.py` | Caches generated data to `runtime/data_cache/<test_id>.json`, reused across runs unless `--refresh-data` is passed (TRD §2.4 invocation policy). |
| `orchestrator/run_engine.py` | The actual WORKFLOW.md sequencer: Step 0 bootstrap → Step 1 spec gen → Step 2 data synth → Step 3 skill pre-check → Step 4 vision loop → Step 5 self-healing sub-loop (guardrail-checked) → Step 6 hand-off to report aggregator. This is the file that turns Phases 2–5 into one working pipeline. |
| `orchestrator/healing_loop.py` | Implements WORKFLOW §Step 5 exactly: calls `Planner.diagnose`, classifies fix type, retries via Vision agent up to guardrail limit, persists successful fixes as skills, escalates on hard-stop to a `needs_review` queue table in `orchestrator/memory.py`. |
| `tests/test_run_engine.py` | End-to-end dry run against `requirements_input/example_login_flow.md` using a mocked target window (a small Tkinter test harness app under `target_app/`) — asserts a full run completes and produces a populated `RunReport`. |
| `target_app/demo_login_app.py` | Minimal Tkinter login-form app used purely as the "app under test" for integration tests and demos — gives Phase 4/5 something real to click. |

---

## Phase 6 — Reporting, Scheduling, CLI/TUI Polish, Escalation Queue

**Goal:** Everything APPFLOW.md promises the human user — human-in-the-loop checkpoints, live monitoring, reports, scheduling, skill management.

| File | Purpose / Contents |
|---|---|
| `reports/templates/run_report.html.j2` | Jinja2 template: summary card, per-step detail, before/after screenshot diffs, tool-call audit trace, "skills learned this run" section (APPFLOW §2.6). |
| `reports/render.py` | `render_html(run_report) -> path`, `render_pdf(html_path) -> path` (via `weasyprint`). |
| `aura/cli/init_cmd.py` | `aura init` — setup wizard: target app type, scheduled-run opt-in + local notification channel, compression aggressiveness (APPFLOW §2.1.3). Writes to `config/settings.py`-backed local config file. |
| `aura/cli/execute_cmd.py` | `aura execute <test_id>` / `--all` — renders the spec-approval checklist TUI (via `rich`) per APPFLOW §2.3, blocks on human approval before invoking `run_engine`, then streams live per-step progress (APPFLOW §2.4) including low-confidence inline approval prompts. |
| `aura/cli/schedule_cmd.py` | `aura schedule add "<cron>" <test_id>` wired to `orchestrator/scheduler.py`; nightly runs post a summary-only notification (pass/fail counts) to a configured local channel, never the full report (TRD §5.5 / decisions D-002). |
| `aura/cli/skills_cmd.py` | `aura skills list`, `aura skills export --app <id> > pack.json` — thin CLI wrapper over `orchestrator/skill_store.py` (APPFLOW §2.9). |
| `aura/tui/live_view.py` | `rich`-based live run view rendering the exact step ticker shown in APPFLOW §2.4, plus the healed-step accept/reject checkpoint (APPFLOW §2.5) and the "Needs Review" escalation queue view (APPFLOW §2.7). |
| `tests/test_reports.py`, `tests/test_cli.py` | Report renders valid HTML with all required sections; CLI commands invoke via `typer.testing.CliRunner` without error against the Phase 5 demo app. |
| `README.md` (update) | Replace "no implementation yet" language with real Quick Start instructions matching the actual CLI now built. |
| `STATUS.md`, `progress.md` (update) | Move project from "design/proposal stage" to "Phase 1–6 implemented, MVP runnable end-to-end against `target_app/demo_login_app.py`." |

---

## Execution order

Phases are strictly sequential — each phase's tests must pass before the next phase's code is written, since Phase 5 imports Phases 2–4 directly and Phase 6 imports everything.

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6
(scaffold)  (kernel)   (planner)  (vision)  (integration)  (UX/reporting)
```

Say **"start phase 1"** (or just "next") when ready and I'll begin execution.
