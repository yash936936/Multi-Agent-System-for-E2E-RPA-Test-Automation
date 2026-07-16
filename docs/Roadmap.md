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

## 6. Phase 20 (delivered as Phase C, 2026-07-14) — Navigation redesign + observability, from external reference research

Backed by verified research across 18 external repos, 6 batches, documented
in full in `docs/external_repos.md`. **Status: delivered.** Implemented as
"Phase C" in the A–E remediation roadmap (§8 below) — see `docs/decisions.md`
D-019 for the actual implementation record. `docs/TRD.md` §10 documents the
technical design this phase implemented (note: as of this Roadmap.md pass,
TRD.md §10's own status line is a known separate staleness gap, still
reading "proposed" — flagged for a follow-up doc pass, not yet fixed here).

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

## 7. Phase 21 (delivered) — Automation Anywhere trigger/validate architecture

Full technical design in `docs/TRD.md` §11. Status: **delivered** — see
`docs/decisions.md` D-021 (21a/21b) and D-023 (21c).

- **21a. `agents/capability/automation_anywhere_adapter.py`** (delivered) —
  `CapabilityType.AUTOMATION_ANYWHERE`, triggers a bot via the Control Room
  REST API or the local AAE CLI, polls to terminal status.
- **21b. `agents/capability/playwright_validator.py`** (delivered) —
  read-only Playwright-based post-run check against the web app's expected
  state (`CapabilityType.WEB_VALIDATION`). Still manages its own browser
  lifecycle independently of Phase 20a's locator work (`dom_locator.py`) —
  sharing that code is a legitimate small follow-up, not yet done.
- **21c. Validation-leg cross-check** (delivered, D-023) — a bot-reported
  `COMPLETED` status is never sufficient alone. `TestStep.bot_validation_group`
  links a trigger step to its validation-leg step(s)
  (`playwright_validator`/`db_adapter`/`file_adapter`); `RunEngine`
  retroactively downgrades the trigger step's result if none of its
  grouped legs independently confirm the expected end state before the
  run is marked passed. Opt-in — specs that don't set the field are
  unaffected.

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
- **Phase C — Playwright interaction layer.** ✅ **DONE, 2026-07-14** — see
  `decisions.md` D-019. Same work as §6 Phase 20 above (20a/20b). Playwright
  is now the primary interaction/self-heal path for browser targets
  (`runtime/hooks/browser.py`, `agents/vision/dom_locator.py`,
  `runtime/hooks/interact.py`'s `dom_*` primitives), with the OCR/pixel
  pipeline retained as the fallback for non-browser targets.
  `link_checker.py` gained a Playwright-render fallback for client-rendered
  pages.
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
- **Phase E — Automation Anywhere trigger/validate.** ✅ **DONE,
  2026-07-14** — see `decisions.md` D-021. Found, on inspection, that both
  adapters (`automation_anywhere_adapter.py`, `playwright_validator.py`)
  and their registration were already correct and complete (13 pre-existing
  tests) from the earlier Phase C conflict-fix; this pass closed the
  remaining gaps: added the missing `control_room_url` param key to Phase
  D's egress-controlled `_URL_PARAM_KEYS` (it wasn't covered before),
  confirmed CLI-mode triggers correctly have no extractable host and rely
  on the kill switch alone, updated `docs/WORKFLOW.md`'s capability-type
  example list to mention Automation Anywhere/web-validation explicitly,
  and added 4 new tests. **All five phases of the original remediation
  roadmap are now complete.**

**Current status (2026-07-14): A, B, C, D, and E all done.** Each phase
got its own `decisions.md` entry before code changes, and the existing
test suite was kept green throughout rather than batching everything into
one untested drop — Phase E added 4 new tests on top of the existing
suite: **304/313 passing** (the 9 failures are the pre-existing Phase C
Playwright/Chromium tests, which fail in a sandboxed environment only
when its own network rules block the one-time Chromium binary download —
not a regression from any phase in this roadmap).

**Remaining follow-ups noted but not required by the original roadmap:**
consolidating `playwright_validator.py` onto the same shared browser-context
module as Phase C's `dom_locator.py`/`browser.py` (a refactor-for-consistency
item, TRD §11.5), and resolving the Azure/GCP host-allowlisting gap noted
in D-020/D-021 for those two SDK-based adapters specifically.

