# Technical Requirements Document (TRD)
## AURA — Autonomous Unified RPA Agent

**Version:** 2.1 · **Date:** June 2026

---

## 1. System Architecture Overview

AURA is a **hub-and-spoke multi-agent system** coordinated entirely through the **Hermes Agent API**. The Orchestrator is the hub; the Planner, Vision, and Data-Synth agents are spokes, exposed to the Orchestrator purely as **tools** invoked via Hermes Agent's native tool-calling protocol.

```
                     ┌─────────────────────────┐
                     │      Orchestrator          │
                     │   (Hermes Agent API)        │
                     │  - tool routing               │
                     │  - skill memory (RAG)          │
                     │  - loop guardrails                │
                     │  - report aggregation                │
                     └───────────┬─────────────────┘
                 tool_call ▲     │ tool_response      ▲
        ┌────────────────────┤     │                          │
        │                    ▼     ▼                          │
┌───────────────┐   ┌─────────────────┐   ┌────────────────────┐
│ Planner/Auditor │   │ Vision Execution  │   │ Data Synthesizer     │
└───────┬────────┘   └────────┬────────┘   └─────────┬──────────┘
        │                     │                        │
        ▼                     ▼                        ▼
  Test Specs             OS Runtime Hooks           Mock Data Records
  Root-cause diag.     (screenshot + interaction)     (invoices, etc.)
```

Every sub-agent is registered with the Orchestrator as a named tool with a defined input/output schema. The Orchestrator never calls a sub-agent's implementation directly — all dispatch goes through the Hermes Agent API's tool-calling layer, so any sub-agent can be replaced, upgraded, or compressed without changing orchestration logic.

> **Second execution pattern (§11, proposed):** the diagram above covers AURA driving the UI itself via the Vision Execution Core. A second, independent pattern exists for steps where an external Automation Anywhere bot performs the interaction and AURA only triggers and validates: `Playwright Test Suite → trigger AA bot (REST/CLI) → AA bot runs → validate Web App / Database / Files (Playwright + db_adapter + file_adapter)`. See §11 for the full design and how it reconciles with §10's Playwright locator-resolution redesign.

---

## 2. Component Specifications

### 2.1 Orchestrator
- **Interface:** Hermes Agent API — provides tool-call routing, memory/skills engine, loop guardrails, and scheduling.
- **Responsibilities:**
  - Parse the incoming requirement doc, delegate spec generation to the Planner via a tool call.
  - Sequence: Planner → Data Synth → Vision Execution → Planner (diagnosis) → repeat as needed.
  - Maintain a **skill library** (`agentskills.io`-compatible) of diagnosed UI-failure patterns and their fixes.
  - Enforce configurable loop guardrails (identical-failure and no-progress detection) to avoid runaway retries.
  - Aggregate all sub-agent outputs into the final structured run report.
- **Memory backend:** local, lightweight store for session recall and a locally indexed skill/failure-memory lookup — no external service dependency.

### 2.2 Planner & Auditor Agent
- **Role:** Registered as a Hermes Agent tool (`Planner.generate_spec`, `Planner.diagnose`).
- **Input:** free-text/PDF requirement docs, execution logs, network traces.
- **Output:** a structured **Test Spec** (see §4.1) and, post-execution, a root-cause diagnostic record with a proposed fix/skill.
- **Invocation policy:** invoked on demand via the Hermes Agent API and released immediately after each call completes, minimizing standing resource use.

### 2.3 Vision Execution Core
- **Role:** Registered as a Hermes Agent tool (`Vision.execute_step`).
- **Input:** periodic screenshots + current step's expected visual state.
- **Output:** interaction target location, action decision (click/type/scroll), and a **confidence score (0–1)** per action.
- **Runtime hook:** dispatches native OS mouse/keyboard events via local Python hooks.
- **Invocation policy:** invoked only during active UI validation iterations, released as soon as the step resolves.

### 2.4 Synthetic Data Generator
- **Role:** Registered as a Hermes Agent tool (`DataSynth.generate`).
- **Output:** structured mock records (invoices, transactions, client names, boundary/edge-case strings) matching the Planner's schema constraints.
- **Invocation policy:** invoked once per test-plan generation cycle; results cached and reused across repeated runs unless explicitly refreshed.

