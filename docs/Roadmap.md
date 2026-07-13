# AURA Roadmap — Universal Enterprise QA Platform

**Status as of this update (2026-07-04):** Phases 1–12 complete and verified. Phases 13–18 below are **implemented and tested** (199/199 tests passing) — this is no longer a planning-only document for those phases; the "no code changes until you say next" note further down is historical and superseded. Phase 19 (enterprise hardening) is **partially implemented**: the schema/adapter/routing foundation and the 16-app-category verification exist, but the service layer's auth/run-execution wiring described in Phase 17 is incomplete — see §1a below before treating any of this as production-ready.

---

## 1. Where AURA actually is today (baseline for everything below)

Before planning further work, here's what's real and working right now, so this stays built on fact, not assumption:

| Capability | Status |
|---|---|
| Vision Core (screenshot → OCR → click/type/scroll) | Working. `mss` + `pytesseract` + `pyautogui`. |
| Self-healing on UI drift | Working. Confidence-threshold escalation → Planner diagnoses → Skill store. |
| Planner: heuristic backend | Working, zero dependencies. |
| Planner: local LLM backend | Working. Auto-detects a bundled `models/*.gguf`, zero `.env` editing. |
| Live URL testing | Working. `navigate_url` step type, `--url`, `--prompt` (unattended NL-driven), `--scroll-test`/`--full-scan` (autonomous scroll + nav/footer/hero/CTA landmark detection). |
| Code bug detection | Working. `aura debug <path>` — real static analysis via `ruff`, detect-only. |
| Scheduling | Working. `aura schedule` (APScheduler + Windows Task Scheduler docs). |
| Reporting | Working. HTML + optional PDF, per-run JSON/trace. |
| Distribution | Working. `install.bat`/`run.bat` (source install), `build_exe.ps1` (standalone .exe + bundled model). |
| **Capability schema + routing (Phase 13)** | **Done.** `orchestrator/schemas.py` (`CapabilityType`, `CapabilityCheckInput`/`CapabilityCheckResult`, `TestStep.capability_type`/`target`/`expected`), `orchestrator/capability_router.py`, `orchestrator/capability_adapter.py`. Full routing test coverage. |
| **Backend/API/DB/Email adapters (Phase 14)** | **Done.** `agents/capability/{api,db,email}_adapter.py`, tested against mocked backends. |
| **File & document adapters (Phase 15)** | **Done.** `file_adapter` (local + SFTP via `paramiko`), `excel_adapter` (`openpyxl`), `pdf_adapter` (`pypdf`). |
| **Cloud & workflow triggers (Phase 16)** | **Done, with a known scope gap.** `cloud_adapter` (S3 via `boto3`, detect-only) implements `s3_object_exists` only — it parses an `action` param but never branches on other actions, so requesting anything else silently runs the same check rather than erroring. `workflow_adapter` (generic webhook trigger via `httpx`) is complete. |
| **Cross-modal self-healing (Phase 18)** | **Done.** `agents/planner/cross_modal_diagnoser.py`, wired into `run_engine.py`'s capability-check loop (up to 2 heal attempts before escalating). |
| **Web UI / REST service / webhooks (Phase 17)** | **Implemented, but not functional end-to-end — see §1a.** |
| **16-app-category verification (part of Phase 19)** | **Done.** `tests/test_16_categories_verification.py` exercises all 16 categories against the adapters above. |
| **Enterprise hardening — RBAC, audit logging, multi-tenant isolation (rest of Phase 19)** | **Partial.** JWT + role checks exist (`api/security.py`), per-tenant run dicts exist (`api/routers/runs.py`), an audit logger exists (`orchestrator/audit_logger.py`) — but the run store is in-memory only (lost on restart) and there's no persistence layer. |

### 1a. Phase 17 gap detail — the service layer is a scaffold, not a working feature

This is important enough to call out before anyone builds on it: `api/main.py` boots a real FastAPI app with routers and a web dashboard, but:

- `api/routers/runs.py::execute_run()` **never calls `RunEngine`.** It marks a run `"running"` then unconditionally `"passed"`, with a `# Hook into RunEngine here...` comment marking the gap. Every run "succeeds" regardless of what it actually tests.
- `api/security.py::create_access_token()` is defined but **no endpoint calls it** — there's no login/token route, so a client can't actually authenticate against a cold instance.
- There's no `aura serve` CLI command; starting the service means already knowing `uvicorn api.main:app`.
- The vault's Fernet key doubles as the JWT signing secret — works, but conflates two different secrets with different rotation/exposure profiles.

None of this is a regression from a prior working state — it appears this was always a scaffold-first build for Phase 17 that never got a follow-up pass. It's now documented (`STATUS.md`) as the top-priority next action rather than left to be rediscovered.

The vision document's original Phases 7–12 are renumbered 13–19 here to continue the real history instead of resetting the count.

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

