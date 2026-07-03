# AURA Roadmap — Universal Enterprise QA Platform

**Status as of this document:** Phases 1–12 complete and verified (124/124 tests passing). This document defines Phases 13–19: the pivot from "vision-first RPA tester" to "universal QA platform" described in the engineering report.

This is a planning document only — no code changes until you say "next."

---

## 1. Where AURA actually is today (baseline for everything below)

Before planning the pivot, here's what's real and working right now, so the phases below build on fact, not assumption:

| Capability | Status |
|---|---|
| Vision Core (screenshot → OCR → click/type/scroll) | Working. `mss` + `pytesseract` + `pyautogui`. |
| Self-healing on UI drift | Working. Confidence-threshold escalation → Planner diagnoses → Skill store. |
| Planner: heuristic backend | Working, zero dependencies. Recently fixed: compound-sentence parsing, broader assertion phrasing. |
| Planner: local LLM backend | Working. Auto-detects a bundled `models/*.gguf`, zero `.env` editing. |
| Live URL testing | Working. `navigate_url` step type, `--url`, `--prompt` (unattended NL-driven), `--scroll-test`/`--full-scan` (autonomous scroll + nav/footer/hero/CTA landmark detection). |
| Code bug detection | Working. `aura audit-code <path>` — real static analysis via `ruff`, detect-only. |
| Scheduling | Working. `aura schedule` (APScheduler + Windows Task Scheduler docs). |
| Reporting | Working. HTML + optional PDF, per-run JSON/trace. |
| Distribution | Working. `install.bat`/`run.bat` (source install), `build_exe.ps1` (standalone .exe + bundled model). |
| **Backend/API/DB/Email/Excel/PDF/Cloud adapters** | **Not started.** This is the entire scope of Phases 13–19 below. |
| **Web UI / REST service / webhooks** | **Not started.** |

The vision document's Phases 7–12 are renumbered 13–19 here to continue the real history instead of resetting the count.

---

## 2. Scope reality check

The engineering report is a strong *direction*, not yet a buildable increment — a few things need to be said plainly before committing to phases:

- **This is a different product shape.** Today AURA is a CLI tool with local execution. A web UI, REST API, webhook receiver, and credential vault turn it into a hosted service with its own security surface (auth, RBAC, secrets at rest, multi-tenant run isolation). That's a legitimate direction, but it's materially more than "add an adapter."
- **Adapters are individually straightforward, collectively large.** Each one (DB, Email, Excel, PDF, SFTP, Cloud) is a well-scoped, buildable unit — a few days each, real code, real tests, using mature libraries exactly as the report proposes. There are just nine-plus of them.
- **"16 app categories" is a coverage *claim*, not a phase.** ERP/CRM/HR/Finance/Mainframe/etc. aren't new code — they're the Vision Core plus whichever adapters apply, applied to a specific target. Once Vision Core + the relevant adapters exist, most of that table is already true. It doesn't need its own phase; it needs the underlying adapters to exist and one worked example per category to prove it.
- **Cross-modal self-healing (API/DB schema healing)** is a research-flavored problem, not an engineering one — "the Planner diagnoses the JSON diff and updates the spec" is a real capability but the hardest one in this document. It should land last, after the simpler healing patterns (UI-only, already working) have adapter-shaped precedent to build on.

None of this means "no" — it means the roadmap below sequences it so each phase ships something real and testable, instead of one enormous "universal platform" cutover.

---

## 3. Phased plan

