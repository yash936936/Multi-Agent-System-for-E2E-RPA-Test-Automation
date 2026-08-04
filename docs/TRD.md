# Technical Requirements Document (TRD)
## AURA — Autonomous Unified RPA Agent

---

## 1. System Architecture

AURA's dispatch layer is an in-repo orchestrator kernel (`orchestrator/kernel.py`) with no required external services. The Orchestrator sequences three sub-agents, each exposed as a tool with a defined input/output schema:

```
                     ┌─────────────────────────┐
                     │      Orchestrator        │
                     │   (orchestrator/kernel.py)│
                     │  - tool routing           │
                     │  - skill memory (difflib) │
                     │  - loop guardrails        │
                     │  - report aggregation     │
                     └───────────┬───────────────┘
                 tool_call ▲     │ tool_response
        ┌────────────────────┤     │                          │
        │                    ▼     ▼                          │
┌───────────────┐   ┌─────────────────┐   ┌────────────────────┐
│ Planner/Auditor │   │ Vision Execution  │   │ Data Synthesizer     │
└───────┬────────┘   └────────┬────────┘   └─────────┬──────────┘
        │                     │                        │
        ▼                     ▼                        ▼
  Test Specs             DOM / OS Runtime Hooks     Mock Data Records
  Root-cause diag.     (Playwright locator or OCR)
```

An optional integration with a real Hermes Agent instance exists (`orchestrator/hermes_client.py`, `AURA_PLANNER_BACKEND=hermes_agent`) for anyone running one who wants its memory/skill recall on the far end — off by default, not required.

**Second execution pattern (§11):** the diagram above covers AURA driving the UI itself via the Vision Execution Core. A second, independent pattern exists for steps where an external Automation Anywhere bot performs the interaction and AURA only triggers and validates: `Playwright Test Suite → trigger AA bot (REST/CLI) → AA bot runs → validate Web App / Database / Files (Playwright + db_adapter + file_adapter)`. Implemented as `agents/capability/automation_anywhere_adapter.py` + `agents/capability/playwright_validator.py` — see §11.

---

## 2. Component Specifications

### 2.1 Orchestrator
- **Interface:** in-repo kernel (`orchestrator/kernel.py`) — tool-call routing, memory/skills, loop guardrails, scheduling.
- **Responsibilities:** parse the requirement doc, delegate spec generation to the Planner; sequence Planner → Data Synth → Vision Execution → Planner (diagnosis) → repeat as needed; maintain an `agentskills.io`-compatible skill library of diagnosed UI-failure patterns; enforce loop guardrails; aggregate outputs into the run report.
- **Memory backend:** local store for session recall and skill lookup — no external service dependency.

### 2.2 Planner & Auditor Agent
- **Input:** free-text/PDF requirement docs, execution logs.
- **Output:** a structured Test Spec (§4.1) and, post-execution, a root-cause diagnostic record with a proposed fix/skill.
- **Backends:** heuristic parser (default), local `.gguf` LLM, optional `cloud_llm` (any OpenAI-compatible HTTP endpoint, off by default), optional `hermes_agent`. See `docs/README.md#planner-backends`.

### 2.3 Vision Execution Core
- **Input:** current step's target description; a live Playwright page (DOM path) or a screenshot (OCR fallback path).
- **Output:** interaction target, action decision (click/type/scroll), and a confidence score (0–1) per action.
- **Dispatch:** DOM-first via `agents/vision/dom_locator.py` when a live page exists; OCR + OS-level mouse/keyboard via `runtime/hooks/os_fallback.py` otherwise (native desktop apps, or the no-URL `--interactive` case).

### 2.4 Synthetic Data Generator
- **Output:** structured mock records (usernames, emails, boundary/edge-case strings) matching the Planner's schema constraints.

---

## 3. Resource Philosophy

No fixed hardware baseline is assumed. Each sub-agent is invoked on demand rather than kept resident; resource sizing is a deployment-time concern, not an architectural one.

---

## 4. Data Schemas

