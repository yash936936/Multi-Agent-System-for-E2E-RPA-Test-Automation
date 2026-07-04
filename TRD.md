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