### Phase 13 — Capability schema foundation
Extends `orchestrator/schemas.py` with `CapabilityType` and a `CAPABILITY_CHECK` step type (as in the report's §6), plus a minimal `CapabilityAdapter` protocol every adapter implements (`run(params) -> CapabilityResult`). No real adapters yet — this phase is the contract every later adapter plugs into, so Phases 14–17 don't each invent their own interface.

**Deliverable:** schema changes, adapter protocol, one *fake* adapter (returns canned results) proving the `RunEngine` can route a step to `VISION_ACTION` or `CAPABILITY_CHECK` correctly. Full test coverage on the routing logic.

### Phase 14 — Core backend adapters
`api_adapter` (httpx: REST/GraphQL, status/schema/payload assertions), `db_adapter` (SQLAlchemy: read-only queries, row/type/constraint checks — read-only is a deliberate safety default), `email_adapter` (IMAP/SMTP or Graph API: send-and-poll verification).

**Deliverable:** three real, tested adapters. A worked example: "submit a web form (Vision) → verify a row landed in the DB (`db_adapter`)" — the report's flagship cross-boundary scenario, done for real on one concrete target.

### Phase 15 — File & document adapters
`file_adapter` (local/SFTP via `paramiko`/S3 via `boto3`), `excel_adapter` (`openpyxl`/`pandas`: cell values, formulas, formatting), `pdf_adapter` (`pdfplumber`/`pypdf`: text/table/barcode extraction — building on the existing `pdf` skill rather than duplicating it).

**Deliverable:** three adapters, plus report generation validation (report exists → parse it → compare to baseline) as a concrete example combining `file_adapter` + `excel_adapter`/`pdf_adapter`.

### Phase 16 — Cloud & workflow triggers
Cloud SDK adapters (`boto3`, `azure-mgmt` — scoped to read/verify operations first; provisioning is a larger, higher-risk surface and should be opt-in and explicitly confirmed, not default-on). Generic webhook/Cron trigger layer so a CI/CD pipeline can kick off a run.

**Deliverable:** cloud adapter(s) for at least one provider, a minimal trigger endpoint (can be CLI-invoked at this stage — the full FastAPI service is Phase 17).

### Phase 17 — Service layer: API, webhooks, minimal web UI
This is where the report's §5 (FastAPI service, REST endpoints, webhook receiver) actually gets built. Scoped deliberately smaller than the report's full dashboard for a first cut:
- `POST /api/v1/test-runs`, `GET /api/v1/test-runs/{id}`, `GET /api/v1/test-runs/{id}/report`, `GET /api/v1/adapters/status`, `POST /api/v1/webhooks/cicd`.
- A minimal web UI (run list + live status + report viewer) — the drag-and-drop Test Builder is a larger UX investment, deferred to a later refinement once the API/data model are proven.
- **Security is not optional here and isn't in the original report's early phases:** auth on every endpoint and a real secrets story (not "store credentials," but *how* — env-scoped secrets manager or encrypted-at-rest vault) land in this phase, not Phase 19. A service that accepts webhook-triggered runs against real systems without auth from day one is a genuine risk, not a nice-to-have deferred to "hardening."

### Phase 18 — Cross-modal self-healing
Extends the existing UI self-healing pattern to adapters: API payload/schema drift diagnosis, DB schema-change detection. Explicitly sequenced last among the adapter work because it depends on Phases 14–16 existing first (there's nothing to heal until there are non-UI steps to run), and it's the least precedented capability in this plan.

### Phase 19 — Enterprise hardening
RBAC on the web UI, audit logging, credential vault hardening, multi-tenant run isolation if this will ever serve more than one team. Folds in the "16 app categories" coverage table as **verification**, not new code: one worked example per category (ERP/CRM/HR/Finance/Mainframe/etc.) using Phases 13–18's adapters against a real or representative target, documented as proof rather than aspiration.

---

## 4. Sequencing rationale (why this order, not the report's original order)

- **Schema/protocol before adapters (13 before 14–16):** every adapter needs the same contract; building it once first avoids reworking three-plus adapters later.
- **Adapters before the service layer (14–16 before 17):** the API/webhook layer is only useful once there's something real to trigger. Building the service shell first would mean testing it against fake data.
- **Security folded into 17, not deferred to 19:** an unauthenticated webhook endpoint that can trigger runs against production systems is a real exposure the moment Phase 17 ships, not a polish item for later.
- **Self-healing for adapters (18) after the adapters it heals (14–16):** can't diagnose a JSON schema drift before there's a JSON-schema-checking adapter to drift.
- **App-category coverage (part of 19) is verification, not a phase of its own:** once the adapters exist, "does AURA test SAP" is a question answered by pointing it at SAP, not a new subsystem.

---

## 5. What stays true throughout

Two things from AURA's original design should carry through every phase above, not just the UI-testing parts:

- **Detect-only by default, act only on explicit confirmation.** `db_adapter` defaults to read-only queries. Cloud adapters verify before they provision. `audit-code` never modifies files. This same posture should extend to every new adapter — report the truth, don't quietly act on it.
- **Offline-first stays the default, network is opt-in per adapter.** AURA's local LLM backend runs fully on-device by design; the new API/DB/Email/Cloud adapters are inherently network-facing, which is fine and expected — but each one should be explicit about what it connects to and require the target to be configured, not assumed.

---