## 9. Second remediation roadmap (Phases G–M) — gap-analysis-derived, against a full-featured autonomous QA agent checklist

Continues the same numbering/sequencing discipline as Phases A–E above
(`decisions.md` last used D-024 before this roadmap started, `STATUS.md`
last used "Phase F" for the bug-hunt pass) — low-risk/independent work
first, shared-state-sensitive work isolated in its own phase, mechanically
similar new capability adapters batched together at the end. Each phase
gets its own `decisions.md` entry; the test suite stays green throughout;
not a phase: native desktop/mainframe automation stays an explicitly
documented gap (no plan offered, no fabricated fix).

- **Phase G — Foundational, zero-shared-state additions.** ✅ **DONE,
  2026-07-14** — see `decisions.md` D-025 (G1)/D-026 (G2)/D-027 (G3). G1:
  environment-profile management (`AURA_ENV`/`--env`, layered
  `.env.<profile>` over base `.env`). G2: CI/CD-native mode (`--junit-out`,
  documented 0/1/2 exit-code convention). G3: real Pillow-based pixel-diff
  visual regression (replacing the SHA-256 hash-only check), baseline image
  storage, diff-image panel in the report.
- **Phase H — Cross-run analytics.** ✅ **DONE, 2026-07-15** — see
  `decisions.md` D-028 (H1)/D-029 (H2). H1: trend analytics (pass-rate over
  time, per-test history) built on `api/run_store.py`'s existing SQLite
  data, new API routes + dashboard chart. H2: flaky-test detection
  (`get_flaky_candidates()`, outcome-transition-based) + opt-in quarantine
  (`aura skills quarantine <test_id>`, `--all` skips by default,
  `--include-quarantined` overrides). H2 depends on H1's query layer, kept
  as one phase.
- **Phase I — Browser coverage.** ✅ **DONE, 2026-07-15** — see
  `decisions.md` D-030. I1: cross-browser support — `settings.playwright_browser`
  (`chromium`/`firefox`/`webkit`), `--browser` flag on `aura execute`/`aura
  explore`, `runtime/hooks/browser.py` launches the configured engine
  instead of hardcoded Chromium. I2: video recording — `settings.record_video`
  (off by default) + `--record-video` flag; the DOM/Playwright path records
  a real video natively via `record_video_dir`; the OS/pixel fallback path
  produces an honestly-labeled step-boundary **slideshow**
  (`runtime/hooks/video_recorder.py`), never claimed as continuous
  recording. Grouped I1+I2 because both touch `runtime/hooks/browser.py`'s
  session setup directly. **Known gap, disclosed rather than silently
  skipped:** the existing Phase C Playwright test suite has not been
  parametrized to actually run against real Firefox/WebKit binaries in
  this environment — only Chromium's binary is downloaded here (a
  sandbox network-egress restriction, same class of gap noted throughout
  this roadmap for Chromium itself in earlier phases), so Phase I's new
  tests verify the engine-selection *dispatch logic* directly (a mocked
  Playwright instance proves the correct engine is requested) plus a real,
  live failure-path test confirming an uninstalled engine fails as a clean
  `NoDisplayError` rather than a crash — not a full three-engine live
  parametrization of every existing Phase C test.
- **Phase J — Parallel execution.** ✅ **DONE, 2026-07-15** — see
  `decisions.md` D-031. Removed the API layer's `RunEngine` singleton
  (`api/routers/runs.py`) — every background task now gets its own fresh
  instance instead of serializing behind one shared lock. Reviewed
  `LoopGuardrail._states`'s `step_id`-only keying and found it already
  safe (every call site already constructs a fresh, per-run instance) —
  documented as verified rather than changed. Added `aura execute --all
  --parallel N` using `ThreadPoolExecutor` (I/O-bound work, threads are
  correct here, not multiprocessing).
- **Phase K — Multi-tenant / fine-grained RBAC.** ✅ **DONE, 2026-07-15** —
  see `decisions.md` D-032. Extended `api/security.py`/`api/user_store.py`'s
  role model to an opt-in project-tag permission matrix
  (`TestSpec.project_tag` + `TokenPayload.allowed_project_tags`),
  additive and backward-compatible (untagged specs/unrestricted users
  behave exactly as before). New admin-only
  `PUT /api/v1/users/{username}/project-tags` endpoint, enforced at both
  the run-creation write path and the run-listing/detail read paths.