### 4.1 Test Spec (Planner Output)
```json
{
  "test_id": "TC-LOGIN-001",
  "requirement_ref": "REQ-4.2",
  "preconditions": ["app_launched", "user_logged_out"],
  "steps": [
    {"step_id": 1, "action": "visual_click", "target_description": "Login button, top-right", "expected_state": "login_modal_visible"},
    {"step_id": 2, "action": "type_text", "field_description": "Username field", "value_ref": "synthetic.username"}
  ],
  "assertions": [{"type": "visual_state", "expected": "dashboard_visible"}],
  "data_requirements": ["username", "password", "edge_case_unicode_name"]
}
```

### 4.2 Vision Action Result
```json
{
  "step_id": 1,
  "action_taken": "click",
  "target_coords": [1423, 87],
  "confidence": 0.94,
  "escalate": false,
  "screenshot_ref": "run_042/step_001.png"
}
```

### 4.3 Diagnostic / Skill Record
```json
{
  "skill_id": "SKILL-2026-0417",
  "failure_signature": "login_button_not_found_after_css_update",
  "root_cause": "Button relocated from top-right to top-center; label text unchanged",
  "proposed_fix": "Broaden visual search region to full header bar before failing",
  "confidence": 0.87,
  "applied_count": 0,
  "created_by": "planner_agent",
  "timestamp": "2026-06-15T10:22:00Z"
}
```

### 4.4 Run Report
```json
{
  "run_id": "run_042",
  "status": "passed_with_healing",
  "total_steps": 20,
  "self_healed_steps": 3,
  "escalated_steps": 1,
  "duration_seconds": 412,
  "report_paths": {"html": "reports/run_042.html", "pdf": "reports/run_042.pdf"}
}
```

---

## 5. Key Mechanisms

### 5.1 Skill-Based Self-Healing
Each diagnosed failure is written to the skill library. On later runs, `orchestrator/skill_store.py`'s `find_similar()` retrieves matching skills via `difflib`-based text similarity on `failure_signature` (no embedding model, no network call) before the Vision agent is invoked.

### 5.2 Confidence-Gated Execution
Actions below `vision_confidence_threshold` (default `0.75`, `config/settings.py`) are not executed — the step is escalated instead (healing loop / human review, depending on run mode).

### 5.3 Loop Guardrails
`orchestrator/guardrails.py` implements configurable warn/hard-stop thresholds on repeated identical failures and no-progress loops, to stop a run from repeating the same failed interaction indefinitely.

### 5.4 Scheduled & Unattended Runs
`aura schedule add "<cron>" <test_id>` wraps `APScheduler` (`orchestrator/scheduler.py`). Nightly runs post a summary-only notification (pass/fail counts) to a configured local channel; full report artifacts and screenshots stay on local disk.

---

## 6. Interfaces

| Interface | Implementation | Purpose |
|---|---|---|
| Orchestrator ↔ Sub-agents | In-repo kernel tool-calling contract | Tool dispatch and response handling |
| Vision Agent ↔ Page/OS | Playwright `page.locator`/`page.mouse` (DOM path) or Python OS hooks (OCR fallback path) | Element resolution, interaction dispatch |
| Orchestrator ↔ Skill Store | Local store + `difflib` similarity search | Skill CRUD, lookup |
| Report Generator | Jinja2 templates → HTML/PDF | Run report rendering |
| Scheduler | `APScheduler` | Unattended run triggers |

---

## 7. Non-Functional Requirements

- **Offline-first by default:** the heuristic parser and local-LLM planner backends make no network calls; the optional `cloud_llm` backend and the capability adapters (§8) are network/filesystem-facing when configured to be.
- **Auditability:** decisions logged to `logs/decision_trace.jsonl`, `logs/assertion_audit.jsonl`, `logs/click_resolution.jsonl` (see `aura explain <run_id>`).
- **Portability:** each sub-agent's implementation is swappable via tool registration without touching orchestration logic.
- **Recoverability:** in-flight run state persists so an interruption can resume from the last completed step.

---

## 8. Capability Adapters & Cross-Modal Healing