---

## 3. Resource Philosophy

No fixed hardware baseline is prescribed. Instead, AURA follows a **maximal-compression, on-demand** policy:

- Every sub-agent is invoked strictly when needed and released the moment its tool call resolves.
- Each sub-agent implementation is compressed as aggressively as its runtime technically supports.
- Only one sub-agent is expected to be actively resource-intensive at any given moment — the Orchestrator's sequencing (via the Hermes Agent API) guarantees this by never issuing overlapping tool calls to resource-heavy agents.
- Resource sizing is a deployment-time concern, not an architectural one — the same tool-call contracts work whether the underlying implementations are tiny or large.

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

## 5. Key Technical Enhancements

### 5.1 Tool-Calling Protocol
All inter-agent communication runs through the Hermes Agent API's native tool-calling protocol:
```
<tools>[Planner.generate_spec, Planner.diagnose, Vision.execute_step, DataSynth.generate]</tools>
<tool_call>{"name": "Vision.execute_step", "arguments": {"step_id": 1, "screenshot": "..."}}</tool_call>
<tool_response>{"target_coords": [1423, 87], "confidence": 0.94}</tool_response>
```
This gives structured, parseable, and auditable inter-agent communication — a direct improvement over ad hoc JSON schema handoffs.

### 5.2 Skill-Based Self-Healing
Each diagnosed failure is written to the skill library. On subsequent runs, the Orchestrator retrieves matching skills via a local similarity lookup on `failure_signature` **before** invoking the Vision agent, pre-emptively adjusting the search strategy.

### 5.3 Confidence-Gated Execution
Vision agent outputs are never executed blindly. Actions below a configurable confidence threshold (default 0.75) are routed back to the Planner for a secondary opinion or flagged for human review.

### 5.4 Loop Guardrails
The Orchestrator adopts the Hermes Agent API's native loop-guardrail configuration:
```yaml
tool_loop_guardrails:
  warnings_enabled: true
  hard_stop_enabled: true
  warn_after:
    exact_failure: 2
    same_tool_failure: 3
    idempotent_no_progress: 2
  hard_stop_after:
    exact_failure: 5
    same_tool_failure: 8
```
This directly prevents the historical RPA failure mode of a bot repeating the same failed interaction indefinitely.

### 5.5 Scheduled & Unattended Runs
The Hermes Agent API's built-in scheduling enables nightly regression sweeps, with report delivery over a local-only channel — only an optional run summary/status may traverse a configured notification relay, while full report artifacts and screenshots remain on local disk only.

---

## 6. APIs / Interfaces

| Interface | Protocol | Purpose |
|---|---|---|
| Orchestrator ↔ Sub-agents | Hermes Agent API tool-calling interface | Tool dispatch and response handling |
| Vision Agent ↔ OS Runtime | Python hook layer | Screenshot capture, interaction dispatch |
| Orchestrator ↔ Skill Store | Local lightweight store + similarity search | Skill CRUD, lookup |
| Report Generator | Templated HTML → PDF | Run report rendering |
| Scheduler | Hermes Agent API scheduling | Unattended run triggers |

---

## 7. Non-Functional Requirements

- **Offline-first:** no outbound network calls during test execution.
- **Auditability:** every tool call/response logged verbatim to `reports/run_<id>/trace.jsonl`.
- **Portability:** each sub-agent's implementation abstracted so it can be swapped via tool registration only (no orchestration code changes).
- **Recoverability:** Orchestrator persists in-flight run state so an interruption mid-run can resume from the last completed step.
- **Minimal footprint:** resource use for every component compressed as far as technically feasible, with no assumption of any particular hardware tier.

---

## 8. Capability Adapters & Cross-Modal Healing (Roadmap Phases 13–18, delivered)