- **Phase L — New capability adapters (batched).** ✅ **DONE, 2026-07-16**
  — see `decisions.md` D-033. L1: accessibility
  (`agents/capability/accessibility_adapter.py`, real axe-core scan,
  vendored locally at `vendor/axe-core/` — not CDN-loaded, matching AURA's
  offline-first posture). L2: passive security headers
  (`agents/capability/security_headers_adapter.py` — header presence,
  cookie flags, common exposed-path checks; explicitly no payload
  injection/active probing, enforced by a dedicated test that fails if any
  non-GET request is issued). L3: performance budget
  (`agents/capability/performance_adapter.py` — single-page Navigation
  Timing metrics against a configurable budget; explicitly not multi-user
  load generation). Batched because the registration pattern (new
  `CapabilityType` enum entry + `default_registry()` registration) is
  what's repeated, not the underlying logic — turned out to be a two-way
  registration in practice, not three: `config/tool_registry.yaml` already
  has a single generic `Capability.check` entry shared by every capability
  adapter since Phase 14, so no per-adapter tool-registry changes were
  ever needed here (or for any capability adapter before it).
- **Phase M — Test-case-management adapter.** Not started. Lowest
  confidence, last on purpose:
  `agents/capability/defect_tracker_adapter.py`, generic REST +
  field-mapping config for Jira/TestRail/Zephyr/Xray-style tools. Will be
  verified only against a mocked HTTP server — `decisions.md` will state
  plainly that live-integration correctness is unverified (no real account
  available to test against).

**Current status (2026-07-16): G, H, I, J, K, L, and M all done. The entire second remediation roadmap (Phases G–M) is complete — see `docs/decisions.md` D-034 for Phase M's `defect_tracker_adapter.py` (generic REST + field-mapping for Jira/TestRail/Zephyr/Xray-style tools, verified only against a mocked HTTP server, lowest confidence by design).**

## 10. Third remediation roadmap (Phases N–Q)

Continues the same sequencing discipline as Phases A–M above (`decisions.md`
last used D-034 before this roadmap started): low-risk/read-only work last,
the one genuinely new write-path capability isolated in its own phase
(same elevated-care treatment Phase J/K got), and file-touch grouping
preferred over feature grouping where two items live in the same module.

- **Phase N — Automation Anywhere adapter completeness (auth +
  multi-trigger).** ✅ **Done.** See `docs/decisions.md` D-035. Both items
  live inside `automation_anywhere_adapter.py`'s request/poll internals —
  one careful pass through that file instead of two, same reasoning as
  Phase I grouping browser-engine choice with video recording.
  - **N1. Control Room authentication.** Add a real login step (calls
    Control Room's `/v1/authentication` endpoint with username/password
    or an API key) to acquire a token instead of requiring the caller to
    pre-supply one. The token is cached with its expiry on the adapter
    instance and the adapter auto-re-authenticates on a 401 during
    deploy/poll rather than failing the whole run. `auth_token` remains a
    valid, optional override for anyone already supplying one directly —
    additive, not a breaking change to the params contract.
  - **N2. Multi-bot / multi-runner trigger.** `bot_id` and
    `run_as_user_id` accept either a scalar (unchanged) or a list, so one
    request can genuinely fan out to multiple bots and/or multiple Bot
    Runner VMs. The poll loop tracks every resulting deployment id
    independently — no longer reads `records[0]` and silently drops the
    rest — via a per-target status map. `expected.rollup` selects
    `all_must_complete` (strict, default) or `any_must_complete` (fan-out
    redundancy use case), since "did the whole trigger succeed" means
    different things depending on why you fanned out in the first place.
    Evidence carries a per-target breakdown, not just one aggregate
    status, so a failing target among several successes stays visible
    rather than getting swallowed.