A `TestStep` may carry `action: "capability_check"` instead of a Vision action. These steps bypass the Vision Execution Core and route through `orchestrator/capability_router.py` to a registered `CapabilityAdapter` (`orchestrator/capability_adapter.py`), keyed on `TestStep.capability_type` (`CapabilityType`: `api`, `database`, `email`, `file_system`, `excel`, `pdf_ocr`, `cloud`, `workflow`, `automation_anywhere`, plus `fake` for tests).

- **Input/output contract:** `CapabilityCheckInput` (`capability`, `target`, `params`, `expected`) in, `CapabilityCheckResult` (`capability`, `passed`, `confidence`, `evidence`, `escalate`) out — mirrors the Vision Action Result contract in §4.2 for non-UI systems.
- **Self-healing:** on failure, `run_engine.py` invokes `agents/planner/cross_modal_diagnoser.py` (up to 2 attempts) before escalating.
- **Adapters implemented:** `api_adapter` (httpx), `db_adapter` (SQLAlchemy, read-only by design), `email_adapter` (IMAP/SMTP), `file_adapter` (local + SFTP via paramiko), `excel_adapter` (openpyxl), `pdf_adapter` (pypdf), `cloud_adapter` (boto3, S3 `s3_object_exists` only — other actions accepted but not yet distinguished), `workflow_adapter` (generic webhook trigger via httpx), `automation_anywhere_adapter` (§11), `playwright_validator` (§11).
- **Known gap:** the REST service layer's `api/routers/runs.py::execute_run()` is a stub that does not call `RunEngine` — this section describes the CLI/`RunEngine`-driven path, which has test coverage (`tests/test_capabilities.py`, `tests/test_16_categories_verification.py`); the REST path does not yet exercise it.

## 9. Non-Functional Requirements Addendum

§7's offline-first posture applies to the Vision/Planner/DataSynth path. The capability adapters are network- or filesystem-facing by design — each is explicit about what it connects to via `params`, and none acts without a configured target. `db_adapter` and `cloud_adapter` default to read/detect-only operations.

## 10. Navigation & Self-Healing: DOM-First Dispatch

Element resolution is DOM-first, with OCR as a fallback:

1. **Primary path (browser targets):** `agents/vision/dom_locator.py`'s `locate_dom()` captures an accessibility snapshot (`page.locator(...)`), scores candidates against the target description, and resolves through a Playwright `Locator` — not raw screen coordinates.
2. **Fallback path (no accessibility tree — native desktop apps, or the no-URL `--interactive` case):** the pixel/OCR pipeline in `runtime/hooks/os_fallback.py`, confined to that one code path (see `CONVENTIONS.md` §2).
3. **Self-healing on the DOM path:** when a Playwright locator fails to resolve (structure drift), `relocate_dom()` scores every current candidate element against the last-known element, threshold-gated at `RELOCATE_MIN_RATIO` (0.40), returning ties rather than guessing and logging the best score found even on failure. This is a separate function from `agents/planner/cross_modal_diagnoser.py` (§8) — DOM-structure drift and capability/schema drift are different failure classes.
4. **`agents/capability/link_checker.py`:** loads pages via headless Playwright (`wait_until="commit"`, then a `networkidle` wait) before querying for `<a>` elements, rather than a raw HTML fetch — this avoids false negatives on client-rendered pages.

Touches `agents/vision/locator.py`, `agents/vision/dom_locator.py`, `runtime/hooks/interact.py`, and `agents/capability/link_checker.py`, all of which have test coverage.

---

## 11. RPA Bot-Trigger & Cross-System Validation Architecture (Automation Anywhere)

Supersedes §10 for any test step where the interaction itself is performed by an external RPA bot rather than by AURA's own Vision Execution Core.

### 11.1 Source pattern

```
Test Execution
        Playwright Test Suite
               │
               ▼
     Trigger Automation Anywhere Bot
      (REST API / Command Line)
               │
               ▼
      Automation Anywhere Bot Runs
               │
       ┌───────┼────────┐
       ▼       ▼        ▼
    Web App  Database  Files
       ▲       ▲        ▲
       │       │        │
     Playwright Validates
```

