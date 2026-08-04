# Product Requirements Document (PRD)
## AURA — Autonomous Unified RPA Agent for Offline QA Test Automation

> This document describes the CLI product's scope. `Roadmap.md` Phases 13–19 later added non-UI capability adapters (API/DB/Email/File/Excel/PDF/Cloud/Workflow) and an in-progress REST/web service layer not covered here — see `Roadmap.md` and `STATUS.md` (the service layer's run-execution path is not yet wired to `RunEngine`). Orchestration below runs through the in-repo orchestrator kernel, not a required external Hermes Agent API — see `docs/TRD.md` §1.

---

## 1. Problem Statement

RPA and UI-test automation suites are brittle: a single DOM ID change, layout shift, or CSS update can break dozens of scripted tests, forcing QA teams into a permanent maintenance cycle rather than genuine coverage growth. Cloud-based AI testing tools solve the flakiness problem but introduce **data residency, cost, and compliance risk**, since screenshots and requirement documents often contain sensitive business logic or PII.

**AURA solves both problems simultaneously**: it is vision-first (so it survives DOM churn) and offline by default (heuristic/local-LLM planner, no required external services), with inter-agent coordination handled through an in-repo orchestrator kernel.

---

## 2. Goals & Non-Goals

### Goals
- G1: Convert plain-language requirement docs into structured, executable test specs without human JSON authoring.
- G2: Execute UI tests via visual understanding rather than fragile selectors.
- G3: Auto-generate realistic and edge-case synthetic test data on demand.
- G4: Diagnose failures and **self-heal** test plans across runs (reduce recurring-failure rate).
- G5: Run offline by default via the in-repo orchestrator kernel, with resource usage compressed as far as technically possible.
- G6: Produce human-readable audit reports for QA sign-off.

### Non-Goals
- Not a general-purpose browser agent for arbitrary web tasks (scope is QA/RPA test execution).
- Not intended to replace exploratory/manual testing — augments scripted regression and RPA bot validation.
- No cloud fallback in v2.1 (may be an optional, explicitly-opt-in stretch goal).

---

## 3. Target Users / Personas

| Persona | Need |
|---|---|
| **QA Automation Engineer** | Wants regression suites that don't break on every sprint's UI tweaks. |
| **RPA Developer** | Needs bots validated against realistic data before production deployment. |
| **Compliance/Security Officer** | Requires zero data egress for testing systems handling regulated data (finance, healthcare, government). |
| **Engineering Manager** | Wants reduced QA maintenance overhead and clear failure-trend reporting. |

---

## 4. User Stories

1. *As a QA engineer*, I upload a requirements doc and get a structured test plan quickly, without writing JSON manually.
2. *As a QA engineer*, when a UI test fails because a button moved, I want the system to retry visually and only escalate to me if it truly can't resolve it.
3. *As an RPA developer*, I want synthetic edge-case data (malformed invoices, unicode names, boundary values) generated automatically each run.
4. *As a compliance officer*, I need proof that no screenshot, prompt, or log leaves the local network boundary.
5. *As an engineering manager*, I want a weekly self-healing report showing which failure classes were auto-fixed vs. escalated.

---

## 5. Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| FR1 | System shall parse unstructured requirement text/PDF/markdown into structured test specs. | P0 |
| FR2 | System shall capture periodic screenshots and map UI elements to interactable coordinates. | P0 |
| FR3 | System shall dispatch OS-level mouse/keyboard events based on visual detection. | P0 |
| FR4 | System shall generate synthetic test data matching schema constraints, including edge cases. | P0 |
| FR5 | System shall log root-cause diagnostics on test failure and propose a corrective plan. | P0 |
| FR6 | System shall persist diagnosed failures as reusable "skills" for automatic reapplication in future runs. | P0 |
| FR7 | Orchestrator shall detect and halt unproductive retry loops using configurable guardrail thresholds. | P0 |
| FR8 | System shall attach a confidence score to every visual action; low-confidence actions are queued for planner review before execution. | P1 |
| FR9 | System shall generate a human-readable HTML/PDF report per run, including screenshots, diffs, and pass/fail summary. | P0 |
| FR10 | System shall support scheduled/unattended nightly runs, with report delivery to local-network channels. | P1 |
| FR11 | System shall support a local index of historical failure/fix pairs to accelerate diagnosis. | P2 |
| FR12 | Orchestration, inference, storage, and logging shall occur on-device by default; any network call (e.g. the optional `cloud_llm` planner backend or a capability adapter checking an external system) requires explicit configuration. | P0 |
| FR13 | All sub-agents shall be invoked strictly through the orchestrator's tool-calling interface, never directly, to keep implementations interchangeable. | P0 |

---

## 6. Success Metrics

| Metric | Target |
|---|---|
| Test-spec generation time (requirement → structured spec) | As fast as the compressed runtime allows |
| Visual element detection accuracy | ≥ 95% on standard desktop/web UI benchmarks |
| Self-healing success rate (recurring failure classes auto-fixed) | ≥ 60% by month 2 of use |
| False-positive escalations to human reviewer | < 10% of total failures |
| Resource footprint | Minimized to the lowest technically viable level, with no fixed hardware target assumed |

---

## 7. Scope (Phased)

- **Phase 1 (MVP):** Planner, Vision, and Data Synth agents registered as orchestrator tools; basic sequential orchestration and reporting.
- **Phase 2:** Full tool-calling routing, skill memory, loop guardrails.
- **Phase 3:** Self-healing feedback loop + local failure-memory index.
- **Phase 4:** Scheduling, unattended runs, multi-channel report delivery, polish + demo packaging.

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Resource contention across concurrently active sub-agents | Strict on-demand invocation and release; aggressive compression applied wherever supported. |
| Vision agent misreads UI (false interaction) | Confidence gating (FR8) + human-in-the-loop escalation. |
| Orchestrator infinite retry loop | Orchestrator-level loop guardrails (warn/hard-stop), see `docs/TRD.md` §5.3. |
| Implementation quality ceiling | Modular tool registration — any sub-agent's implementation swappable without re-architecture. |

---

## 9. Out of Scope for v2.1

- Mobile app UI testing (desktop/web only for now).
- Multi-machine distributed orchestration.
- Cloud fallback (explicitly offline-first).
