---
type: status
project: AURA
last_updated: 2026-07-14
---

# STATUS

> This file should always reflect the *current* state — overwrite freely, don't accumulate history here (that belongs in `progress.md`).

## Where things stand (2026-07-14 update)
- **Phases G1–G3 landed (this pass, see `docs/decisions.md` D-025/D-026/D-027):** the first three phases of the second remediation roadmap (gap-analysis-derived Phases G–M). **G1 (environment profiles)** and **G2 (CI/CD JUnit output)** were found already partially/fully coded from earlier in this same work session but undocumented and, for G2, unwired/untested — this pass finished the wiring, wrote the missing tests, and documented both. **G3 (real pixel-diff visual regression)** was built from scratch. A real latent bug was found and fixed in G2's pre-existing `junit.py`: its self-heal detection read a `healed_via` field that `VisionActionResult` never actually has, so that branch was permanently dead code — same bug class as D-017's `db_adapter`/`cross_modal_diagnoser` finding (a field referenced by name that the producing module never populates). `aura execute` also gained its first-ever documented, enforced exit-code convention (previously always exited 0 regardless of outcome). **351/360 tests passing** (20 new this pass; the 9 failing/erroring are the same pre-existing Phase C Playwright/Chromium sandbox-only failures noted throughout this file — zero new regressions).
- **Follow-up fix (this pass, see `docs/decisions.md` D-024):** two more unguarded `screenshot_provider(...)` call sites found and fixed, in files D-022's pass didn't touch — `orchestrator/autoscan.py::run_autoscan` (behind `--scroll-test` and `aura explore`'s page-scan) and `orchestrator/ui_audit_runner.py::_run_click_audit` (behind `--ui-audit` and `aura explore`'s element-clicking pass). Both now catch `NoDisplayError` cleanly instead of crashing; `AutoScanReport` gained a `display_unavailable` field so callers can show an accurate message instead of conflating "no display" with "hit the scan limit." Live-reproduced and confirmed fixed: `aura explore <url>` with no display connected now exits 0 with a valid report instead of a raw traceback. **321/330 tests passing** (3 new; the 9 failures are the same pre-existing Phase C Playwright/Chromium sandbox-only failures noted throughout this file — confirmed via `git stash` that the true before-state for this pass was 318/327, so this is a net +3 passing, zero regressions).
- **Phase 21c closed (this pass, see `docs/decisions.md` D-023):** RunEngine now enforces the last open piece of the Automation Anywhere trigger/validate architecture — a bot's own reported success is no longer sufficient alone. New `TestStep.bot_validation_group` field links a trigger step to its validation-leg step(s); `RunEngine._enforce_bot_validation_cross_check()` retroactively downgrades a trigger step's result if none of its grouped validation legs independently confirmed the expected end state. Opt-in (specs without the field are unaffected). **327/327 tests passing**, 6 new.
- **Phase F (this pass, see `docs/decisions.md` D-022):** three real bugs found via live command-by-command testing, all fixed — `aura debug --out` silently skipped clean scans, `orchestrator/run_engine.py` crashed the whole run on a missing display instead of escalating gracefully (5 unguarded `screenshot_provider` call sites), and `aura explore` died silently (exit 1, no traceback) because `pyautogui`'s `mouseinfo` dependency raises `SystemExit` (not `Exception`) when tkinter is missing on Linux, which nothing caught. Also added non-fatal display/Playwright/adapter-dependency checks to `aura/cli/preflight.py`, which previously only checked Tesseract and the planner backend. **321/321 tests passing**, 10 new.
This pass (see `docs/decisions.md` D-018/D-019 for full detail):
- **Phase A** (secrets split, cloud_adapter S3-action branching, cross_modal_diagnoser dead-code/real-bug fix, db_adapter hardening) — verified already correctly implemented from a prior pass, code and tests match the roadmap's fix plan.
- **Phase B** (removed `AnthropicBackend`/`allow_network_calls` entirely, `local_llm`/`heuristic` are the only planner backends) — verified already correctly implemented.
- **Conflict found and fixed:** `automation_anywhere_adapter.py` / `playwright_validator.py` (Phase E, TRD §11) existed fully written but were never registered in `CapabilityType`/`default_registry()`, breaking `pytest` collection. Fixed minimally (enum + registration) — full Phase E wiring/docs pass still deferred.
- **Phase C landed:** Playwright is now the primary interaction/self-heal path for browser targets (`runtime/hooks/browser.py`, `agents/vision/dom_locator.py`, `runtime/hooks/interact.py`'s `dom_*` primitives, `agents/vision/executor.py`), with the OCR/pixel pipeline retained as the fallback for non-browser targets. `link_checker.py` gained a Playwright-render fallback for client-rendered pages. **293/293 tests passing** (280 pre-existing + 13 new, all Phase-C tests run against real local Chromium, not mocks).
- **Phase D landed (2026-07-14, see `decisions.md` D-020):** capability-adapter egress controls — a hard kill switch (`settings.capability_adapters_enabled`) and an opt-in host allowlist (`settings.allowed_capability_hosts`), both enforced at `orchestrator/capability_router.py::route_capability` (the single chokepoint every adapter dispatches through), plus audit logging of each permitted call's target host + UTC timestamp (never payload contents) to `orchestrator/audit_logger.py`. Turned out not to actually need Phase C first — Phase C's Playwright surface is local browser automation, not a new outbound capability target, so Phase D's scope was entirely the pre-existing `agents/capability/*.py` adapters. Documented gap: `azure_adapter`/`gcp_adapter` use SDK default-credential chains rather than an explicit host param, so they can't be host-allowlisted yet (kill switch still covers them). 16 new tests in `tests/test_capability_egress_controls.py`. **300/309 tests passing** — the 9 failures are the pre-existing Phase C Playwright/Chromium tests, which fail only in sandboxes whose own network egress rules block the one-time Chromium binary download; confirmed unrelated to Phase D by reproducing the identical 9-failure baseline before any Phase D code was touched.
- **Phase E landed (2026-07-14, see `decisions.md` D-021):** Automation Anywhere trigger/validate closure — the adapters (`automation_anywhere_adapter.py`, `playwright_validator.py`) and their registration were already correct and complete from an earlier conflict-fix pass; this pass added the missing `control_room_url` param key to Phase D's egress allowlist coverage, confirmed CLI-mode triggers correctly rely on the kill switch alone (no host to allowlist), updated `docs/WORKFLOW.md`'s capability-type example list, and added 4 new tests. **All five phases of the original remediation roadmap (A/B/C/D/E) are now complete. 304/313 tests passing** — same 9 pre-existing sandbox-only Chromium failures, zero regressions.

## Where things stood before this pass

AURA has grown well past the original CLI-only MVP described in earlier revisions of this file. It is now two things in one repo:

1. **The original offline CLI tool** (Phases 1–12): Planner/Vision/DataSynth agents, self-healing loop, live-URL testing, UI audit, code bug detection, scheduling, reporting. Still fully working, still the recommended way to run AURA today.
2. **A "universal QA platform" backend** (Roadmap.md Phases 13–19): capability adapters for non-UI systems, and a FastAPI service layer with a web dashboard. **This was previously undocumented — this update reconciles the docs with what the code actually contains.**

### Capability adapters (Roadmap Phases 13–16) — implemented and tested
`orchestrator/schemas.py` (`CapabilityType`, `CapabilityCheckInput`/`CapabilityCheckResult`, `TestStep.capability_type`/`target`/`expected`), `orchestrator/capability_router.py` (`route_capability`, dispatches to the registry), `orchestrator/capability_adapter.py` (registry + protocol), and real adapters under `agents/capability/`: `api_adapter`, `db_adapter`, `email_adapter`, `file_adapter` (local + SFTP via paramiko), `excel_adapter`, `pdf_adapter`, `cloud_adapter` (S3, detect-only), `workflow_adapter` (generic webhook trigger), plus `fake_adapter` for routing tests. `orchestrator/run_engine.py` routes `CAPABILITY_CHECK` steps through this path with cross-modal self-healing (`agents/planner/cross_modal_diagnoser.py`, Roadmap Phase 18) up to 2 heal attempts before escalating. All 16 app-category verification cases in `tests/test_16_categories_verification.py` pass.

### Autonomy modes (this pass) — implemented and tested
Two new, genuinely different modes, not just "pauses more or less":
- **`aura explore <url>`** (new command, `aura/cli/explore_cmd.py`) — zero-instruction autonomous exploration. Generalizes `orchestrator/ui_audit_runner.py`'s click-and-diff engine (previously nav+footer only, for `--ui-audit`) into `run_exploration()`, which test-clicks every interactive-looking element across all bands (nav/hero/footer/body), plus an optional `--prompt` keyword-heuristic check (disclosed as a heuristic in its own output, not sold as language understanding). No HTML report yet -- outputs a terminal summary + JSON under `reports/explore_<run_id>/report.json`.
- **`aura execute --interactive`** (new flag) — human-in-the-loop. New `ActionType.WAIT_FOR_HUMAN_ACTION` step type (`orchestrator/schemas.py`), executed by a new polling branch in `RunEngine.run_spec()` (`orchestrator/run_engine.py`): re-screenshots every `settings.human_action_poll_interval_seconds` (default 2s) until the screen changes or an optional `--timeout` elapses (default 0 = wait indefinitely). `RunEngine.run()` was split into `run()` (planner + data synth) and the new public `run_spec()` (execution loop only), so `--interactive` mode can hand-build a spec and skip the planner entirely.
- **`--autonomous`** — explicit alias for `--yes`, so Mode A has a self-documenting name distinct from Mode B's `--interactive`.
- Documented explicitly in README.md's new "Autonomy modes" section, including the pre-existing `auto_approve=True` hardcoding in `execute_prompt()`/`--yes` -- that behavior is correct for Mode A and was not a bug; the actual gap (no zero-instruction mode, no way to deliberately hand control to a human) is what these two features close.
- 8 new tests (`tests/test_human_in_the_loop.py`, plus additions to `tests/test_ui_audit_runner.py`). **205/205 tests passing.**

### Link check fix (2026-07-05) — scope, redirects, client-rendered pages
Real user-reported bug: `aura explore` was silently only ever checking `<footer>` links (hardcoded default at two call sites, despite `LinkCheckAdapter` itself already defaulting to `"all"`), and gave a misleading "no links found" message on client-rendered (React/Next.js) pages where links are JS-injected rather than present in the raw HTML AURA fetches. Fixed: default scope is now `"all"` everywhere (exposed as `--link-scope` on `aura explore`), redirect chains are now reported per-link instead of silently followed, and a marker-based heuristic now gives an honest, explicit explanation when a page looks client-rendered instead of a bare "nothing to check" result. **Not fixed, by design decision, not oversight:** actually seeing JS-injected links on a client-rendered page would require a headless-browser render step (e.g. Playwright) — a real architecture change (new heavy dependency, different automation posture) flagged for a separate decision, not silently bundled in. **244/244 tests passing.**

### Service layer (Roadmap Phase 17) — **implemented but incomplete, not production-ready**
`api/main.py` is a real FastAPI app (`AURA Universal QA Platform`, mounts `webui/static`, serves `webui/templates/index.html`) with routers for `POST/GET /api/v1/test-runs`, webhooks, and adapter status, plus JWT-based auth and per-tenant run isolation (`api/security.py`). This exists in code but was never reflected in STATUS/progress/Roadmap or README until now, and has real gaps:

- **`POST /api/v1/test-runs` does not actually run anything.** `api/routers/runs.py::execute_run()` is a stub — it flips status to `"running"` then unconditionally to `"passed"` with a `# Hook into RunEngine here...` comment. It never calls `RunEngine`. Every submitted run reports success regardless of the spec. **This is the single most important gap to close before this API is usable for anything real.**
- **No way to obtain a token.** `api/security.py::create_access_token()` exists but no endpoint calls it — there is no `/auth/login` or `/token` route. Every other endpoint requires a Bearer JWT via `require_role`/`get_current_user`, so the API is not actually callable end-to-end from a cold start.
- **No CLI or documented way to start the server.** `uvicorn` is a dependency and `api/main.py` is importable, but there's no `aura serve` command and (until this pass) no README instructions. Starting it requires already knowing `uvicorn api.main:app`.
- **Secrets/signing key reuse.** `SecretVault`'s Fernet key doubles as the JWT HMAC secret (`JWT_SECRET = vault.get_jwt_secret()`), conflating "encrypt stored credentials" with "sign auth tokens." Works, but is not the secrets separation Roadmap.md Phase 17 calls for.
- The web dashboard (`webui/templates/index.html`) is a single static page; no live status/report viewer is wired to it yet.

None of the above are correctness bugs in the sense of throwing exceptions — the service starts and responds — but the run-execution stub means **the API currently cannot be relied on to actually test anything.** Treat it as a scaffold, not a working feature, until `execute_run` is wired to `RunEngine` and a login endpoint exists.

## 156 → 199 tests
Test count grew from 156 (last recorded in progress.md, pre-adapters) to **199/199 passing** as of this update, covering the CLI/vision/reporting suite plus the new capability-adapter, router, kernel-dispatch, cloud/workflow-adapter, and cross-modal-healing tests. `pyflakes` clean except 4 pre-existing unused-variable warnings in `cross_modal_diagnoser.py` and `cloud_adapter.py` (dead branches — see "Needs review" below).

## What's fully working (verified by tests, not just present)
Everything in the "Since then" section of the previous revision of this file (live URL testing, UI audit, scroll scan, code bug detection, scheduling, reporting) — unchanged, still accurate — **plus**, as of this pass: schema-level capability routing, all 9 capability adapters against mocked backends, and cross-file consistency between `TestStep`, `CapabilityCheckInput`, and `CapabilityCheckResult` (previously broken — see decisions.md / progress.md 2026-07-04 entry).

## Next action
> Pick one, in priority order given the gaps above:
> 1. **Wire `api/routers/runs.py::execute_run()` to the real `RunEngine`** — this is the one item that makes the service layer actually functional instead of a demo shell.
> 2. **Add a `/auth/login` (or equivalent) endpoint** that calls `create_access_token()`, and an `aura serve` CLI command, so the API is reachable without out-of-band knowledge.
> 3. Run a real `--ui-audit` pass against a live external site with a display available (carried over, still open).
> 4. Reconcile README.md's CLI reference and add the adapter/service-layer sections (**done in this pass** — verify it stays current going forward).

## Blockers / open questions
- **Local LLM planner backend still needs a real verification run** (carried over, unchanged — `"heuristic"` remains the default and is fully verified).
- **Vault/repo conventions** — still no code repository link, license, or naming convention confirmed.
- **Service layer secrets design** — decide whether the vault key and JWT signing key should be split before this goes anywhere near production traffic.
- **Multi-tenant run store is in-memory** (`runs_store: dict` in `runs.py`) — restarting the API process loses all run history; no persistence layer wired yet despite `orchestrator/memory.py` already existing for the CLI path.

## Closed since last update
- (Carried over from 2026-07-03, still accurate: audit-trail gap D-007/D-008, live-display verification D-009, local LLM backend D-010, PIL file-handle leak D-011, PyInstaller packaging D-012.)
- **Schema drift across the capability-adapter path (this pass)** — `orchestrator/schemas.py` had been renamed from `CapabilityResult` to `CapabilityCheckResult`, but `capability_adapter.py`, `capability_router.py`, `fake_adapter.py`, and `config/tool_registry.yaml` still referenced the old name; `capability_router.py` also read a nonexistent `payload.step` attribute, and `TestStep` was missing the `target`/`expected` fields `run_engine.py` needed for capability-check steps. Fixed across all seven affected files, plus a stale test hash, a mocked-method mismatch in the workflow-adapter test, and unused imports. Full changelog in progress.md's 2026-07-04 entry. **199/199 tests passing after the fix.**

## New features this pass
(Carried over from 2026-07-03: skill-library diff, "Explain this test" narrative in reports — both still accurate.)

## Not yet implemented (deferred)
Carried over from 2026-07-03 (video/GIF diff, element-drift heatmap, multi-monitor profiles, local digest notifications, confidence-threshold auto-tuning) — **plus, newly identified in this pass:**
- Real `RunEngine` wiring inside the FastAPI service (see "service layer" above).
- Token-issuance endpoint / `aura serve` CLI command.
- Persistent (non-in-memory) run store for the API.
- Live dashboard wiring (the HTML page exists but isn't dynamic yet).

## Needs review
- Confirm personas in `README.md` still match actual intended users now that a service/API surface exists (compliance officer persona in PRD.md may care a great deal about the auth gaps above).
- Decide whether to fix `execute_run`'s stub behavior before advertising the API at all, or explicitly label it "preview, do not use for real runs" until it's wired up.
- `agents/planner/cross_modal_diagnoser.py` (`error_type`, `query`, `missing_col` assigned but unused) and `agents/capability/cloud_adapter.py` (`action` parsed but never branched on, so non-`s3_object_exists` actions silently fall through to the same code path) — flagged as product-decision items, not fixed silently.
- Confirm whether `PRD.md` should gain a v2.2 section for the capability-adapter/service-layer surface, since it currently only describes the original vision-first CLI scope.

---

## Update — Phases 15, 16b, 17: service layer wired for real, capability gaps closed, UI rewritten

This pass closes every gap flagged in the "Service layer (Roadmap Phase 17) — implemented but incomplete" section above, plus every gap identified in the standalone compatibility review against the Automation Anywhere application-category list.

### Phase 15 — API service layer is now real, not a stub
- `api/routers/runs.py::execute_run()` now calls the real `RunEngine.run_spec()` (background task), instead of unconditionally flipping to `"passed"`. A shared `RunEngine` instance is built once per process; a lock keeps vision-driven runs from overlapping (capability-only specs never touch it).
- `api/routers/auth.py` (new) — real `POST /api/v1/auth/login`, backed by `api/user_store.py` (new): a JSON-file user store, PBKDF2-hashed (stdlib `hashlib`, no new crypto dependency), auto-seeded with one `admin` user on first run (`AURA_ADMIN_PASSWORD` env var, or a generated password printed once to stderr).
- `api/run_store.py` (new) — SQLite-backed persistent run store (`memory/api_runs.db`) replacing the in-memory `runs_store: dict`. Restarting the process no longer loses run history.
- `api/spec_builder.py` (new) — normalizes the loose JSON body the HTTP API accepts into a real `TestSpec`, with friendly action aliases (`VISION_CLICK` → `visual_click`, etc.) and fail-fast validation (422, not a mid-run crash).
- `api/routers/adapters.py` rewritten to report the live registry (`orchestrator/capability_adapter.py::default_registry()`) instead of a hardcoded "healthy" dict.
- Verified end-to-end against a live local server: login → create run → RunEngine executes → real `RunReport` (with `report_paths` pointing at the actual JSON on disk) persists and is retrievable after the fact.
- New tests: `tests/test_api_service.py` (6 tests — login, real execution, validation, persistence-across-restart, adapter status).

### Phase 16b — Closed every adapter gap from the compatibility review
- `agents/capability/azure_adapter.py` (new) — real Azure Blob Storage: `blob_exists` (detect), `upload_blob`/`download_blob` (real read/write), `list_blobs`.
- `agents/capability/gcp_adapter.py` (new) — same action vocabulary against Google Cloud Storage.
- `agents/capability/sharepoint_adapter.py` (new) — real Microsoft Graph API integration (OAuth2 client-credentials, no `msal` dependency needed — raw `httpx` calls): `file_exists`, `upload_file`, `download_file`, `list_files`. This was explicitly called out as unsupported in the original review ("no dedicated API integration here").
- `agents/capability/chatops_adapter.py` (new) — real Slack Block Kit and Teams Adaptive Card (`MessageCard`) posting via incoming webhooks, distinct from the generic `workflow_adapter.py` POST.
- `agents/capability/pdf_adapter.py` — real OCR fallback wired in. Previously read metadata only; now, when `text_contains` is checked and the native text layer is empty (or `force_ocr=True`), it rasterizes each page via PyMuPDF (no poppler system dependency) and runs `pytesseract` against the image. Verified against a genuinely generated scanned-style PDF, not just mocked.
- New `CapabilityType` entries: `AZURE_BLOB`, `GCP_STORAGE`, `SHAREPOINT`, `CHAT_OPS`. All four registered in `orchestrator/capability_adapter.py::default_registry()`.
- `tests/test_16_categories_verification.py` updated: the "Document Mgmt (SharePoint)" and "Collaboration (Slack)" rows now route through the real dedicated adapters instead of File/Workflow stand-ins; two new rows added for Azure and GCP. **18/18 passing.**
- New tests: `tests/test_gap_adapters.py` (12 tests), `tests/test_pdf_ocr.py` (2 tests, including one real OCR extraction, not mocked).
- New dependencies: `azure-storage-blob`, `google-cloud-storage`, `pymupdf`.

Remaining honest gap from the original review: native desktop (Java/.NET) and mainframe (3270/AS/400) automation is still untested against a real target — Vision Core's screen-based approach should work in principle, but there is still no test in this codebase driving an actual non-browser desktop app end-to-end. Word/PowerPoint still have no dedicated adapter (Vision Core fallback only) — out of scope for this pass, flagged if wanted next.

### Phase 17 — Dashboard rewritten, wired to real data, iconsax-style icons
- `webui/templates/index.html`, `webui/static/js/app.js` rewritten from a static single page into a full SPA: login screen (real JWT auth), dashboard (live stat cards + recent runs), Test Runs, Adapters (live registry), Settings views, New Run modal (dynamic step builder), Run Detail modal (full report JSON).
- `webui/static/js/icons.js` (new) — hand-built inline SVGs matching iconsax.io's Linear style (24×24, 1.5px rounded stroke, `currentColor`) since this is an unbundled static app with no reachable CDN for the exact asset set in this sandbox.
- Zero hardcoded/mock data — every view polls the real API (`/auth/login`, `/test-runs/`, `/adapters/status`) every 4s; unreachable-API states are shown honestly rather than falling back to fake rows.
- Color palette/tokens (`--bg-base #121212`, `--accent-green #1ed760`, etc.) in `webui/static/css/style.css` untouched — all Phase 17 additions reuse the existing CSS variables and pill/card/badge conventions rather than introducing a second design language.

## 205 → 225 tests
**225/225 passing** (was 205 at the start of this pass): +6 API service tests, +12 gap-adapter tests, +2 PDF-OCR tests. `pyflakes` clean on all new/modified modules; the two pre-existing dead-branch warnings noted above (`cross_modal_diagnoser.py`, `cloud_adapter.py`) are unchanged and still flagged as product-decision items, not silently fixed.

## Next action
> 1. Real desktop/mainframe test against a live non-browser target (still the only true "unverified, not just untested-in-CI" gap from the original review).
> 2. Word/PowerPoint-specific adapters, if wanted — currently Vision Core fallback only, same as before this pass (roadmap issue 1.9, still not started).
> 3. ~~Split the vault Fernet key from the JWT signing secret~~ — **done, 2026-07-13, see `decisions.md` D-017.** `config/vault.key` (Fernet) and `config/jwt.key` (JWT HMAC) are now independently generated files with no derivation relationship.
> 4. Implement Roadmap Phase 20 (proposed, not started — see `Roadmap.md` §6 and `TRD.md` §10): Playwright-first element resolution + Scrapling-style DOM self-heal for `agents/vision/locator.py`, headless-render fix for `agents/capability/link_checker.py`'s client-rendered-page gap, structured audit-log taxonomy, skill quality-tracking. Full design backed by `external_repos.md`'s verified research across 18 repos. **This is now the largest remaining Phase (roadmap Phase C).**
> 5. Implement Roadmap Phase 21 (proposed, not started — see `Roadmap.md` §7 and `TRD.md` §11): Automation Anywhere trigger/validate architecture — new `automation_anywhere_adapter.py` (REST/CLI bot trigger + poll) and `playwright_validator.py` (read-only post-run web-state check), reusing the existing `db_adapter`/`file_adapter` for the database/files validation legs. Sequenced after Phase 20 since both need the same Playwright dependency (roadmap Phase E, lowest urgency, deliberately last).
> 6. **(New, 2026-07-13, roadmap Phases A & B — done, see `decisions.md` D-017/D-018):** Safety/correctness fixes (secrets split, `cloud_adapter` `list_objects` action + explicit mutating-action rejection, `db_adapter` mutating-function-pattern hardening, a real `cross_modal_diagnoser`↔`db_adapter` data-flow bug found and fixed) and full removal (not just disabling) of `AnthropicBackend`/`allow_network_calls` from the Planner. Planner now has exactly two backends: `heuristic` and `local_llm`. 18 tests added/changed across `test_cloud_workflow_adapters.py`, `test_db_adapter.py`, `test_preflight.py`; full suite passing. **Offline-hardening (roadmap Phase D) and the Phase C Playwright work above are the next logical steps**, in that order per the roadmap's own sequencing (Phase C is the prerequisite for the egress-audit-trail work in Phase D's capability-adapter logging extension).