Beyond the vision-only flow above, a `TestStep` may carry `action: "capability_check"` instead of a Vision action. These steps bypass the Vision Execution Core entirely and route through `orchestrator/capability_router.py` to a registered `CapabilityAdapter` (`orchestrator/capability_adapter.py`), keyed on `TestStep.capability_type` (`CapabilityType`: `api`, `database`, `email`, `file_system`, `excel`, `pdf_ocr`, `cloud`, `workflow`, plus `fake` for tests).

- **Input/output contract:** `CapabilityCheckInput` (`capability`, `target`, `params`, `expected`) in, `CapabilityCheckResult` (`capability`, `passed`, `confidence`, `evidence`, `escalate`) out — mirrors the Vision Action Result contract in §4.2 but for non-UI systems.
- **Self-healing:** on failure, `run_engine.py` invokes `agents/planner/cross_modal_diagnoser.py` (up to 2 attempts) before escalating — the same skill-persistence pattern as §5.2, applied to schema/payload drift instead of UI drift.
- **Adapters implemented:** `api_adapter` (httpx), `db_adapter` (SQLAlchemy, read-only by design), `email_adapter` (IMAP/SMTP), `file_adapter` (local + SFTP via paramiko), `excel_adapter` (openpyxl), `pdf_adapter` (pypdf), `cloud_adapter` (boto3, S3 `s3_object_exists` only — other actions are accepted but not yet distinguished), `workflow_adapter` (generic webhook trigger via httpx).
- **Not yet part of this contract:** the REST service layer described informally in Roadmap.md Phase 17 does not yet invoke this path — `api/routers/runs.py::execute_run()` is a stub that doesn't call `RunEngine` at all. This section describes the CLI/`RunEngine`-driven path only, which is the one with real test coverage (`tests/test_capabilities.py`, `tests/test_16_categories_verification.py`).

## 9. Non-Functional Requirements Addendum