- **Phase O — Data seeding adapter (new capability, its own phase).** ✅
  **Done.** See `docs/decisions.md` D-036. Its own phase because it's the
  one item here that introduces AURA's first-ever intentional write path
  to a database — the same elevated care level Phase J (shared state) and
  Phase K (auth) got.
  - New `agents/capability/db_seed_adapter.py`, a distinct
    `CapabilityType.DB_SEED` — not a loosening of `db_adapter.py`'s
    existing read-only hardening. That adapter stays exactly as strict as
    it is today.
  - Structured input only, not raw SQL text: params describe a table
    plus a values dict (or a list of row-dicts), and the adapter builds a
    parameterized INSERT itself — this closes off the injection surface a
    free-text query string would reopen, rather than just re-adding the
    old denylist-based guard.
  - Explicit opt-in required at the settings level (off by default, e.g.
    `settings.allow_db_seeding`), independent of the general
    `capability_adapters_enabled` kill switch — a second, deliberate gate
    specifically for the one adapter that writes.
  - Every seed operation gets its own audit log entry (reusing
    `orchestrator/audit_logger.py`), including the exact rows written —
    this is the adapter most worth having a paper trail for.
  - Only INSERT — explicitly no UPDATE/DELETE/DDL, even structured.
    Precondition setup means creating rows that didn't exist, not
    mutating or erasing existing ones.
- **Phase P — Control Room audit log retrieval + report sync.** ✅ **Done.**
  See `docs/decisions.md` D-037. Lower risk than N/O (read-only against
  Control Room), grouped as one phase since both halves are about the same
  "data synchronization" arrow in the architecture diagram (docs/TRD.md §11).
  - **P1.** Fetch Control Room's own audit-log entries for a given
    deployment ID after the poll reaches a terminal state — a new
    read-only call, no new write capability.
  - **P2.** Merge that into AURA's own `RunReport` (a new
    `report_paths`/evidence key, e.g. `control_room_audit`) so one AURA
    report actually contains both trails side by side, instead of Control
    Room's audit history existing only inside AA's own system with
    nothing on AURA's side to show it.
- **Phase Q — Playwright native trace files.** ✅ **Done.** See
  `docs/decisions.md` D-038. Touches `runtime/hooks/browser.py` again
  (same file Phase I's video recording lives in), but scoped separately
  since it's a distinct feature, not a bug fix to I2.
  - New `settings.record_trace` flag (off by default, same posture as
    `record_video`).
  - Wire `context.tracing.start(screenshots=True, snapshots=True)` at
    session start and `context.tracing.stop(path=...)` at close(),
    parallel to the existing video-recording lifecycle.
  - Attach the resulting `.zip` trace path under `report_paths["trace"]`,
    completing the diagram's "(Screenshots, Videos, Trace files)" label
    for real, matching what's already true for the other two.

**Current status (2026-07-16): Phases N, O, P, and Q are all done (see
`docs/decisions.md` D-035, D-036, D-037, D-038). The entire third
remediation roadmap (Phases N–Q) is complete.**

---

## Fourth remediation roadmap — Phases R–V

Continuing the letter sequence after Phase Q (last landed phase,
`decisions.md` D-038). Sequenced by dependency, not just priority: the two
exception/guard-unification bugs go first since later phases touch the
exact same code paths and should build on the fixed version, not the
broken one.

One note on the corrected Idea 1 (Phase U): OCR-then-DOM in sequence, both
always run, results compiled together — the reverse order from Phase C's
current DOM-first/OCR-fallback architecture. Built exactly as specified.

### Phase R — Safety/correctness quick fixes (small, independent, do first)

- **R1.** Automation Anywhere poll-loop busy-spin fix. Clamp
  `poll_interval_seconds` to a sane floor (`max(poll_interval_seconds,
  1.0)`) inside `_poll_rest_status_multi` itself — not just documented as
  an expected value. Direct fix for the `KeyError: 'targets'` failure in
  `test_n2_timed_out_target_reported_independently_of_completed_target`.
- **R2.** Investigate the test-isolation mystery alongside the fix.
  Confirm the fix resolves it both in isolation and in the full suite —
  and if the isolation-vs-full-suite discrepancy persists even after the
  real bug is fixed, chase that down too rather than letting a fixed bug
  mask a separate ordering issue.
- **R3.** Planner retry/escalation logging. Every retry inside
  `generate_spec`'s validation-failure loop gets a logged reason (schema
  validation error, timeout, exception type) instead of retrying silently.
  Small, no architecture change, but a prerequisite for Phase V's
  escalation policy being trustworthy/auditable rather than a black box.

