---
type: status
project: AURA
last_updated: 2026-07-19
---

# STATUS

> This file should always reflect the *current* state — overwrite freely, don't accumulate history here (that belongs in `progress.md`).

## Where things stand (2026-07-19 update, Phase Z started)
- **D-051:** fixed stale "proposed" cross-references in `docs/TRD.md` (§10/§11 headers already said "delivered"; two summary blurbs elsewhere in the same file hadn't caught up).
- **D-052:** added a real `LICENSE` file (MIT) backing `PROJECT_OVERVIEW.md`'s existing claim, which previously had no actual file behind it. Shipped `aura baselines list|approve|reject` — closes D-027's explicitly-flagged "natural, small follow-up" that had been left undone (reviewing/approving a new visual-regression baseline used to require manually deleting a file).
- **629/632 tests passing** (23 new this batch, zero regressions; same 3 pre-existing `mss`-module sandbox failures).
- **Phase Z is a continuing sweep, not a one-pass completion** — the two items closed above were the concretely-named, easily-verified ones found so far. Genuinely still open: D-027's per-channel/perceptual diff threshold (a larger algorithm change, not attempted here), Phase X1's multimodal LLM verifier (blocked on a real vision-capable endpoint to test against), and a continued grep-and-fix pass through `decisions.md`/`STATUS.md` history for any remaining stale language.

## Where things stand (2026-07-19 update, Phase X/Y — done)
- **Phase X2 (D-048):** opt-in `AURA_PLANNER_PRIORITY=hermes_first` auto-detection for the Hermes Agent planner backend. Default behavior (`local_first`/`cloud_first`) unchanged.
- **Phase X3 (D-049):** `HermesAgentDiagnoser` — root-cause diagnosis can now route through a real Hermes Agent instance too, not just spec generation. Opt-in via `AURA_DIAGNOSIS_BACKEND=hermes_agent`; default remains the deterministic heuristic diagnoser.
- **Phase Y1/Y2 confirmed already closed** from earlier phases: `api/run_store.py` is SQLite-backed (not in-memory), and `api/security.py` already keeps the JWT signing secret separate from the Fernet vault key (D-017). No code changes needed — closing these roadmap items as already-done rather than re-doing finished work.
- **Phase Y3 (D-050):** found and fixed a real bug while investigating the azure/gcp allowlisting gap — Azure connection strings are `Key=Value;Key=Value` pairs, not URLs, so the existing `urlparse()`-based host extraction was silently failing even for the *explicit connection_string param* case, not just the SDK-default-credential-chain case the old docs described. Added real Azure connection-string parsing and GCS's fixed default host (`storage.googleapis.com`) — both capability types are now genuinely allowlist-restrictable. `sharepoint_adapter` remains a documented, real fail-open exception (tenant-specific, no fixed host).
- **614/617 tests passing** (27 new across this batch: 5 for X3, 8 for Y3, plus X2's 4 folded into the Phase W test file — zero regressions). The 3 remaining failures are still the same pre-existing sandbox-only `mss` gap.
- **Remaining backlog:** Phase X1 (multimodal/screenshot-based LLM verifier — needs a real vision-capable endpoint to validate against, not available in this sandbox), and Phase Z (the full systematic audit of every other "proposed/partial" feature mention across the docs history — not started, still the single largest remaining item).

## Where things stand (2026-07-19 update, Phase W — done)
- **Real Hermes Agent integration, finally.** `docs/PROJECT_OVERVIEW.md` has always described AURA as orchestrated via "the Hermes Agent API," but D-006 replaced that with the in-repo kernel early on and no code ever actually talked to a Hermes Agent instance. `orchestrator/hermes_client.py::HermesAgentClient` now does: a thin client against a running Hermes Agent's real OpenAI-compatible `/v1/chat/completions` API server (Bearer auth, optional session header), reusing Phase D's egress-allowlist mechanism. `agents/planner/spec_generator.py::HermesAgentBackend` is a fourth, explicitly-selected planner backend (`AURA_PLANNER_BACKEND=hermes_agent`) — deliberately not in the auto-detection matrix (see D-047 for why).
- **LLM semantic tie-break.** Phase U's dual OCR/DOM verification (D-043) could only resolve a genuine disagreement via numeric rules. New `agents/vision/llm_verifier.py::semantic_verify()` adds a `"llm_semantic"` `dual_verification_tie_break` mode: asks whichever LLM backend is enabled (Hermes Agent or CloudLLMBackend) which candidate's matched text/role better fits the step's own `target_description`. Fails soft unconditionally to the pre-existing `highest_confidence` rule — this can only add accuracy, never a new failure mode.
- Both features off by default; both are strictly additive on top of everything Phases A–V already built. See `docs/decisions.md` D-047.
- **599/602 tests passing** (14 new in `tests/test_phase_w_hermes_and_llm_verifier.py`, zero regressions; one pre-existing test needed the same one-line exact-set-membership update D-044 already required for `cloud_llm`). The 3 remaining failures are the same pre-existing sandbox-only `mss` (screen capture library) gap, confirmed via `git stash` to predate this phase.
- **Explicit backlog left open by this phase, not silently deferred** — see `docs/Roadmap.md` §11 ("Phase X/Y/Z — gap closure & fusion roadmap"):
  - Auto-detection wiring for `hermes_agent` (currently explicit-select only, by design — see D-047).
  - A vision/multimodal LLM verifier variant (this phase is text-only, deliberately, since a text-only path is fully testable without a live multimodal model in this sandbox).
  - The FastAPI service layer's remaining gaps from earlier phases (in-memory run store persistence, vault/JWT secret separation, azure/gcp adapter host-allowlisting) — carried over, not touched by Phase W.
  - A pass through every "partial/proposed" feature flagged across `docs/decisions.md`/`docs/STATUS.md` history to convert each into either a completed phase or an explicit "won't do, here's why" entry.

## Where things stand (2026-07-17 update, Phase V verification closed — see D-045)
- **Ran the real `pytest` suite D-044 explicitly asked for** (this session has full tooling: `pytest`, `pydantic`, `httpx`, `sqlalchemy`, real `playwright`). `tests/test_phase_v_cloud_llm.py tests/test_planner.py` — **50/50 passing, first run** — the hand-verification from D-044's constrained session held up exactly.
- **One real, pre-existing, non-Playwright test bug found and fixed:** `test_spec_generator_has_no_anthropic_backend` hardcoded the exact backend registry as `{"heuristic", "local_llm"}` from before Phase V intentionally added `"cloud_llm"` as a third backend. The test's actually-meaningful checks (no `AnthropicBackend` class, `"anthropic"` not a registry key) were and are still correct — only the stale exact-set assertion needed updating. One-line fix, `tests/test_preflight.py`.
- **Full suite: 518/524 passing** (up from 517 before the fix). All 26 failed + 5 errored are the same long-documented Chromium-binary-download sandbox limitation (spot-checked and reconfirmed live, not assumed) — none touch Phase V's own code.
- **This closes the verification gap across the entire fourth remediation roadmap (R–V).** No phase from R through V has an outstanding "never run through real pytest" gap anymore.

## Where things stand (2026-07-17 update, Phase V — done, fourth remediation roadmap R–V complete)
- **New `CloudLLMBackend`** (`agents/planner/spec_generator.py`): generic OpenAI-compatible HTTP client (`POST {base_url}/chat/completions`), no vendor SDK, works against a real cloud endpoint or an operator's own local OpenAI-compat server equally. Config entirely via `AURA_CLOUD_LLM_BASE_URL`/`_API_KEY`/`_MODEL`. Off by default (`AURA_ENABLE_CLOUD_PLANNER=false`).
- **Egress control reuses Phase D's mechanism, not a new one:** new public `orchestrator.capability_router.is_egress_host_allowed()` wraps the existing allowlist check; `CloudLLMBackend` calls it before every request.
- **Detection matrix extended** (`config/settings.py::_auto_detect_planner_backend`): auto-detect now also considers a configured+enabled cloud backend, tie-broken by `AURA_PLANNER_PRIORITY` (`local_first` default / `cloud_first`). `AURA_REQUIRE_LLM_BACKEND` fails fast at startup instead of silently falling back to heuristic when no LLM backend is usable.
- **Escalation policy** (`generate_spec`, factored through a shared `_generate_with_retry` helper so R3's retry-with-logged-reason behavior is identical for both explicit-backend and auto-resolved callers): if the auto-resolved primary backend fails (after its own retry) and cloud is enabled and not already the primary, one escalation attempt against `CloudLLMBackend` is made and logged, same style as R3's retry logging.
- **A real bug caught during hand-verification, fixed before shipping:** the original escalation check (`isinstance(primary, CloudLLMBackend)`) broke under the exact `patch("...CloudLLMBackend", ...)` mocking pattern the test file uses. Fixed to check `settings.planner_backend != "cloud_llm"` instead — more robust and arguably more correct.
- **Verification, same disclosed gap as N–Q:** no `pytest`/`pydantic`/`httpx`/network this session. `tests/test_phase_v_cloud_llm.py` (24 tests) hand-verified against the real, unmodified `settings.py`/`spec_generator.py` via a from-scratch `pydantic`/`pydantic_settings` stand-in supporting real `Field(default_factory=...)` and `@model_validator` usage — more complete than earlier phases' stand-ins, since this phase's core logic lives inside a real pydantic validator. A full regression pass against pre-existing planner behavior confirmed no regressions. See D-044.
- **This closes out the entire fourth remediation roadmap (Phases R–V).** No further phases are currently planned.

## Where things stand (2026-07-17 update, Phase U — done)
- **Replaced Phase C's DOM-first/OCR-fallback chain with OCR-then-DOM dual verification**, per the roadmap's redesigned Idea 1. `agents/vision/executor.py::execute_step()` now always runs OCR (`locate_text`) *and*, when a browser session exists, DOM (`_resolve_dom()` — `locate_dom()` then `relocate_dom()` self-heal, unchanged logic, just no longer dispatching inline) — not conditionally, both every time.
- **New compilation rule** (`_compile_dual_result()`): both clear the confidence threshold and overlap (DOM bounding box vs. OCR point, within `settings.dual_verification_overlap_tolerance_px`) → agreement, dispatch via the higher-confidence method, tagged `"dual-method-confirmed"`. Both clear the threshold but disagree → logged, both candidates recorded, resolved via `settings.dual_verification_tie_break` (`highest_confidence`/`prefer_dom`/`prefer_ocr`), still `"dual-method-confirmed"`. Only one clears it → `"single-method"`. Neither → escalate, both candidates still recorded.
- **Dispatch-fallback:** if the winning method's dispatch fails for a display reason (`NoDisplayError`) and the other candidate also cleared the threshold, falls back to it rather than reporting a false miss (`verification_evidence["dispatched_via"]` records which one actually fired).
- `orchestrator/schemas.py::VisionActionResult` gained `verification_method`/`verification_evidence`. `agents/vision/dom_locator.py::DomLocateResult` gained a best-effort `bbox` field (needed for the overlap check — didn't exist before this pass). `config/settings.py` gained `dual_verification_overlap_tolerance_px` (default 40) and `dual_verification_tie_break` (default `"highest_confidence"`). `reports/templates/run_report.html.j2` renders verification method + both candidates on disagreement.
- **528 tests collected (20 new this pass): 497 passing, 26 failed, 5 errored** — the failing/erroring ones are the same pre-existing Chromium-binary-download sandbox gap documented since Phase C/D, unrelated to this pass's own code (confirmed separately via 16 new pure-unit tests against the compilation logic, which need no browser and all pass cleanly). See `docs/decisions.md` D-043.
- **This is Phase U of the R–V roadmap** (`docs/Roadmap.md`) — R, S, T, and U are now all done. **Phase V (dual API + local LLM generic backend) is next and last.**

## Where things stand (2026-07-17 update, Phase T — done)
- **New `orchestrator/spec_validator.py`:** a pre-execution validation pass over the whole `TestSpec`, wired into `RunEngine.run_spec()` before any memory write/screenshot happens. Structural-completeness issues (a step missing a required field for its own action type — e.g. `NAVIGATE_URL` with no `url`) raise `SpecValidationError` and block the run entirely, before anything starts. A second, separate check is a non-blocking heuristic: a vision-driven step (`VISUAL_CLICK`/`TYPE_TEXT`/`SCROLL`) whose description sounds like it's actually describing a backend/API/bot/database target gets a `severity="warning"` on `RunEngineResult.validation_warnings`, never a hard block (too fuzzy to trust as a hard rule — a UI button genuinely labeled "API Settings" is a legitimate real target).
- Wired into both `aura/cli/execute_cmd.py` call sites (clean `console.print` + `typer.Exit(code=1)` instead of an unhandled traceback) and `api/routers/runs.py`'s two background-task functions (explicit `except SpecValidationError` branch ahead of the pre-existing generic catch-all).
- **508/508 tests passing** (24 new), zero regressions. See `docs/decisions.md` D-042.
- This is Phase T of the R–V roadmap (`docs/Roadmap.md`) — Phase U (OCR-then-DOM dual verification) is next, largest phase in this roadmap, depends on Phase S's unified display guard (already done) and benefits from Phase R3's retry/escalation logging (already done).

## Where things stand (2026-07-16 update, Phase Q — done, third remediation roadmap N–Q complete)
- **`runtime/hooks/browser.py`** now mirrors Phase I2's video lifecycle for Playwright native trace files: `settings.record_trace` (off by default), `settings.traces_dir`, `context.tracing.start(screenshots=True, snapshots=True)`/`stop(path=...)`, `get_last_trace_path()`. Fully independent of `record_video`.
- **`orchestrator/run_engine.py`** attaches `report.report_paths["trace"]`, same pattern as the existing video block.
- **Verification is genuinely stronger here than for N/O/P:** this sandbox session has real `playwright` + a launchable Chromium binary (confirmed directly). `pytest`/`pydantic` are still absent, but `browser.py` itself has no `pydantic` dependency, so it was run for real against real Chromium + a real local HTTP server (via a tiny stand-in for just `config.settings`) and produced an actual, validated `trace.zip` on disk. Only the `run_engine.py` `report_paths` wiring (which does need `pydantic` via `RunEngine`) remains verified by code-reading only. See D-038.
- **This closes out the entire third remediation roadmap (Phases N–Q).** No further phases are currently planned.

## Where things stand (2026-07-16 update, Phase P — done)
- **`agents/capability/automation_anywhere_adapter.py`** gained P1 (`_fetch_control_room_audit()`, opt-in via `params.include_control_room_audit`, off by default, read-only, best-effort/non-fatal, shares N1's 401-retry) and P2 (a new `control_room_audit` evidence key, per-target + single-target-back-compat top level).
- **No RunReport/report_aggregator/run_engine changes needed** — `evidence` already flows into per-step `raw_results.json` for every capability-check step, so the new key alone puts Control Room's audit trail and AURA's own trail side by side in one report.
- **Verification, same disclosed gap as N/O:** no `pytest`/`httpx`/`pydantic`/network this session. `tests/test_phase_p_automation_anywhere.py` (5 tests) hand-verified via the same stand-ins used for Phase N, plus a regression check on the pre-existing evidence shape. See D-037.
- **This closes out the third remediation roadmap except Phase Q** (Playwright native trace files — not started).

## Where things stand (2026-07-16 update, Phase O — in progress)
- **New write-path adapter:** `agents/capability/db_seed_adapter.py` (`CapabilityType.DB_SEED`) — structured `table` + `values`/`rows` input only, builds a parameterized `INSERT` itself, table/column identifiers allowlist-validated (`^[A-Za-z_][A-Za-z0-9_]*$`) since SQL can't bind identifiers. No code path reads caller-supplied SQL text at all, so only INSERT is structurally possible. `db_adapter.py` (read-only, D-017-hardened) is untouched.
- **Two independent gates required:** the router's existing `capability_adapters_enabled` kill switch, plus a new `settings.allow_db_seeding` (default `False`, `config/settings.py`) checked inside the adapter itself.
- **Audited on success only:** every successful seed writes a `DB_SEED` audit-log record (via the existing `orchestrator/audit_logger.py` singleton) including the exact rows written; rejected/failed calls write nothing and are not audited as if they had.
- **Verification, same disclosed gap as Phase N:** no `pytest`/`sqlalchemy`/`pydantic`/network this session. `tests/test_db_seed_adapter.py` (16 tests) was written but not run through `pytest`; hand-verified instead end-to-end against a **real sqlite3 database on disk** using minimal stand-ins for the missing packages (see D-036). Regression status against the rest of the suite remains unverified this session.
- **Not started this pass:** Phases P, Q (plan-only, recorded in `Roadmap.md` §10; zero code written for either).

## Where things stand (2026-07-16 update, Phase N — in progress)
- **`docs/Roadmap.md` §10 now records the full third remediation roadmap (Phases N–Q)**, per the plan the person supplied: N (this pass), O (data-seeding adapter, AURA's first DB write path — its own phase, not started), P (Control Room audit-log retrieval + report sync — not started), Q (Playwright native trace files — not started).
- **Phase N started and substantially complete this pass** (see `docs/decisions.md` D-035): `agents/capability/automation_anywhere_adapter.py`'s REST mode now does real Control Room authentication (**N1**: `/v1/authentication` login with username/password or API key, cached token with expiry, transparent one-retry re-auth on a 401 during deploy or poll, `auth_token` override still honored for back-compat, unauthenticated fallback still honored when no credentials at all are supplied) and multi-bot/multi-runner fan-out triggering (**N2**: `bot_id`/`run_as_user_id` accept a scalar or a list, deploy fans out to every named target, a per-target deployment-id status map replaces the old `records[0]`-only poll so no target's result is silently dropped, `expected.rollup` selects `all_must_complete`/`any_must_complete`, evidence always carries a per-target breakdown, single-target calls keep the exact pre-Phase-N evidence shape).
- **Verification gap, disclosed rather than silently skipped:** this sandbox session has no `pytest`/`httpx`/`pydantic` installed and no network access to install them — a stricter gap than the Chromium-binary-download limitation noted elsewhere in this file. `tests/test_phase_n_automation_anywhere.py` (9 tests) was written but not run through `pytest`; the same scenarios were instead hand-verified end-to-end using minimal stdlib-only stand-ins for `pydantic`/`httpx` (see D-035). **Regression status against the rest of the suite (449 passing as of Phase M) is unverified this session** — run the real suite before trusting this as a clean landing.
- **Not started this pass:** Phases O, P, Q (plan-only, recorded in `Roadmap.md` §10; zero code written for any of them).

## Where things stand (2026-07-16 update, Phase M)
- **Phase M landed (this pass, see `docs/decisions.md` D-034):** the sixth and last phase of the second remediation roadmap (Phases G–M) — a generic test-case-management/defect-tracker adapter. `agents/capability/defect_tracker_adapter.py` (new `CapabilityType.DEFECT_TRACKER`) is one tool-agnostic REST adapter for Jira/TestRail/Zephyr/Xray-style tools: a caller-supplied `field_mapping` config translates a flat generic field dict (`title`/`status`/`priority`) into whatever nested (Jira's `fields.summary`) or flat (TestRail's `title`/`status_id`) JSON shape the target tool expects, via a small dotted-path `_set_nested()`/`_get_nested()` helper pair — no vendor-specific code lives in this file. Supports `create`/`update`/`get` actions, and a `get` (or a create/update's own response) can be verified against caller-supplied `expected_fields`, extracted via `response_field_mapping`, so pass/fail means "the call succeeded **and** the fields matched," not just a status code. Same three-part registration every capability adapter has used since Phase 14 (enum entry + `default_registry()` call; `config/tool_registry.yaml` needed no changes) — **except** one genuine (not just verified-unnecessary) router change: this adapter's primary URL param is `base_url`, not the generic `url` key every prior adapter used, so `orchestrator/capability_router.py::_URL_PARAM_KEYS` needed `"base_url"` added for egress-allowlist/audit-log host resolution to work, confirmed with a dedicated test rather than assumed. Honest confidence note, per the roadmap's own framing for this phase: verified only against a local mocked HTTP server (Jira-style nested mapping, TestRail-style flat mapping, update-by-record-id, get+verification, field-mismatch detection, and the usual missing-input/connection-error/wrong-status failure paths) — there is no real Jira/TestRail/Zephyr/Xray account available in this environment, so live-integration correctness against any specific real vendor is unverified. **449/449 tests passing** (14 new this pass, zero regressions). **All seven phases of the second remediation roadmap (G/H/I/J/K/L/M) are now complete.**

## Where things stand (2026-07-16 update)
- **Phase L landed (this pass, see `docs/decisions.md` D-033):** three new capability adapters, batched (Phases G–M's fifth phase). **L1 (accessibility)** runs a real axe-core WCAG scan via a locally-vendored bundle (`vendor/axe-core/`, not CDN-loaded — offline-first by design), verified against a deliberately-broken local HTML fixture (missing alt text, empty link text) that reliably trips real violations, plus a clean-page pass case. **L2 (security headers)** is a passive-only `httpx` GET check — header presence, cookie flag checks (Secure/HttpOnly/SameSite), and a configurable exposed-path list (`.env`, `.git/config`, etc.) — with a dedicated test that fails the test itself if the adapter ever issues a non-GET request, enforcing the "no active probing" constraint at the code level rather than just in a docstring. **L3 (performance budget)** reads real Navigation Timing metrics from a single Playwright page load against a configurable budget — explicitly not multi-user load generation. All three follow the same two-part registration every capability adapter has used since Phase 14 (new `CapabilityType` enum entry + `default_registry()` registration; `config/tool_registry.yaml`'s single generic `Capability.check` entry needed no changes, confirmed with a dedicated test). A minor stale-error-message bug (an outdated `pip install .[automation_anywhere]` extra that no longer exists in this version's `pyproject.toml`) was caught and fixed in both new Playwright-based adapters. **435/435 tests passing** (20 new this pass, zero regressions).

## Where things stand (2026-07-15 update)
- **Phase K landed (this pass, see `docs/decisions.md` D-032):** the fifth phase of the second remediation roadmap (Phases G–M) — multi-tenant / fine-grained RBAC. Verified first that tenant-level isolation was already real and thorough (every run/analytics query already scoped by `tenant_id`), so this phase's actual scope was *within*-tenant access, not tenant isolation itself. Added an opt-in `TestSpec.project_tag` + `TokenPayload.allowed_project_tags` permission matrix: untagged specs and unrestricted users behave exactly as before (zero breaking change), a restricted user can only run/view specs whose tag is in their list, admins always bypass. New admin-only `PUT /api/v1/users/{username}/project-tags` endpoint — deliberately not exposed via self-service signup, so signup can never be used to escalate or narrow someone else's access. Enforced at both the write path (`create_run`) and read paths (`list_runs` filters, `get_run` denies with the same "not found" phrasing the missing-run case already used, not a 403, to avoid confirming existence to an unauthorized caller). **401/415 tests passing** (16 new this pass, same pre-existing 12 failed/2 errored Chromium-binary-download sandbox gap, zero regressions), plus a live manual end-to-end run through a real `TestClient` (login → signup → restrict → denied run → allowed run) confirming the whole flow works, not just the unit tests.
- **Phase J landed (see `docs/decisions.md` D-031):** the fourth phase of the second remediation roadmap (Phases G–M) — parallel execution. Removed `api/routers/runs.py`'s module-level `RunEngine` singleton + global lock, which previously serialized every API run and failed a second concurrent submission with `"Vision Core busy"` instead of actually running it; every background task now gets its own fresh `RunEngine` via `_new_engine()`, so API runs genuinely execute in parallel. Reviewed the roadmap's planned `LoopGuardrail._states` re-keying (`step_id` → `(run_id, step_id)`) and found it unnecessary on inspection: every `LoopGuardrail()` construction site in the repo (there is exactly one, in `orchestrator/run_engine.py::run_spec()`) already creates a fresh local instance per call, so no two runs ever share guardrail state today — documented as verified-safe rather than silently changed. Added `aura execute --all --parallel N` (`ThreadPoolExecutor`, default `N=1` preserves the original sequential behavior exactly); each worker already gets its own `SkillStore`/`RunMemoryStore`/`RunEngine` via the existing per-call construction in `execute_cmd.py`, so no new locking was needed for correctness. Honest scope note: `--parallel`/concurrent API runs don't (and can't) make two workers safely share one physical display/screenshot surface on a single machine — a hardware constraint, not something this pass's code could fix, and disclosed in `docs/README.md` rather than silently ignored. **385/391 tests passing** (6 new this pass, zero regressions — the 12 failed/2 errored are the same pre-existing Phase C Playwright/Chromium sandbox-only gap documented throughout this file).
- **Phase I landed (see `docs/decisions.md` D-030):** the third phase of the second remediation roadmap (Phases G–M) — browser coverage. **I1 (cross-browser)** adds `settings.playwright_browser` (`chromium`/`firefox`/`webkit`) + a `--browser` flag on `aura execute`/`aura explore`; `runtime/hooks/browser.py` now launches the configured engine via `getattr` instead of hardcoded Chromium, with a clear `NoDisplayError` (not a crash) on an invalid choice. **I2 (video recording)** adds `settings.record_video` (off by default) + `--record-video`: the DOM/Playwright path gets a real native video via `record_video_dir` (a real bug was found and fixed here -- a stale video path from a previous run leaking into a recording-off run, fixed by resetting `_last_video_path` unconditionally in `close()`); the OS/pixel fallback path gets a new, honestly-labeled step-boundary `SlideshowRecorder` (`runtime/hooks/video_recorder.py`) instead of a fake "video" claim. Honest scope note: only Chromium's binary is actually downloaded in this sandbox (a network-egress restriction, same class of gap noted for Chromium itself in earlier phases) -- Firefox/WebKit engine-selection is verified via mocked dispatch plus a real live failure-path test, not full three-engine live parametrization of the existing Phase C suite. **393/393 tests passing** (10 new this pass, zero regressions -- notably all tests pass in this session's sandbox, including the 9 that earlier phases documented as Chromium-download-blocked elsewhere).
- **Phases H1–H2 landed (see `docs/decisions.md` D-028/D-029):** cross-run trend analytics and flaky-test detection, the next two phases of the second remediation roadmap (Phases G–M). **H1** adds a `test_key` column (migrated in-place on existing `api_runs.db` files) plus `test_history()`/`pass_rate_series()`/`list_tracked_tests()` on `api/run_store.py`, two new API routes (registered ahead of the pre-existing `/{run_id}` catch-all — verified with a dedicated regression test so `/analytics/...` isn't swallowed as a bogus run lookup), and a new **Analytics** view in the web dashboard. **H2** adds `get_flaky_candidates()` (outcome-transition-based, not just low-pass-rate — a consistently-failing test isn't "flaky," and a single regression isn't either, both explicitly excluded and tested), a `GET /analytics/flaky` route, a new local `orchestrator/quarantine_store.py`, and `aura skills quarantine/unquarantine/quarantined` CLI commands. `aura execute --all` now skips quarantined specs by default (visible message) with a new `--include-quarantined` override, checking each doc's test_id *before* generating a spec via a newly-extracted `agents/planner/spec_generator.py::infer_test_id()` (shared with the Planner itself, not a hand-copied regex). Honest scope note: quarantine is opt-in only (nothing auto-quarantines), and CLI-side (`aura execute`) trend analytics isn't possible yet — `orchestrator/memory.py`'s `run_state` table is keyed by `run_id` with in-place status updates, so it retains only the latest status per test, not history; this pass's trend analytics is scoped to the API/service-layer surface, which already gets a fresh `run_id` per submission. **374/383 tests passing** (23 new this pass; the 9 failing/erroring are the same pre-existing Phase C Playwright/Chromium sandbox-only failures noted throughout this file — zero new regressions).
- **Phases G1–G3 landed (see `docs/decisions.md` D-025/D-026/D-027):** the first three phases of the second remediation roadmap (gap-analysis-derived Phases G–M). **G1 (environment profiles)** and **G2 (CI/CD JUnit output)** were found already partially/fully coded from earlier in this same work session but undocumented and, for G2, unwired/untested — this pass finished the wiring, wrote the missing tests, and documented both. **G3 (real pixel-diff visual regression)** was built from scratch. A real latent bug was found and fixed in G2's pre-existing `junit.py`: its self-heal detection read a `healed_via` field that `VisionActionResult` never actually has, so that branch was permanently dead code — same bug class as D-017's `db_adapter`/`cross_modal_diagnoser` finding (a field referenced by name that the producing module never populates). `aura execute` also gained its first-ever documented, enforced exit-code convention (previously always exited 0 regardless of outcome). **351/360 tests passing** (20 new this pass; the 9 failing/erroring are the same pre-existing Phase C Playwright/Chromium sandbox-only failures noted throughout this file — zero new regressions).
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

## Next action (current, 2026-07-16)
> Phases G, H, I, J, K, L, and M of the second remediation roadmap are
> ALL now done — the entire roadmap (Phases G–M, `Roadmap.md` §9) is
> complete. No further phases are currently planned in `Roadmap.md`;
> pick from the small follow-ups below, or await new scope.
>
> Small follow-ups flagged but not done in Phase K: no `GET /api/v1/users`
> bulk-listing endpoint for an admin to see every user's current tag
> restrictions at once; no CLI equivalent of the new project-tags PUT
> endpoint (Phase K's scope was the API/service-layer surface only, per
> the original gap review's own framing).



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
- **Vault/repo conventions** — repository link/naming convention still informal; license is now confirmed (see below).
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

---

## Update — 2026-07-16 — Phase R: safety/correctness quick fixes (fourth roadmap, R–V)

**Note:** the sections above are historical (Phase 15–19 era) and were not
overwritten per this file's own "overwrite, don't accumulate" convention in
several recent passes — flagged here rather than silently rewritten,
since a full rewrite is a larger editorial job than this pass's scope.
Treat this section as the current ground truth; the third remediation
roadmap (Phases N–Q, see `docs/decisions.md` D-035–D-038) and now this
fourth roadmap (Phases R–V) are the most recent real work, layered on top
of the Phase 1–19 baseline described above.

**Fourth remediation roadmap (Phases R–V) kicked off — full plan in
`docs/Roadmap.md`'s "Fourth remediation roadmap" section. Phase R is done
(`docs/decisions.md` D-039):**

- **R1 (fixed):** `AutomationAnywhereAdapter._poll_rest_status_multi` had
  no floor on `poll_interval_seconds` — a caller-supplied `0` (or
  negative) busy-spun the poll loop with no pacing between status
  requests, which could exhaust a bounded response sequence (real API
  rate limits, or a test's mocked sequence) before the deadline elapsed.
  This was the real cause of the previously-failing
  `test_n2_timed_out_target_reported_independently_of_completed_target`
  (it surfaced one layer removed, as `KeyError: 'targets'`, because the
  adapter's generic exception handling converted the underlying
  `StopIteration` into a failure result with a different evidence shape).
  Fixed with `poll_interval_seconds = max(poll_interval_seconds, 1.0)`
  inside the function itself.
- **R2 (confirmed):** re-ran the fixed test in isolation and in the full
  suite. Both pass — there was no separate isolation-vs-full-suite
  ordering bug, just this one busy-spin bug.
- **R3 (added):** `agents/planner/spec_generator.py::generate_spec`'s
  one-retry-on-validation-failure loop now logs the failure reason
  (`logging.warning`, with the exception type and message) before
  re-prompting, instead of retrying silently. This is a prerequisite for
  Phase V's escalation policy being auditable rather than opaque.

**Tests: 483/484 → 484/484 passing** (full suite, confirmed both before
and after by temporarily reverting the R1 fix and re-running).

## Update — 2026-07-16 — Phase S: display/screenshot-guard unification (fourth roadmap)

**Phase S is done** (`docs/decisions.md` D-040, D-041):
- S1: `NoDisplayError` unified into one shared class in new `runtime/errors.py`,
  replacing three previously-unrelated per-module classes
  (`runtime.hooks.browser`/`capture`/`interact`). All call sites simplified
  to a single import + single `except NoDisplayError`.
- S2: new `runtime.errors.display_guard()` context manager -- the one
  enforced way to guard a screenshot-acquisition call, replacing
  hand-written `try/except NoDisplayError` at each site. Wired into
  `run_engine.py`, `autoscan.py`, `ui_audit_runner.py` (both screenshot
  sites), and `preflight.py`.

**Tests: 484/484 passing throughout** (no regressions). `ruff check` clean
on all Phase S-touched files.

## Next action
> **Phase T — Spec-level action/target-type validation pass**: new
> pre-execution validation step checking action/target-type compatibility
> across the whole spec before any step runs -- e.g. a `VISUAL_CLICK` step
> pointed at something that should have been a
> `CapabilityType.AUTOMATION_ANYWHERE` check fails fast with a specific
> message instead of burning through the vision pipeline first. See
> `docs/Roadmap.md`'s fourth-roadmap section for the full R–V plan and
> sequencing rationale.