The offline-first posture in §7 applies to the original Vision/Planner/DataSynth path. The capability adapters above are, by design, network- or filesystem-facing (that's their purpose) — each one is explicit about what it connects to via `params`, and none defaults to acting without a configured target. `db_adapter` and `cloud_adapter` default to read/detect-only operations rather than mutating the systems they check.

## 10. Delivered: Navigation & Self-Healing Redesign from External Reference Research

**Status: delivered, 2026-07-14.** This section originally documented a
proposed design direction backed by verified research into external repos
(`docs/external_repos.md`, all 6 batches); it was implemented as "Phase C"
of the A–E remediation roadmap — see `docs/decisions.md` D-019 and
`docs/Roadmap.md` §6/§8 for the implementation record. The design below is
now current, not aspirational (found stale — still reading "proposed" —
during a `docs/debug.md`-motivated documentation consistency pass on
2026-07-14, well after the actual implementation had already landed and
been recorded elsewhere in `decisions.md`/`STATUS.md`; fixed here to match).

**Finding:** three independent external projects — Playwright/playwright-mcp
(`browser_snapshot`/`browser_click`), `vercel-labs/agent-browser` (`@eN`
refs via CDP `DOM.resolveNode`), and `alibaba/page-agent` (index-based
selector maps) — converged, unprompted, on the same architecture: **resolve
an element to a stable reference once, then act via that reference**, rather
than re-locating from raw pixels/selectors on every single action.

**Proposed redesign of `agents/vision/locator.py` and `runtime/hooks/interact.py`:**
1. **Primary path (browser targets):** add an accessibility-tree-first
   resolution step, modeled on Playwright's `browser_snapshot`/`browser_click`
   (`docs/external_repos.md` Batch 1) — capture an accessibility snapshot,
   resolve the target element via that tree, and click/type through a
   Playwright `Locator`, not raw screen coordinates.
2. **Fallback path (no accessibility tree — native desktop apps):** keep the
   existing pixel/OCR vision pipeline, hardened with UI-TARS's
   `smartResizeForV15`-style coordinate normalization (Batch 1) so
   OCR-bounding-box coordinates map correctly back to true screen pixels
   after any internal resizing.
3. **Self-healing for the new primary path:** when a Playwright locator fails
   to resolve (structure drift), try `Scrapling`-style relocation (Batch 6)
   before falling back to vision — score every current candidate element
   against the last-known element, threshold-gate the match (don't guess
   below a confidence floor), and log the best score found even on failure
   rather than silently returning nothing. This becomes a new function
   alongside `agents/planner/cross_modal_diagnoser.py`, not a replacement for
   it — DOM-structure drift and UI-pixel drift are different failure modes
   with different fixes.
4. **`agents/capability/link_checker.py`:** replace the current raw-HTML
   fetch with a headless Playwright page load (`waitUntil` past commit, plus
   a network-idle wait — confirmed independently by both the Playwright
   extraction and PixelRAG's `--wait-network-idle` flag, Batch 1 & 2) before
   querying for `<a>` elements, closing the documented client-rendered-page
   false-negative gap (`docs/STATUS.md`).

**Explicitly out of scope for this redesign:** PixelRAG's tiling logic
(Batch 2) is a *screenshot-reading* pattern, not a click/navigation one — it
applies to `agents/vision/executor.py` if/when AURA's vision agent is backed
by a multimodal LLM call rather than OCR-only, not to this navigation
redesign directly.

**Before implementing:** add a corresponding entry to `docs/decisions.md`
(this is a real architecture change to a shipped, tested code path) and
follow `docs/debug.md`'s full checklist — this redesign touches
`agents/vision/locator.py`, `agents/vision/executor.py`,
`runtime/hooks/interact.py`, and `agents/capability/link_checker.py`, all of
which have existing test coverage that must keep passing.

---

## 11. RPA Bot-Trigger & Cross-System Validation Architecture (Automation Anywhere) — delivered

**Status: delivered.** Supersedes §10 for any test step where the
interaction itself is performed by an external RPA bot rather than by
AURA's own Vision Execution Core. See `docs/decisions.md` D-021 (11.1–11.5,
the adapters themselves) and D-023 (11.6's cross-check, enforced by
`RunEngine`).

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

This is a **trigger-and-verify** pattern: AURA does not perform the UI
interaction in this flow — an external Automation Anywhere bot does. AURA's
job is (a) to trigger that bot deterministically and (b) to independently
verify the systems the bot touched, so the check isn't just "did the bot
report success" but "did the web app, database, and files actually end up in
the expected state."

### 11.2 How this maps onto AURA's existing components

This pattern does not require a new orchestration engine — it slots into
the existing `CapabilityAdapter` architecture (§8) as a new capability type,
plus one new adapter:

| Diagram element | AURA implementation |
|---|---|
| Playwright Test Suite | The existing `TestSpec`/`RunEngine` harness (§4.1, §8). A spec's steps sequence a `capability_check` (trigger) followed by one or more validation steps. Playwright itself is only invoked for the "Web App" leg of validation (§11.4) — it is not the harness that decides whether to run, that's still `RunEngine`. |
| Trigger Automation Anywhere Bot (REST API / CLI) | New: `agents/capability/automation_anywhere_adapter.py`, registered as `CapabilityType.AUTOMATION_ANYWHERE` in `orchestrator/capability_adapter.py::default_registry()`. Two trigger modes, mirroring the diagram's "REST API / Command Line" label — REST mode posts to the Control Room bot-deployment endpoint, returning a deployment/activity ID; CLI mode invokes the local AAE CLI/Bot Launcher for on-prem runners with no Control Room reachable. |
| Automation Anywhere Bot Runs | Opaque to AURA by design — the bot's internal steps are not observed. `automation_anywhere_adapter.py` only polls the Control Room activity-status endpoint (REST mode) or watches the CLI process exit code/log tail (CLI mode) until terminal state (`COMPLETED`/`FAILED`), returning a `CapabilityCheckResult` with the bot's own reported status as evidence and `passed=False` on any non-success terminal state. |
| Web App | Post-run validation via a Playwright-backed web validator (§11.4) — new, and distinct in purpose from the §10 locator-resolution redesign (see §11.5). |
| Database | Existing `db_adapter`, used exactly as-is — read-only query against the expected post-bot-run row/state. No changes needed. |
| Files | Existing `file_adapter` (local + SFTP via paramiko), used exactly as-is — checks for the file the bot was expected to produce/move. No changes needed. |
| Playwright Validates | The aggregation point: `RunEngine` collects the `CapabilityCheckResult`s from the web/database/file validation steps and rolls them into the same Run Report schema as §4.4 — a bot run is "passed" only if the trigger succeeded and all three validation legs independently confirm the expected end state. |

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

`CapabilityCheckResult` for this step reuses the §4.2/§8 contract unchanged
(`capability`, `passed`, `confidence`, `evidence`, `escalate`) — `confidence`
is `1.0` or `0.0` here (bot terminal status is binary, not a vision
confidence score), and `evidence` carries the raw Control Room activity
record or CLI exit log for audit purposes.

### 11.4 Playwright web validator (new, validation-only)

A new `agents/capability/playwright_validator.py`, invoked as the "Web App"
leg of the diagram once the bot reports a terminal state:

- Launches a headless Playwright browser and navigates to the target
  page/state the bot was expected to produce (e.g. an updated order-status
  screen).
- Resolves and reads back element/state via Playwright's accessibility
  snapshot (the same primitive as §10's proposed primary action path),
  asserting against the spec's `expected` block — text content, element
  presence, visual state. This leg is strictly read-only: no clicking or
  typing.
- Returns a `CapabilityCheckResult` alongside the `db_adapter`/`file_adapter`
  results for the same run.

### 11.5 Explicit reconciliation with §10 (collision noted, resolved)

§10 proposes Playwright as the primary action-execution path — resolving
and clicking through a Playwright `Locator` — for test steps where AURA's
own Vision Execution Core is the thing driving the interaction. §11 uses
Playwright strictly as a read-only validator after an external AA bot has
already performed the interaction. These are different step types
(`visual_click`/`visual_type` vs. `capability_check` with
`capability: automation_anywhere` or a new `capability: web_validation`) and
both can exist simultaneously without conflict:

- If a `TestSpec` step drives the UI itself, §10's locator-resolution path
  applies (AURA acts).
- If a `TestSpec` step triggers an external bot and then checks the result,
  §11's trigger/validate path applies (AURA only observes and verifies).

Both paths should share the same underlying Playwright browser-context
management code once §10 lands — one `playwright` dependency, one
accessibility-snapshot helper — so `playwright_validator.py` becomes a thin
read-only consumer of whatever browser-session module §10 introduces, rather
than a second independent Playwright integration.

### 11.6 Non-functional notes

- **Offline-first exception, disclosed:** like the other capability adapters
  (§9), `automation_anywhere_adapter.py` and `playwright_validator.py` are
  network-facing by design (Control Room API, headless browser navigation)
  — consistent with §9's existing carve-out, not a new exception.
- **No blind trust of bot-reported success:** a `COMPLETED` status from
  Automation Anywhere alone is not sufficient to mark a run passed — at
  least one of the web/database/file validation legs must also
  independently confirm the expected end state, mirroring §5.3's
  confidence-gating philosophy (never execute or accept blindly) applied to
  a third-party system's self-report instead of a vision-agent's confidence
  score. **Enforced by `RunEngine._enforce_bot_validation_cross_check()`
  (D-023):** a spec author tags an `AUTOMATION_ANYWHERE` trigger step and
  its corresponding `WEB_VALIDATION`/`DATABASE`/`FILE_SYSTEM` step(s) with
  the same `TestStep.bot_validation_group` string; after all steps run,
  `RunEngine` retroactively downgrades the trigger step's own result to
  failed/escalated if none of its grouped validation legs independently
  confirmed the expected end state, adding a `cross_check_failed` note to
  its evidence. Opt-in — specs that don't set `bot_validation_group` are
  completely unaffected.
- **Self-healing scope:** trigger failures (bot didn't start, auth
  rejected) route to the existing `cross_modal_diagnoser.py` (§8) exactly
  like other capability failures. Validation-leg mismatches (bot reported
  success, but the DB/file/web state disagrees) are a new, higher-severity
  failure class — flagged for escalation rather than auto-healed, since a
  disagreement between an RPA bot's self-report and independently observed
  system state is a correctness signal, not a UI-drift pattern a skill can
  fix.