Why first: all three are small, self-contained, and carry zero risk to
anything else — the same "smallest risk, unblocks nothing else, but
removes real bugs before bigger changes land on top" pattern the very
first remediation phase (Phase A) already established.

### Phase S — Display/screenshot-guard unification (closes a whole bug class, not one instance)

- **S1.** Unify `NoDisplayError`. One shared `runtime.errors.NoDisplayError`,
  imported everywhere. Every current per-module duplicate
  (`runtime.hooks.interact`, `runtime.hooks.browser`, and the third one)
  gets replaced with the shared class, not a new duplicate.
- **S2.** Shared screenshot-acquisition guard. A single context
  manager/decorator that every screenshot call site uses, built around
  S1's unified exception. This is the structural fix behind what D-022
  and D-024 each patched piecemeal.

Why S1 before S2: the shared guard needs the unified exception to exist
first. Why S before U: Phase U is about to become the single most
frequently-executed piece of display-touching code in the whole system —
it should be built against the unified guard, not the fragmented one.

### Phase T — Spec-level action/target-type validation pass

**Status (2026-07-17): done.** See `docs/decisions.md` D-042.

New pre-execution validation step (not per-step at runtime) that checks
action/target-type compatibility across the whole spec before any step
runs — e.g. a `VISUAL_CLICK` step pointed at something that should have
been a `CapabilityType.AUTOMATION_ANYWHERE` check fails fast with a
specific, actionable message, instead of burning through the entire
vision pipeline and failing with a confusing OCR/DOM miss. Independent of
R and S — can land in parallel with either, but sequenced here since it's
lower urgency than the display-guard bug class.

### Phase U — OCR-then-DOM dual verification, results compiled (redesigned Idea 1)

**Status (2026-07-17): done.** See `docs/decisions.md` D-043.

Replace the current DOM-first/OCR-fallback chain with: run OCR, then run
DOM, sequentially, every time (not conditionally) — then compile/reconcile
both results before deciding the step's outcome.

Compilation rule: both agree (overlapping location) → strongest
confidence, dispatch. Both find something but disagree → log both
candidates as evidence, apply the configured tie-break, never silently
trust one over the other without recording the disagreement. Only one
finds it → proceed, but tag the result "single-method" vs.
"dual-method-confirmed" in evidence. Neither finds it → escalate.

This fully replaces the smaller "fresh DOM re-check before escalating"
idea from last time. Depends on Phase S (built on the unified display
guard) and benefits from Phase R3's logging (the disagreement/tie-break
reasoning needs a logged reason, not a silent decision). Largest phase
here — touches `agents/vision/executor.py`, `agents/vision/locator.py`,
`agents/vision/dom_locator.py`, and the report template.

### Phase V — Dual API + local LLM generic backend

Generic OpenAI-compatible HTTP client (no SDK, no hardcoded vendor),
`AURA_CLOUD_LLM_BASE_URL`/`_API_KEY`/`_MODEL`/`AURA_ENABLE_CLOUD_PLANNER`/
`AURA_PLANNER_PRIORITY`/`AURA_REQUIRE_LLM_BACKEND` env vars, a detection
matrix, local-first/cloud-escalation policy, and reuse of Phase D's
existing egress-allowlist mechanism rather than a second one.

Depends on Phase R3 — the escalation policy this phase introduces is
exactly what R3's "why did this retry/escalate" logging exists to make
trustworthy. Otherwise independent of S/T/U — touches the planner, not
the vision pipeline — so it could run in parallel with those, but
sequenced last here since it's net-new capability rather than fixing
something already shipped and load-bearing.

Each phase gets its own `decisions.md` entry (continuing at D-039) once
actually built; the existing test suite stays green throughout.

**Phase R status (2026-07-16): done.** See `docs/decisions.md` D-039.
**Phase S status (2026-07-16): done.** See `docs/decisions.md` D-040 (S1) and D-041 (S2).
**Phase T status (2026-07-17): done.** See `docs/decisions.md` D-042.
**Phase U status (2026-07-17): done.** See `docs/decisions.md` D-043.
**Current status (2026-07-17): R, S, T, and U are all done. Phase V (dual API + local LLM generic backend) is next and last.**