### Phase 13 — Capability schema foundation — **delivered**
Extends `orchestrator/schemas.py` with `CapabilityType` and a `CAPABILITY_CHECK` step type (as in the report's §6), plus a minimal `CapabilityAdapter` protocol every adapter implements (`run(payload: CapabilityCheckInput) -> CapabilityCheckResult`). No real adapters yet — this phase is the contract every later adapter plugs into, so Phases 14–17 don't each invent their own interface.

**Deliverable:** schema changes, adapter protocol, one *fake* adapter (returns canned results) proving the `RunEngine` can route a step to `VISION_ACTION` or `CAPABILITY_CHECK` correctly. Full test coverage on the routing logic.

### Phase 14 — Core backend adapters — **delivered**
`api_adapter` (httpx: REST/GraphQL, status/schema/payload assertions), `db_adapter` (SQLAlchemy: read-only queries, row/type/constraint checks — read-only is a deliberate safety default), `email_adapter` (IMAP/SMTP or Graph API: send-and-poll verification).

**Deliverable:** three real, tested adapters. A worked example: "submit a web form (Vision) → verify a row landed in the DB (`db_adapter`)" — the report's flagship cross-boundary scenario, done for real on one concrete target.

### Phase 15 — File & document adapters — **delivered**
`file_adapter` (local/SFTP via `paramiko`/S3 via `boto3`), `excel_adapter` (`openpyxl`/`pandas`: cell values, formulas, formatting), `pdf_adapter` (`pdfplumber`/`pypdf`: text/table/barcode extraction — building on the existing `pdf` skill rather than duplicating it).

**Deliverable:** three adapters, plus report generation validation (report exists → parse it → compare to baseline) as a concrete example combining `file_adapter` + `excel_adapter`/`pdf_adapter`.

### Phase 16 — Cloud & workflow triggers — **delivered, cloud_adapter scope gap noted in §1**
Cloud SDK adapters (`boto3`, `azure-mgmt` — scoped to read/verify operations first; provisioning is a larger, higher-risk surface and should be opt-in and explicitly confirmed, not default-on). Generic webhook/Cron trigger layer so a CI/CD pipeline can kick off a run.

**Deliverable:** cloud adapter(s) for at least one provider, a minimal trigger endpoint (can be CLI-invoked at this stage — the full FastAPI service is Phase 17).

### Phase 17 — Service layer: API, webhooks, minimal web UI — **implemented, see §1a for the gap**
This is where the report's §5 (FastAPI service, REST endpoints, webhook receiver) got built. It shipped scoped smaller than the report's full dashboard, as planned:
- `POST /api/v1/test-runs`, `GET /api/v1/test-runs/{id}`, `GET /api/v1/test-runs/{id}/report` (`api/routers/runs.py`), plus adapter-status and webhook routers.
- A minimal web UI (`webui/templates/index.html`) — static for now, not yet wired to live run status; the drag-and-drop Test Builder is still deferred as originally planned.
- **Auth exists (JWT + role checks via `api/security.py`), but the loop isn't closed** — there's no endpoint that issues a token, and `execute_run()` doesn't actually invoke `RunEngine` yet. See §1a for the full detail. Treat "security is not optional" below as still true and **not yet fully satisfied** — a deployed instance today would accept authenticated-looking requests that don't do what they claim.

### Phase 18 — Cross-modal self-healing — **delivered**
Extends the existing UI self-healing pattern to adapters: API payload/schema drift diagnosis, DB schema-change detection. Explicitly sequenced last among the adapter work because it depends on Phases 14–16 existing first (there's nothing to heal until there are non-UI steps to run), and it's the least precedented capability in this plan.

### Phase 19 — Enterprise hardening — **partially delivered, see §1**
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

## 6. Phase 20 (proposed, not started) — Navigation redesign + observability, from external reference research

Backed by verified research across 18 external repos, 6 batches, documented
in full in `docs/external_repos.md`. Status: **proposed only** — nothing in
this phase is implemented. See `docs/TRD.md` §10 for the full technical
design.

- **20a. Playwright-first element resolution + Scrapling-style DOM self-heal**
  for browser targets, UI-TARS-style coordinate normalization retained as the
  native-desktop fallback path. Touches `agents/vision/locator.py`,
  `runtime/hooks/interact.py`.
- **20b. `agents/capability/link_checker.py` headless-render fix** — load the
  page via Playwright with a network-idle wait before scanning for `<a>`
  elements, closing the client-rendered-page false-negative gap in
  `docs/STATUS.md`.
- **20c. Skill quality-tracking** (inspired by `HKUDS/OpenSpace`'s
  `skill_engine/analyzer.py`) — add a lightweight success/failure counter to
  whatever `orchestrator/skill_store.py` persists per skill, so a stored fix
  that stops working can be surfaced rather than reused forever on faith.
- **20d. Structured audit-log event taxonomy** (inspired by `langfuse`'s
  `ObservationType` enum) — give `orchestrator/audit_logger.py` a small fixed
  set of event types (e.g. `VISION_ACTION`, `CAPABILITY_CHECK`,
  `PLANNER_DIAGNOSIS`, `SELF_HEAL`, `GUARDRAIL_STOP`) instead of free-form log
  entries, so `logs/audit.jsonl` becomes queryable/reportable in a structured
  way.
- **20e. Guardrail structure review** (inspired by `openhuman`'s
  stop-hook-middleware pattern) — confirm `orchestrator/guardrails.py` is
  structured as independently-voting checks (any one check can halt a run)
  rather than one combined condition, for easier future extension.

Sequencing note: 20a and 20b should land together (both depend on the same
Playwright integration work); 20c–20e are independent, smaller, and can land
in any order once 20a/20b are done or in parallel with them.

---

## 7. Phase 21 (proposed, not started) — Automation Anywhere trigger/validate architecture

Full technical design in `docs/TRD.md` §11. Status: **proposed only** —
nothing in this phase is implemented; adds a distinct execution pattern
alongside (not replacing) Phases 13–20.

- **21a. `agents/capability/automation_anywhere_adapter.py`** (new) — new
  `CapabilityType.AUTOMATION_ANYWHERE`, triggers a bot via the Control Room
  REST API or the local AAE CLI, polls to terminal status.
- **21b. `agents/capability/playwright_validator.py`** (new) — read-only
  Playwright-based post-run check against the web app's expected state.
  Shares its browser-session code with Phase 20a's locator work once that
  lands, rather than a second independent Playwright integration.
- **21c. Validation-leg cross-check** — a bot-reported `COMPLETED` status is
  never sufficient alone; at least one of the web/database/file validation
  legs (`playwright_validator`, existing `db_adapter`, existing
  `file_adapter`) must independently confirm the expected end state before
  `RunEngine` marks the run passed.

Sequencing note: 21b depends on the same Playwright dependency as 20a/20b,
so 21 is naturally sequenced after or alongside Phase 20, not before it.

---

## 8. Remediation roadmap (Phases A–E) — supersedes/refines Phases 20–21's sequencing

This section records a five-phase remediation plan covering both the
outstanding audit issues (roadmap items 1.1–1.11, referenced throughout
`decisions.md`) and the Phase 20/21 work above, in an explicit priority
order. Phases C and E below are the same work as Phase 20 and Phase 21
respectively — this section exists to record the *sequencing decision*
(safety fixes and planner cleanup first, then the large Playwright change,
then offline hardening, then Automation Anywhere last), not to duplicate
their technical design, which stays in TRD.md §10/§11.

- **Phase A — Safety/correctness fixes.** ✅ **DONE, 2026-07-13** — see
  `decisions.md` D-017. Secrets split (vault key vs. JWT secret),
  `cloud_adapter.py` gained a real `list_objects` action (detect-only,
  matching its documented design — mutating actions deliberately not
  added), `db_adapter.py` hardened against mutating functions hidden
  inside a SELECT, and a real data-flow bug between `db_adapter.py` and
  `cross_modal_diagnoser.py` was found and fixed (the `healing_hints`
  dict was missing the `exception` key the diagnoser's regex needed).
- **Phase B — Remove Anthropic from the Planner, local LLM only.** ✅
  **DONE, 2026-07-13** — see `decisions.md` D-018. `AnthropicBackend` and
  `settings.allow_network_calls` removed entirely (not disabled). The
  Planner now has exactly two backends: `heuristic` and `local_llm`.
- **Phase C — Playwright interaction layer.** Not started. Same work as
  §6 Phase 20 above (20a/20b specifically). This is now the largest
  remaining item in this roadmap.
- **Phase D — Offline hardening & API boundary.** ✅ **DONE, 2026-07-14**
  — see `decisions.md` D-020. Added the hard kill-switch
  (`settings.capability_adapters_enabled`) and egress allowlist
  (`settings.allowed_capability_hosts`), enforced at
  `orchestrator/capability_router.py::route_capability` (the single
  chokepoint every capability adapter is dispatched through), plus
  audit-logged every permitted capability call's target host + UTC
  timestamp (never payload contents) via `orchestrator/audit_logger.py`.
  Turned out not to actually depend on Phase C landing first — Phase C's
  Playwright work is a local browser-automation surface, not a new
  outbound capability target, so Phase D's real scope was entirely the
  pre-existing `agents/capability/*.py` adapters. Known documented gap:
  `azure_adapter`/`gcp_adapter` authenticate via SDK default-credential
  chains rather than an explicit host param, so their calls can't be
  host-allowlisted yet (kill switch still covers them).
- **Phase E — Automation Anywhere trigger/validate.** Not started. Same
  work as §7 Phase 21 above. Deliberately sequenced last — lowest
  urgency, and 21b depends on Phase C's Playwright session/locator code.
  Inherits Phase D's kill switch/allowlist automatically once picked up,
  since it routes through the same `route_capability` chokepoint.

**Current status (2026-07-14): A, B, C, and D done; E not started.** Each
phase gets its own `decisions.md` entry before code changes, and the
existing test suite is kept green throughout rather than batching
everything into one untested drop — Phase D added 16 new tests on top of
the existing suite: **300/309 passing** (the 9 failures are the
pre-existing Phase C Playwright/Chromium tests, which fail in a sandboxed
environment only when its own network rules block the one-time Chromium
binary download — not a Phase D regression; confirmed by running the
identical 9-failure baseline before touching any Phase D code).
