---
type: status
project: AURA
last_updated: 2026-07-04
---

# STATUS

> This file should always reflect the *current* state — overwrite freely, don't accumulate history here (that belongs in `progress.md`).

## Where things stand
AURA has grown well past the original CLI-only MVP described in earlier revisions of this file. It is now two things in one repo:

1. **The original offline CLI tool** (Phases 1–12): Planner/Vision/DataSynth agents, self-healing loop, live-URL testing, UI audit, code bug detection, scheduling, reporting. Still fully working, still the recommended way to run AURA today.
2. **A "universal QA platform" backend** (Roadmap.md Phases 13–19): capability adapters for non-UI systems, and a FastAPI service layer with a web dashboard. **This was previously undocumented — this update reconciles the docs with what the code actually contains.**

### Capability adapters (Roadmap Phases 13–16) — implemented and tested
`orchestrator/schemas.py` (`CapabilityType`, `CapabilityCheckInput`/`CapabilityCheckResult`, `TestStep.capability_type`/`target`/`expected`), `orchestrator/capability_router.py` (`route_capability`, dispatches to the registry), `orchestrator/capability_adapter.py` (registry + protocol), and real adapters under `agents/capability/`: `api_adapter`, `db_adapter`, `email_adapter`, `file_adapter` (local + SFTP via paramiko), `excel_adapter`, `pdf_adapter`, `cloud_adapter` (S3, detect-only), `workflow_adapter` (generic webhook trigger), plus `fake_adapter` for routing tests. `orchestrator/run_engine.py` routes `CAPABILITY_CHECK` steps through this path with cross-modal self-healing (`agents/planner/cross_modal_diagnoser.py`, Roadmap Phase 18) up to 2 heal attempts before escalating. All 16 app-category verification cases in `tests/test_16_categories_verification.py` pass.

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