This is a trigger-and-verify pattern: AURA does not perform the UI interaction — an external Automation Anywhere bot does. AURA's job is (a) to trigger that bot deterministically and (b) to independently verify the systems the bot touched.

### 11.2 How this maps onto AURA's existing components

| Diagram element | AURA implementation |
|---|---|
| Playwright Test Suite | The existing `TestSpec`/`RunEngine` harness (§4.1, §8). A spec's steps sequence a `capability_check` (trigger) followed by validation steps. |
| Trigger Automation Anywhere Bot (REST API / CLI) | `agents/capability/automation_anywhere_adapter.py`, registered as `CapabilityType.AUTOMATION_ANYWHERE`. REST mode posts to the Control Room bot-deployment endpoint; CLI mode invokes the local AAE CLI/Bot Launcher when no Control Room is reachable. |
| Automation Anywhere Bot Runs | Opaque to AURA by design. `automation_anywhere_adapter.py` polls the Control Room activity-status endpoint (REST mode) or watches the CLI process exit code/log tail (CLI mode) until terminal state (`COMPLETED`/`FAILED`), returning a `CapabilityCheckResult` with `passed=False` on any non-success terminal state. |
| Web App | Post-run validation via `playwright_validator.py` (§11.4), read-only. |
| Database | Existing `db_adapter` — read-only query against the expected post-bot-run state. |
| Files | Existing `file_adapter` (local + SFTP via paramiko). |
| Playwright Validates | `RunEngine` collects the `CapabilityCheckResult`s from the web/database/file validation steps and rolls them into the Run Report schema (§4.4). |

### 11.3 Data schema — Automation Anywhere trigger step

```json
{
  "capability": "automation_anywhere",
  "target": {
    "mode": "rest",
    "control_room_url": "https://<tenant>.my.automationanywhere.digital",
    "bot_id": "12345",
    "run_as_user_id": "67890"
  },
  "params": {
    "input_variables": {"invoice_id": "INV-2026-0417"},
    "poll_interval_seconds": 5,
    "timeout_seconds": 600
  },
  "expected": {"terminal_status": "COMPLETED"}
}
```

`CapabilityCheckResult` reuses the §4.2/§8 contract unchanged — `confidence` is `1.0` or `0.0` (bot terminal status is binary), and `evidence` carries the raw Control Room activity record or CLI exit log.

### 11.4 Playwright web validator (validation-only)

`agents/capability/playwright_validator.py`, invoked as the "Web App" leg once the bot reports a terminal state: launches a headless Playwright browser, navigates to the target page/state, resolves and reads back element/state via Playwright's accessibility snapshot, and asserts against the spec's `expected` block. Strictly read-only — no clicking or typing.

### 11.5 Relationship to §10

§10 covers Playwright as the primary action-execution path for steps AURA's own Vision Execution Core drives. §11 uses Playwright strictly as a read-only validator after an external AA bot has performed the interaction. These are different step types (`visual_click`/`visual_type` vs. `capability_check` with `capability: automation_anywhere`) and coexist without conflict — both use the same underlying Playwright browser-context management code.

### 11.6 Non-functional notes

- **Network-facing by design**, consistent with §9's carve-out: `automation_anywhere_adapter.py` and `playwright_validator.py` call the Control Room API and navigate a headless browser.
- **No blind trust of bot-reported success:** enforced by `RunEngine._enforce_bot_validation_cross_check()`. A spec author tags an `AUTOMATION_ANYWHERE` trigger step and its corresponding `WEB_VALIDATION`/`DATABASE`/`FILE_SYSTEM` step(s) with the same `TestStep.bot_validation_group` string; after all steps run, `RunEngine` downgrades the trigger step's own result to failed/escalated if none of its grouped validation legs independently confirmed the expected end state, adding a `cross_check_failed` note to its evidence. Opt-in — specs that don't set `bot_validation_group` are unaffected.
- **Self-healing scope:** trigger failures (bot didn't start, auth rejected) route to `cross_modal_diagnoser.py` (§8) like other capability failures. Validation-leg mismatches (bot reported success, but DB/file/web state disagrees) are flagged for escalation rather than auto-healed.
