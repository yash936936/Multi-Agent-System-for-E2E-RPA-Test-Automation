---
type: progress-log
project: AURA
---

# Progress Log

> Dated entries only. Don't edit past entries — append new ones. Newest at the top.

---

## 2026-07-16 — Phase P: Control Room audit log retrieval + report sync

**What happened:**
- Both P1 and P2 landed inside `agents/capability/automation_anywhere_adapter.py` (the same file N1/N2 touched — Phase O's `db_seed_adapter.py` was a separate, new file). **P1:** new `_fetch_control_room_audit()`, opt-in via `params.include_control_room_audit` (default off — no extra latency for existing callers), fetches Control Room's own audit-log entries for a deployment id once that target's poll is already terminal. Read-only, best-effort, non-fatal on failure (a fetch failure never changes the trigger's own pass/fail verdict, only its own `fetch_error` field), shares N1's 401-re-auth path.
- **P2:** the fetched entries land under a new `control_room_audit` evidence key (per-target, and mirrored to the top level for the single-target case) — no new report-plumbing needed, since `evidence` already flows into `ReportAggregator`'s per-step `raw_results.json` for every capability-check step. Confirmed by re-reading `orchestrator/schemas.py` and `orchestrator/report_aggregator.py`, not assumed; neither file (nor `run_engine.py`) needed changes.
- New tests: `tests/test_phase_p_automation_anywhere.py` (5 tests). Full detail in `docs/decisions.md` D-037.
- Same disclosed sandbox gap as N/O: no `pytest`/`httpx`/`pydantic`/network this session. Hand-verified end-to-end with the same lightweight stand-ins used for D-035, plus a regression check confirming the pre-existing single-target evidence shape and error paths are untouched.

**What should happen next:**
- Run `pytest tests/test_automation_anywhere.py tests/test_phase_n_automation_anywhere.py tests/test_phase_p_automation_anywhere.py` (and the full suite) in a real environment before starting Phase Q.
- Phase Q (Playwright native trace files) is the last phase in this roadmap.

## 2026-07-16 — Phase O: data-seeding adapter (`db_seed_adapter.py`, AURA's first intentional DB write path)

**What happened:**
- New `agents/capability/db_seed_adapter.py` + `CapabilityType.DB_SEED` (`orchestrator/schemas.py`) + registered in `orchestrator/capability_adapter.py::default_registry()`. `db_adapter.py` (read-only, D-017-hardened) untouched.
- Structured input only (`table` + `values`/`rows`, never a raw query string) — the adapter builds one parameterized `INSERT` itself. Table/column identifiers are interpolated (SQL can't bind identifiers) so they're validated against a strict `^[A-Za-z_][A-Za-z0-9_]*$` allowlist instead. Only INSERT is structurally possible — there's no code path that reads caller SQL text at all.
- New `settings.allow_db_seeding` (default `False`, `config/settings.py`) — a second, deliberate gate checked inside the adapter itself, independent of the router's general `capability_adapters_enabled` kill switch.
- Every successful seed call is audited via the existing `orchestrator/audit_logger.py` singleton (`DB_SEED` action, exact rows written in `details`); failed/rejected calls are not audited.
- New tests: `tests/test_db_seed_adapter.py` (16 tests). Full detail in `docs/decisions.md` D-036.
- **Same disclosed sandbox gap as Phase N:** no `pytest`/`sqlalchemy`/`pydantic` and no network this session. Hand-verified end-to-end this time against a **real sqlite3 database on disk** (not just mocks) via minimal in-process stand-ins for the three missing packages — every scenario in the real test file was independently re-run this way and passed, including confirming rows were actually persisted or, for rejected calls, that nothing was written. Still not a substitute for a real `pytest` run against the full suite.

**What should happen next:**
- Run `pytest tests/test_db_adapter.py tests/test_db_seed_adapter.py` (and the full suite) in a real environment before starting Phase P.
- Phase P (Control Room audit-log retrieval + report sync) is next per the roadmap's sequencing.

## 2026-07-16 — Phase N started (Control Room auth + multi-bot/multi-runner trigger); Phases N–Q added to Roadmap.md

**What happened:**
- Added the full third remediation roadmap (Phases N–Q) to `docs/Roadmap.md` §10, from the plan the person supplied: N (Automation Anywhere adapter completeness), O (data-seeding adapter, new write-path capability), P (Control Room audit-log retrieval + report sync), Q (Playwright native trace files). Only the plan text for O/P/Q was recorded — no code for those three yet.
- Started and substantially completed Phase N in the same pass: `agents/capability/automation_anywhere_adapter.py`'s REST path now does real Control Room authentication (N1: `/v1/authentication` login, cached token with expiry, transparent re-auth on a 401, `auth_token` override preserved for back-compat) and multi-bot/multi-runner fan-out triggering (N2: `bot_id`/`run_as_user_id` accept a list, per-target deployment-id status map replacing the old `records[0]`-only poll, `all_must_complete`/`any_must_complete` rollup, full per-target evidence breakdown). Full detail in `decisions.md` D-035.
- New tests: `tests/test_phase_n_automation_anywhere.py` (9 tests). Existing `tests/test_automation_anywhere.py` REST-mode tests re-checked by hand against the new code (still pass: no-credentials/no-override still sends no auth header, single-`bot_id` still gets the original scalar-shaped evidence keys).
- **Honest gap, not silently worked around:** this sandbox session has no `pytest`/`httpx`/`pydantic` installed and no network to install them, so the new test suite could not actually be run through `pytest`. The same scenarios were re-verified by hand with minimal stdlib-only stand-ins for `pydantic.BaseModel`/`httpx.Client` (see D-035 for the exact method) — confirms the logic runs and produces the intended results, but is **not** a substitute for a real full-suite `pytest` run, so regression-freeness against the rest of the (previously 449-passing) suite is unverified this session.

**What should happen next:**
- Run `pytest tests/test_automation_anywhere.py tests/test_phase_n_automation_anywhere.py` (and then the full suite) in an environment with the actual dependencies installed, before starting Phase O.
- Phase O (data-seeding adapter) is next per the roadmap's sequencing — same elevated care level as Phase J/K, since it's AURA's first intentional database write path.

## 2026-07-16 — Phase L: new capability adapters (accessibility, security headers, performance budget)

**What happened:**
- Worked through Phase L of the second remediation roadmap (Phases G–M) — three new capability adapters, batched together since the registration pattern (not the logic) is what's shared. Full detail in `decisions.md` D-033.
- **L1 (accessibility):** `agents/capability/accessibility_adapter.py`, `CapabilityType.ACCESSIBILITY`. Vendored axe-core v4.12.1 locally at `vendor/axe-core/axe.min.js` (fetched via `npm pack axe-core`, unmodified minified bundle + its MPL-2.0 license, provenance in `vendor/axe-core/README.md`) rather than loading it from a CDN — matches AURA's offline-first posture. Injects it into a headless Playwright page via `page.add_script_tag(path=...)`, runs `axe.run()`, filters violations by a configurable `severity_threshold` (default `"serious"`). Verified against a deliberately-broken local HTML fixture (an `alt`-less `<img>`, an empty-text `<a>`) that reliably trips real axe-core violations (`image-alt` at `critical`, `link-name` at `serious`, among others), plus a clean, properly-labeled page that scans clean.
- **L2 (security headers):** `agents/capability/security_headers_adapter.py`, `CapabilityType.SECURITY_HEADERS`. Passive-only: a single `httpx` GET, checking header presence (HSTS/X-Content-Type-Options/X-Frame-Options/CSP/Referrer-Policy by default, configurable), `Set-Cookie` flag checks (Secure/HttpOnly/SameSite), and a configurable "commonly exposed paths" list (`.env`, `.git/config`, `wp-config.php.bak`, etc.), each checked with its own plain GET. Explicitly, permanently no payload injection or active probing of any kind — enforced by a dedicated test that raises inside the test itself if the adapter ever calls `httpx.Client.post`, not just documented as a design intent.
- **L3 (performance budget):** `agents/capability/performance_adapter.py`, `CapabilityType.PERFORMANCE`. One Playwright page load, metrics read directly from the browser's own `performance.getEntriesByType('navigation'/'paint')` API (TTFB, DOM-content-loaded, load time, first paint, first contentful paint), compared against a configurable `budget` dict. Explicitly not multi-user load generation and not a trend/percentile series — one data point per run.
- All three follow the exact registration pattern every capability adapter has used since Phase 14: a `CapabilityType` enum entry + a `registry.register(...)` call in `default_registry()`. Verified (not just assumed) that `config/tool_registry.yaml`'s single generic `Capability.check` entry needed zero changes, and that the egress-control host-allowlist logic (`orchestrator/capability_router.py::_URL_PARAM_KEYS`) already covers all three via the same `params["url"]` key every other URL-based adapter uses — both confirmed with dedicated tests rather than just inspection.
- **Bug caught and fixed while writing these:** both new Playwright-based adapters' initial `ImportError` messages pointed at `pip install .[automation_anywhere]`, an optional extra that no longer exists in this version of `pyproject.toml` (playwright graduated to a core dependency during the Phase C/D era, and the extra was removed then, but the *original* adapters' error message — written back when the extra still existed — was never updated to match). Fixed in both of this phase's new files to point at `pip install -e .` / `playwright install chromium` instead.
- New tests: `tests/test_accessibility_adapter.py` (6), `tests/test_security_headers_adapter.py` (7), `tests/test_performance_adapter.py` (6, including a shared three-adapter registry-wiring check), plus 1 new egress-coverage test in `tests/test_capability_egress_controls.py`.
- Full suite: **435/435 passing** (415 before this pass + 20 new), zero regressions.
- Updated `docs/Roadmap.md` §9 (Phase L marked done, corrected the "three-way registration" description to the two-way it actually turned out to be) and `docs/STATUS.md`.

**What changed:**
- Three genuinely new, tested capabilities — no partial/undocumented surprises this time, same clean pattern as Phase I/J/K.

**Known limitations carried forward:**
- The same stale `pip install .[automation_anywhere]` message still exists in the *original* `automation_anywhere_adapter.py`/`playwright_validator.py` files (found while fixing the same bug in this phase's own new files) — not retroactively fixed here, flagged as a small follow-up.
- Accessibility/security-header/performance results don't yet feed into Phase H's trend analytics — each run's result lands in the normal step-result/report flow, but there's no dedicated "score over time" view for any of these three yet.
- Phase M (test-case-management adapter) is next and last in the Phases G–M roadmap — lowest confidence by design, will be verified only against a mocked HTTP server per the original plan (no real Jira/TestRail/Zephyr/Xray account available to test against here).

---

---

## 2026-07-15 — Phase K: multi-tenant / fine-grained RBAC (project-tag permission matrix)

**What happened:**
- Fifth phase of the second remediation roadmap (Phases G–M). Full detail in `decisions.md` D-032.
- Verified before writing any code that tenant-level isolation was already real and thorough — grepped every use of `tenant_id` across `api/` and confirmed every run/analytics query in `api/run_store.py` was already scoped by it. So the actual scope here is *within*-tenant access, not tenant isolation, which needed no changes.
- Added an opt-in permission matrix: `TestSpec.project_tag` (optional label a spec can carry) + `TokenPayload.allowed_project_tags` (optional per-user restriction, carried in the JWT itself like `tenant_id`/`role` already are). Untagged specs and unrestricted users (the default for every existing/new user) behave exactly as before — zero breaking change to anything that doesn't use the feature.
- New admin-only `PUT /api/v1/users/{username}/project-tags` endpoint (new `api/routers/users.py` router). Deliberately not exposed via self-service `/auth/signup` — a signing-up user can't touch anyone's access, including their own, beyond the existing defaults.
- Enforced at the write path (`create_run`, via a new `require_project_access` that raises 403) and, just as importantly, the read paths: `list_runs` now filters out runs the caller can't see rather than returning everything in the tenant, and `get_run` denies with the *same* "Run not found or access denied" message the plain-missing-run case already used — deliberately 404, not 403, so an unauthorized caller can't tell the difference between "doesn't exist" and "exists, not yours."
- Verified live, not just via the test suite: a real `TestClient` run through login → signup → admin restricts a second user → that user re-logs-in → denied run on a disallowed tag → allowed run on their permitted tag, all producing the expected status codes and messages.
- Full suite: **401/415 passing** (16 new this pass — 6 direct unit tests of the pure `user_can_access_project` function, 10 full HTTP integration tests), same pre-existing 12 failed/2 errored Chromium-binary-download sandbox gap documented throughout this log, zero regressions.

**What changed:**
- `orchestrator/schemas.py` — `TestSpec.project_tag` (additive).
- `api/security.py` — `TokenPayload.allowed_project_tags`, `create_access_token()` gained the param, new `user_can_access_project()`/`require_project_access()`.
- `api/user_store.py` — `verify()`/`create_user()`/`find_or_create_oauth_user()` read/write `allowed_project_tags`; new `set_allowed_project_tags()`.
- `api/spec_builder.py` — `build_test_spec()` reads `project_tag` from the request body.
- `api/routers/auth.py` — both token-issuance call sites (`/login`, OAuth callback) now pass `allowed_project_tags` through.
- `api/routers/runs.py` — `create_run` checks access up front; `list_runs` filters; `get_run` denies.
- `api/routers/users.py` — new router, new admin-only endpoint.
- `api/main.py` — registered the new router.
- `tests/test_security.py` (new, 6 tests), `tests/test_project_tag_permissions.py` (new, 10 tests).
- `docs/decisions.md` — D-032 added.

**What should happen next:**
- Phase L (new capability adapters: accessibility, passive security headers, performance budget) is next per the roadmap's sequencing.
- Small, disclosed follow-ups from this phase: no bulk `GET /api/v1/users` listing endpoint, no CLI equivalent of the new PUT endpoint (this phase's scope was the API/service-layer surface specifically).

---

## 2026-07-15 — Phase J: parallel execution

**What happened:**
- Worked through Phase J of the second remediation roadmap (Phases G–M), the parallel-execution phase. Full detail in `decisions.md` D-031.
- **API `RunEngine` singleton removed:** `api/routers/runs.py`'s module-level `_engine`/`_run_lock` are gone. Every background task now gets its own fresh `RunEngine` via a new `_new_engine()` helper. Previously, a second run submitted while one was already in flight got an immediate `"Vision Core busy"` failure instead of actually running — that was full serialization, not real concurrency. Concurrent API runs now genuinely execute in parallel.
- **`LoopGuardrail` concurrency reviewed, found already safe:** the roadmap's original plan called for re-keying `LoopGuardrail._states` from `step_id` to `(run_id, step_id)`. On review, every construction site of `LoopGuardrail()` in the repo (there's exactly one, inside `orchestrator/run_engine.py::run_spec()`) already creates a fresh local instance per call — no two concurrent runs ever share one `LoopGuardrail`, so the re-key would be inert. Documented as verified-correct rather than changed, per `docs/debug.md`'s "verify, don't assume" rule, with a note on when this would need revisiting.
- **`aura execute --all --parallel N`:** new option (default `1`, unchanged sequential behavior). `N > 1` dispatches the filtered (non-quarantined) requirement docs through a `ThreadPoolExecutor` — I/O-bound work, so threads rather than processes. Each worker already gets its own `SkillStore`/`RunMemoryStore`/`RunEngine` via the existing `execute_cmd.execute_test`/`_run_requirement_text` path, so no new shared-state locking was needed.
- New tests: `tests/test_parallel_execution.py` (6) — every target runs exactly once under `--parallel`, `--parallel 1` matches the original sequential order, `--parallel 0` is rejected, a failed run under `--parallel` still exits 1, and two regression guards on the removed API singleton/lock.
- Test count: 379/391 passing before this pass (12 failed/2 errors — the same pre-existing Phase C Playwright/Chromium sandbox-only gap noted throughout `STATUS.md`), **385/391 passing after** (6 new, all passing) — zero regressions.

---

## 2026-07-15 — Phase I: cross-browser support + video recording

**What happened:**
- Worked through Phase I of the second remediation roadmap (Phases G–M), the browser-coverage phase. Full detail in `decisions.md` D-030.
- **I1 (cross-browser):** `config/settings.py` gained `playwright_browser` (`chromium`/`firefox`/`webkit`, default unchanged) and a shared `PLAYWRIGHT_BROWSER_CHOICES` constant. `runtime/hooks/browser.py` now launches whichever engine is configured via `getattr(playwright, engine_name)` instead of a hardcoded `.chromium`, with a clear `NoDisplayError` (listing valid choices) if the value is invalid, checked before Playwright is even touched. New `--browser` flag on `aura execute` and `aura explore`.
- **I2 (video recording):** new `settings.record_video` (off by default) + `--record-video` on `aura execute`. When on and the DOM/Playwright path is active, the browser context records a real video natively (`record_video_dir`); `runtime/hooks/browser.py::close()` now captures the finalized video path *before* the rest of teardown, since Playwright only writes the file once the page is closed. **Found and fixed a real bug while writing tests:** the session's `_last_video_path` field wasn't reset between runs, so a recording-off run immediately after a recording-on run incorrectly reported the *previous* run's video path — fixed by clearing it unconditionally at the top of `close()`. For the OS/pixel fallback path (no live Playwright page — native desktop targets), new `runtime/hooks/video_recorder.py::SlideshowRecorder` writes an honestly-labeled step-boundary manifest (`"kind": "slideshow"`, explicit "not continuous video" note) instead of pretending to be a real recording. `orchestrator/report_aggregator.py::finalize()` gained an `extra_report_paths` param so `orchestrator/run_engine.py::run_spec()` can attach whichever artifact actually got produced under `report_paths["video"]` or `report_paths["video_slideshow"]` (never both — real video wins if somehow both exist).
- New tests: `tests/test_cross_browser.py` (6 — live Chromium baseline, invalid-engine-name handling, mocked-dispatch proof that firefox is actually requested via `getattr`, live confirmation that an uninstalled firefox binary fails as a clean `NoDisplayError`, plus the two video on/off behavior tests), `tests/test_slideshow_recorder.py` (2, manifest correctness), `tests/test_run_engine_video.py` (2, full `RunEngine.run_spec()` integration proving a real video file lands in the finalized report).
- Full suite: **393/393 passing** (383 before this pass + 10 new), zero regressions. Notably, every test passed in this session's sandbox, including the 9 that earlier phases (D, E, and others) documented as failing only when Chromium's binary can't be downloaded — this session's sandbox has a working Chromium binary, so that particular environment-dependent gap simply doesn't reproduce here. It remains real and disclosed for whichever environment runs this next, not something this pass silently fixed.
- Updated `docs/Roadmap.md` (new §9, the full Phases G–M plan with G/H/I marked done and J–M's scope recorded ahead of time) and `docs/PHASES.md` (pointer note, since that file's own scope is the original 6-phase MVP plan only).

**What changed:**
- Two genuinely new, tested capabilities (`--browser`, `--record-video`) rather than partial/undocumented ones this time — no "found already written but undocumented" surprises like earlier phases in this same roadmap.

**Known limitations carried forward:**
- Firefox/WebKit engine selection is verified via dispatch-logic tests (mocked Playwright) plus one real live failure-path test, not full three-engine live parametrization of the existing Phase C DOM-path suite — that would require an environment where those binaries can actually be downloaded.
- No video/slideshow viewer added to `reports/render.py`'s HTML report yet — the paths are real and populated in `RunReport.report_paths`, but rendering them nicely in the report itself is a small follow-up, not required by this phase's own scope.
- `--record-video` is scoped to `aura execute`/`aura explore` only, not to Automation Anywhere trigger/validate runs (Phase 21) — recording a bot-triggered run wouldn't capture anything meaningful since AURA itself isn't driving the UI in that flow.

---

## 2026-07-15 — Phases H1–H2: cross-run trend analytics, flaky-test detection + quarantine

**What happened:**
- Worked through Phases H1/H2 of the second remediation roadmap (Phases G–M). Full detail in `decisions.md` D-028 (H1), D-029 (H2).
- **H1:** added a `test_key` column to `api/run_store.py`'s `api_runs` SQLite table (with an in-place migration for pre-existing DB files, verified against a hand-built legacy-schema fixture, not just a fresh install), extracted from `spec.test_id`/`spec.test_name` at run-creation time. New `test_history()`, `pass_rate_series()`, `list_tracked_tests()` query methods. New `GET /api/v1/test-runs/analytics/tests` and `GET /api/v1/test-runs/analytics/tests/{test_key}` routes — registered *before* the pre-existing `/{run_id}` catch-all route, since FastAPI matches in registration order and `/analytics/...` would otherwise be swallowed as a bogus run-id lookup (caught this with a dedicated regression test before it could ship broken). New **Analytics** view in the web dashboard (`webui/templates/index.html` + `app.js`), reusing existing card/badge CSS tokens; one new hand-drawn `trend` icon added to `icons.js` in the same iconsax-Linear style as the rest of the set.
- **H2:** `get_flaky_candidates()` on `ApiRunStore`, built on H1's query layer per the original phase plan. Deliberately transition-based, not just low-pass-rate: wrote and passed dedicated tests proving a consistently-failing test and a test with a single clean regression are both correctly *excluded* from the flaky list (they're "broken" and "regressed," not "flaky"). New `GET /api/v1/test-runs/analytics/flaky` route (`min_runs`/`min_transitions` query params), same route-ordering care as H1.
- New local `orchestrator/quarantine_store.py` (JSON file, not SQLite — a short, human-readable, rarely-written list) + `aura skills quarantine/unquarantine/quarantined` CLI commands. `aura execute --all` now peeks each requirement doc's test_id via a newly-extracted `agents/planner/spec_generator.py::infer_test_id()` (pulled out of `LocalHeuristicBackend._infer_test_id` so the skip-check and the Planner share one implementation instead of two that could drift) and skips quarantined specs with a visible message; new `--include-quarantined` flag overrides it. If every doc ends up skipped, `--all` now exits 1 with an explicit "nothing ran" message instead of silently reporting success on zero runs.
- Live end-to-end smoke test: `aura skills quarantine TC-LOGIN-FLOW-001 --reason "flaky demo"` → `aura skills quarantined` (shows it) → `aura execute --all --yes` (skips it, prints the reason, exits 1 since it was the only doc) → `aura skills unquarantine` (removes it) → confirmed clean.

**Tests:** 23 new (`tests/test_run_store_analytics.py` ×11, `tests/test_analytics_api.py` ×5, `tests/test_quarantine.py` ×7). Full suite: **374/383 passing** (was 351 at the start of this pass), same pre-existing 9 sandbox-only Playwright/Chromium failures, zero regressions.

**Docs touched:** `docs/decisions.md` (D-028, D-029), `docs/STATUS.md` (rewritten "where things stand" section), `docs/README.md` (`aura execute --include-quarantined`, `aura skills quarantine/unquarantine/quarantined`, new Analytics API endpoints documented).

**Not done, flagged not silently dropped:**
- No API/dashboard way to quarantine a test directly (quarantine is CLI-only for now); a human sees a flaky candidate in the Analytics view but has to go run a CLI command to act on it.
- CLI-side (`aura execute`) trend analytics is a separate, unaddressed gap — `orchestrator/memory.py`'s `run_state` table only retains the latest status per test_id (keyed by `run_id`, overwritten in place), not history across repeated local runs. This pass's analytics is scoped to the API/service-layer surface, which already has the right data shape (fresh `run_id` per submission).
- Quarantine entries never expire or prompt for re-review.

---

## 2026-07-14 (later same day) — Phases G1–G3: environment profiles, CI/CD JUnit output, real visual regression

**What happened:**
- Worked through the first three phases of the second remediation roadmap (Phases G–M, derived from a code-verified gap analysis against a full-featured autonomous QA agent checklist). Full detail in `decisions.md` D-025 (G1), D-026 (G2), D-027 (G3).
- **G1 (environment profiles) and G2 (CI/CD JUnit output)** were found already partially/fully implemented from earlier in this same work session, but undocumented — and for G2, not actually wired into the CLI, with zero test coverage. Verified G1's existing code and tests were genuinely correct (13/13 passing, live `aura init --env` smoke test), then wrote the two missing `decisions.md` entries.
- **G2** needed real finishing work: added `--junit-out` to `aura execute` (single-spec and `--all` combined-suite modes), threaded `RunReport` return values back through `execute_test`/`execute_prompt`/`execute_url` (previously all returned `None`), and gave `aura execute` its first-ever documented, enforced exit-code convention (0 = all passed, 1 = any failed/escalated — previously the CLI always exited 0 no matter what happened). Wrote 10 new tests for the previously-untested `reports/junit.py`, and while writing them, **found a real bug**: the module's self-heal detection read `step.get("healed_via", "")`, but `VisionActionResult` has no such field — that branch was permanently dead code on real data. Fixed by reporting self-healing honestly at the `<testsuite>` level via `RunReport.self_healed_steps` (the field that's actually populated correctly) instead of falsely attributing it to one testcase.
- **G3 (real pixel-diff visual regression)** built from scratch: `agents/vision/visual_regression.py::compare_to_baseline()`, using Pillow + a numpy-vectorized diff (numpy is a guaranteed transitive dependency of the already-declared `opencv-python-headless`). New opt-in `TestStep.visual_baseline_key`/`visual_diff_tolerance` fields, new `VisionActionResult.visual_diff_ratio`/`visual_diff_image_ref`/`visual_baseline_created` fields, wired into `run_engine.py` right after the existing OCR assertion check with an explicit AND-style combining rule. Baselines persist under `runtime/baselines/` — deliberately **not** gitignored (unlike `screenshots/`/`data_cache/`), since a visual-regression baseline that isn't shared across machines/CI defeats the entire point of the feature. Report template gained a diff panel.
- Both phases verified end-to-end, not just unit-tested: live CLI runs (`--junit-out`, `--all --junit-out`) against the real example spec, and two full `RunEngine.run_spec()` integration tests proving `visual_baseline_key` actually reaches the diff module through the real pipeline.
- Full suite: **351/360 passing** (20 new tests this pass), same 9 pre-existing Playwright/Chromium sandbox-only failures throughout this log, zero new regressions.

**What changed:**
- `config/settings.py` — `baselines_dir` property added; G1's env-profile machinery documented (already present).
- `aura/main.py` — `--junit-out` flag, `_exit_nonzero_if_failed()` exit-code enforcement.
- `aura/cli/execute_cmd.py` — `junit_out`/`junit_suite_collector` params threaded through all entry points; all now return `RunReport`.
- `reports/junit.py` — self-heal detection bug fixed (see above); otherwise unchanged from its pre-existing implementation.
- `orchestrator/schemas.py` — `TestStep.visual_baseline_key`/`visual_diff_tolerance`, `VisionActionResult.visual_diff_ratio`/`visual_diff_image_ref`/`visual_baseline_created` (all additive/optional).
- `orchestrator/run_engine.py` — visual regression check wired in after the OCR assertion block.
- `agents/vision/visual_regression.py` — new module.
- `reports/templates/run_report.html.j2` — visual diff panel added.
- `runtime/baselines/.gitkeep` — new directory, deliberately not gitignored.
- `tests/test_junit.py` (new, 10 tests), `tests/test_visual_regression.py` (new, 7 tests), `tests/test_run_engine.py` (+2 integration tests), `tests/test_cli.py` (+1 test, 1 existing test's stub fixture updated for the new return-value/kwarg contract).
- `docs/decisions.md` — D-025, D-026, D-027 added. `docs/README.md` — `--env`/`AURA_ENV` documented (G1 doc gap closed).

**What should happen next:**
- Remaining Phase G item not done: the example GitHub Actions workflow template — small, low-risk, explicitly flagged rather than silently dropped.
- Phase H (cross-run trend analytics + flaky-test detection) is next in the roadmap's own sequencing — builds directly on `api/run_store.py`'s existing data, no live external target needed.

---

## 2026-07-14 (later same day) — Follow-up fix: two more unguarded screenshot-capture sites in explore/ui-audit

**What happened:**
- After D-022 fixed `run_engine.py`'s 5 unguarded `screenshot_provider(...)` calls and the `mouseinfo`/`SystemExit` root cause behind `aura explore`'s silent failure, re-verified `aura explore` live with genuinely no display connected at all (not just the earlier no-tkinter-under-Xvfb scenario) — it still crashed with a raw, uncaught `NoDisplayError` traceback.
- Root cause: `orchestrator/autoscan.py::run_autoscan` and `orchestrator/ui_audit_runner.py::_run_click_audit` (the scroll-scan and click-audit engines behind `--scroll-test`/`--ui-audit`/`aura explore`) each call `screenshot_provider(...)` directly with no guard — the same class of bug D-022 fixed, in two files that pass didn't touch. Full detail in `decisions.md` D-024 — this entry is a summary.
- **Fixed:** both files now catch `NoDisplayError` at every screenshot-capture call site and stop cleanly (keeping whatever was already collected) instead of crashing. Added a `display_unavailable` field to `AutoScanReport` so `execute_cmd.py`/`explore_cmd.py` can print an accurate "no display available" message instead of the misleading "hit the scan limit" they'd have shown before (both conditions previously looked identical: `reached_bottom=False`).
- Added 3 new regression tests (2 in `tests/test_autoscan.py`, 1 in `tests/test_ui_audit_runner.py`); updated a pre-existing fake report object in `tests/test_explore_cmd.py` that needed the new field to keep passing.
- **Verification:** confirmed the true before/after via `git stash` rather than assuming — before this pass: 318/327 passing; after: 321/330 passing. Same 9 pre-existing Phase C Playwright/Chromium sandbox-only failures throughout, zero regressions. Live-reproduced the crash and confirmed the fix by re-running `aura explore` with no display: now exits 0 with a valid JSON report instead of a traceback.

**What changed:**
- `aura explore`, `aura execute --scroll-test`, and `aura execute --ui-audit` no longer crash in a genuinely headless/no-display environment (as opposed to the narrower no-tkinter-under-Xvfb case D-022 fixed) — they now report "no display available" cleanly and exit 0.

**What should happen next:**
- Optional follow-up, not required by this fix: unify the three separate, identically-named `NoDisplayError` classes across `runtime/hooks/capture.py`/`interact.py`/`browser.py` into one shared exception type (noted in D-024 as a design smell this pass had to work around, not fixed here since it's a broader refactor).

---

## 2026-07-14 (later same day) — Roadmap Phase E: Automation Anywhere trigger/validate closure

**What happened:**
- Closed out Phase E per D-019's earlier note requesting a full pass (own decisions.md entry, CLI/doc coverage, a registration test). Full detail in `decisions.md` D-021 — this entry is a summary.
- **Verified, not re-built:** `agents/capability/automation_anywhere_adapter.py` and `agents/capability/playwright_validator.py`, plus `tests/test_automation_anywhere.py`'s existing 13 tests (registry wiring, REST trigger+poll, CLI trigger, web-validator assertions, full trigger→validate integration test), were already correct and complete against TRD §11 — no functional bug found in either adapter on inspection.
- **Real gap found and fixed:** Phase D's (D-020) egress-controlled `_URL_PARAM_KEYS` list didn't include `control_room_url` — the actual param name the AA REST trigger uses for its Control Room endpoint — so an AA trigger's target host was invisible to both the audit trail and the allowlist. Added it.
- Confirmed CLI-mode AA triggers (local subprocess, not a network call) correctly have no extractable host and rely on the kill switch alone — added a test making this explicit rather than leaving it as an untested side effect.
- Updated `docs/WORKFLOW.md`'s capability-check step-type example list, which only named 8 of the now 15 registered capability types, to mention Automation Anywhere trigger + Playwright web-validation explicitly.
- Added 4 new tests to `tests/test_automation_anywhere.py` (now 17 total in that file).
- **Verification:** ran the full suite before starting (300/309 passing, the 9 pre-existing Phase-C sandbox-only Chromium failures) to confirm a clean baseline. After this pass: 304/313 passing — identical 9 pre-existing failures, 4 new tests all passing, zero regressions. `pyflakes` clean on every file touched.
- **All five phases (A/B/C/D/E) of the original remediation roadmap are now complete.**

**What changed:**
- Automation Anywhere trigger/validate is now fully covered by Phase D's egress controls (kill switch + allowlist), matching every other network-facing capability adapter, and is documented for spec authors in `docs/WORKFLOW.md`.

**What should happen next:**
- Optional follow-ups, not required by the original roadmap: consolidate `playwright_validator.py` onto the same shared Playwright browser-context module as Phase C's `dom_locator.py`/`browser.py` (TRD §11.5's own reconciliation note); resolve the Azure/GCP host-allowlisting gap noted in D-020/D-021 for those two SDK-based adapters.

---

## 2026-07-14 — Roadmap Phase D: capability-adapter egress controls

**What happened:**
- Implemented the remediation roadmap's Phase D (Section 4: offline hardening / API boundary). Full detail in `decisions.md` D-020 — this entry is a summary.
- **Verified, not re-fixed:** confirmed Phases A/B/C were already genuinely landed in the current codebase (real Playwright integration in `agents/vision/dom_locator.py`, `runtime/hooks/browser.py`, etc.) before starting — the roadmap's own sequencing note said Phase D depended on Phase C landing first, but on inspection Phase C's Playwright work is a local browser-automation surface, not a new outbound network target, so Phase D didn't actually need to wait on it.
- **Added:**
  1. `config/settings.py`: `capability_adapters_enabled: bool = True` (hard kill switch) and `allowed_capability_hosts: list[str] | None = None` (opt-in egress allowlist), both defaulting to unchanged behavior.
  2. `orchestrator/capability_router.py::route_capability` — the single chokepoint every capability adapter dispatches through — now enforces the kill switch and allowlist before any adapter runs, and audit-logs every permitted call's target host + UTC timestamp (never payload contents, since params can carry credentials) via the existing `orchestrator/audit_logger.py` sink already used for run-level auditing.
  3. Host extraction was built from the real `params.get(...)` key names actually used across every file in `agents/capability/*.py` (audited, not assumed): `url`/`webhook_url`/`account_url`/`endpoint`, `connection_string`/`conn_str`, `smtp_server`/`imap_server`/`host`, falling back to `payload.target` if it parses as a URL.
  4. New test file `tests/test_capability_egress_controls.py` (16 tests): kill-switch rejection, per-adapter-convention host extraction, allowlist exact/subdomain matching and rejection, fail-open behavior when no host is resolvable, and audit-log content checks (present on permit, absent on kill-switch rejection, no payload leakage).
- **Documented gap, not hidden:** `azure_adapter.py`/`gcp_adapter.py` primarily authenticate via SDK default-credential chains rather than an explicit host param, so `_extract_egress_host` often can't resolve a host for them — `_host_allowed` fails open in that case (kill switch remains the backstop) and the audit record logs `host: null` rather than silently skipping the log line.
- **Verification:** ran the full suite before touching any code to establish a clean baseline (284/293 passing — the 9 failures are pre-existing Phase C Playwright/Chromium tests that fail in this specific sandbox because its own network egress rules block the one-time Chromium binary download, unrelated to anything in this repo). After Phase D's changes: 300/309 passing — identical 9 pre-existing failures, 16 new tests all passing, zero regressions. `pyflakes` clean on every file touched.
- **What's left:** only Phase E (Automation Anywhere trigger/validate, TRD §11) remains unimplemented from the original 5-phase roadmap. It already routes through `route_capability` once picked up (per D-019's earlier conflict fix registering `CapabilityType.AUTOMATION_ANYWHERE`), so it inherits Phase D's kill switch/allowlist automatically.

**What changed:**
- Capability-adapter layer (the system's sole intentional network/filesystem surface) now has a single, uniform, testable kill switch and an opt-in host allowlist, plus a real audit trail of outbound egress — closing the last item from the original remediation roadmap's Section 4 ("offline-first architecture — hardened, not just default off").

**What should happen next:**
- Pick up Phase E (Automation Anywhere) if/when prioritized — give it its own full `decisions.md` entry per D-019's note, not a minimal fix.
- Optional follow-up (not blocking): thread a resolvable hostname through `azure_adapter`/`gcp_adapter`'s params if tighter allowlisting is ever needed for those two specifically.

---

## 2026-07-13 — Roadmap Phases A & B: safety/correctness fixes + full removal of AnthropicBackend

**What happened:**
- Worked through a remediation roadmap's Phase A (Section 1 safety/correctness fixes) and Phase B (Section 2: remove Anthropic from the Planner, local LLM only). Full detail in `decisions.md` D-017 (Phase A) and D-018 (Phase B) — this entry is a summary.
- **Verified, not re-fixed:** roadmap items 1.1 (`execute_run` stub) and 1.2 (missing login endpoint) were already resolved in the current codebase before this pass started — the roadmap document was written against an earlier snapshot. Confirmed by reading the actual current source rather than trusting the roadmap's framing.
- **Phase A, actually fixed:**
  1. Split `config/vault.key` (Fernet) from a new `config/jwt.key` (JWT HMAC secret) in `api/security.py` — they were previously the same file doing double duty, so anyone who could read `vault.key` could forge an admin token. Added both to `.gitignore` (neither was ignored before, though `vault.key` was already committed — pre-existing hygiene issue, not rewritten this pass).
  2. `agents/capability/cloud_adapter.py`: added a real second action, `list_objects` (detect-only). Deliberately did **not** add `upload_object`/`delete_object` as an earlier draft of the roadmap suggested — this adapter is detect-only by design (`TRD.md` §9), and adding mutating actions would be a design regression, not a fix.
  3. `agents/capability/db_adapter.py`: added a second, denylist-based check for mutating/exfiltration function calls that can hide inside a syntactically-valid SELECT (`setval`, `pg_terminate_backend`, `lo_export`, `LOAD_FILE`, `INTO OUTFILE`, `EXEC`/`CALL`, `OPENROWSET`, `dblink_exec`, etc.), on top of the existing statement-prefix allowlist. Explicitly documented as a pattern denylist, not a full SQL sandbox.
  4. **Found (not in the original roadmap's framing) and fixed a real bug:** `agents/planner/cross_modal_diagnoser.py::_heal_db_drift()` read `hints.get("exception", "")`, but `db_adapter.py`'s `healing_hints` dict never actually contained an `"exception"` key — the real error text only ever landed one level up in the top-level `evidence` dict. The column-drift regex was therefore always matching an empty string and could never fire. Fixed by including `exception` inside `healing_hints` too. This is exactly the class of bug `docs/debug.md`'s cross-file-consistency check exists to catch — neither file was wrong in isolation, only the contract between them was.
- **Phase B — AnthropicBackend removed entirely, not disabled:** deleted the class, its `anthropic` import, and its `_BACKEND_REGISTRY` entry from `agents/planner/spec_generator.py`; removed `settings.allow_network_calls` from `config/settings.py` (confirmed via grep it had no other consumer before removing); removed the `"anthropic"` branch from `aura/cli/preflight.py`. The Planner now has exactly two backends (`heuristic`, `local_llm`) with no network-capable code path left anywhere in it. `prompts.py` reviewed and left unchanged (already backend-agnostic). Docs (`docs/README.md`'s config table and feature bullets) updated in the same pass so they don't describe a backend that no longer exists.
- 9 new tests added (`tests/test_cloud_workflow_adapters.py` +3, `tests/test_db_adapter.py` +3, `tests/test_preflight.py` +3, one old anthropic-specific test replaced rather than just deleted). Full suite: **267/267 passing.**

**What changed:**
- `api/security.py` — `SecretVault`/`JWTSecretStore` split.
- `agents/capability/cloud_adapter.py` — `list_objects` action, explicit mutating-action rejection message.
- `agents/capability/db_adapter.py` — mutating-function denylist, `healing_hints["exception"]` fix.
- `agents/planner/cross_modal_diagnoser.py` — docstring updated to reflect the fixed data flow.
- `agents/planner/spec_generator.py` — `AnthropicBackend` removed, module/class docstrings updated.
- `config/settings.py` — `allow_network_calls` removed, comments updated.
- `aura/cli/preflight.py` — `"anthropic"` branch removed.
- `.gitignore` — `config/vault.key`, `config/jwt.key` added.
- `tests/test_cloud_workflow_adapters.py`, `tests/test_db_adapter.py`, `tests/test_preflight.py` — new/replaced tests, see above.
- `docs/README.md` — config table and feature-bullet updates (no more `AURA_ALLOW_NETWORK_CALLS`/`anthropic` mentions).
- `docs/decisions.md` — D-017, D-018 added.
- `docs/STATUS.md` — Next-action list updated (vault split marked done, Phase A/B summarized).

**What should happen next:**
- Roadmap Phase C (Playwright interaction layer, `docs/TRD.md` §10 / `docs/Roadmap.md` Phase 20) is now the largest remaining item — everything else in the original roadmap (Phase D offline hardening, Phase E Automation Anywhere) is sequenced after it.
- Roadmap items 1.4 (SQLite run-store persistence, kill-and-restart integration test), 1.9 (Word/PowerPoint adapters), 1.10 (real desktop/mainframe test) remain open, explicitly not silently claimed as done.

---

## 2026-07-05 — Link-check fix: default scope, redirect visibility, client-rendered-page detection

**What happened:**
- User ran `aura explore` against a real deployed site (`personal-portfolio-yashmalik.vercel.app`) and got "No navigable `<a href>` links found in scope='footer'" even though the page clearly has content. Root-caused to two separate, real bugs rather than one:
  1. **Scope hardcoded to `"footer"` at two call sites** — `orchestrator/ui_audit_runner.py::run_exploration()`'s default (`link_check_scope or "footer"`) and `aura/cli/explore_cmd.py`'s explicit `link_check_scope="footer"` — even though `LinkCheckAdapter` itself already defaulted to `"all"` internally. This meant `aura explore` (which is supposed to check *everything*, per its own design) was silently only ever HTTP-checking footer links, regardless of how many nav/body links existed. Fixed both defaults to `"all"`, and exposed it as a new `--link-scope` CLI flag (default `"all"`) instead of a bare hardcode, so `footer`/`nav`-only checks are still available on request.
  2. **Client-rendered (SPA) pages have a real, previously-undisclosed coverage gap.** AURA's link checker fetches raw HTML over plain HTTP with no JS execution (by the same "no DOM automation" design as the rest of the vision pipeline) — if a page's links are injected by React/Next.js/Angular after the initial load, they're not in the HTML AURA sees, and "no links found" looked identical to "nothing to check here," which is misleading. Added `_looks_client_rendered()` (`agents/capability/link_checker.py`), a marker-based heuristic (`id="root"`, `id="__next"`, `ng-version`, etc.) that fires specifically on the zero-links case and adds an explicit, disclosed explanation to the result instead of a bare miss.
- Also addressed the related ask ("check internal transfer redirects too"): `_check_one()` now captures httpx's `resp.history` and reports the full redirect chain (each hop's status code and target, plus the final URL) for every redirected link, rather than silently following redirects and reporting only the end state.
- Did **not** add a headless-browser rendering step (e.g. Playwright) to actually execute JS and see SPA-injected links — that's a real architecture decision (new heavy dependency, changes AURA's "screenshot + OCR, no DOM/browser automation" posture) that deserves an explicit call, not something to silently bundle into a bug-fix pass. Flagged as the natural next step if JS-rendered link coverage is wanted.
- Live-verified against the actual reported URL where possible; the sandbox's network egress allowlist blocked `personal-portfolio-yashmalik.vercel.app` directly, so verification instead used a synthetic Next.js-shell HTML fixture (`id="__next"`, zero anchors) in `tests/test_link_checker.py`, which exercises the identical code path.
- 4 new tests added (`tests/test_link_checker.py`: default-scope-is-all, redirect-chain reporting, client-rendered detection; `tests/test_ui_audit_runner.py`: `run_exploration()` defaults to `"all"` when `link_check_scope` isn't passed). Full suite: **244/244 passing** (up from 240 before this fix), `pyflakes` clean.

**What changed:**
- `agents/capability/link_checker.py` — redirect-chain capture in `_check_one()`, `_looks_client_rendered()` heuristic + honest message on the zero-links path, `redirected_count`/`redirected_links` added to top-level evidence.
- `orchestrator/ui_audit_runner.py` — default `link_check_scope` fixed from `"footer"` to `"all"`, docstring updated.
- `aura/cli/explore_cmd.py` — `link_scope` parameter (was a hardcoded `"footer"` literal), output now labels the check with its actual scope instead of a hardcoded "Footer link check" header, surfaces redirect chains and the client-rendered notice.
- `aura/main.py` — new `--link-scope` flag on `aura explore` (default `"all"`).
- `tests/test_link_checker.py`, `tests/test_ui_audit_runner.py` — new regression tests (above).
- `README.md` — new paragraph under `aura explore` documenting `--link-scope`, redirect visibility, and the disclosed client-rendered-page limitation.

**Known limitations, disclosed rather than hidden:**
- JS-rendered links on client-rendered pages are still not checkable without a headless-browser render step — the fix here is *detecting and honestly reporting* that gap, not closing it.
- The client-rendered heuristic is marker-based (a small set of common root-element IDs/attributes) and will miss frameworks that don't use one of those markers, or false-negative on hybrid SSR/CSR pages that do have some server-rendered anchors alongside JS-injected ones.

**What should happen next:**
- Decide whether headless-browser rendering (Playwright) is worth adding as an opt-in, heavier-dependency mode for sites where JS-injected link coverage actually matters — a real product decision, not bundled into this fix.


## 2026-07-04 (later same day) — Two new autonomy modes: `aura explore` and `--interactive`

**What happened:**
- Built the two genuinely-missing autonomy modes identified in review, rather than the much larger "27-adapter enterprise platform" ask that would need real external systems to test against responsibly:
  1. **`aura explore <url>`** (new command) — give it a URL and nothing else; it navigates, runs the existing full-page scroll/error scan (`orchestrator/autoscan.py`), then clicks every interactive-looking element it can find via OCR across *all* landmark bands (nav/hero/footer/body), not just nav/footer like `--ui-audit`. Generalized `orchestrator/ui_audit_runner.py`'s click-and-diff engine into a shared `_run_click_audit()` used by both the existing `run_ui_audit()` (nav+footer, unchanged behavior) and the new `run_exploration()` (all bands). Added an optional `--prompt` on `explore` for a best-effort keyword-heuristic check against everything seen during exploration — explicitly disclosed as a heuristic in its own output (`_check_requirement_prompt()`), not sold as understanding.
  2. **`aura execute --interactive`** (new flag) — human-in-the-loop mode. New `ActionType.WAIT_FOR_HUMAN_ACTION` step type; `RunEngine.run()` was split into `run()` (Planner + DataSynth) and a new public `run_spec(spec, ...)` (the execution loop alone), so interactive mode can hand-build a two-step spec (optional navigate + one wait-for-human step) and skip the planner entirely. The new branch in `run_spec()` polls the live screen every `settings.human_action_poll_interval_seconds` (default 2s) via the same `screenshot_provider` callback everything else uses, comparing a SHA-256 hash against the baseline, until it changes or an optional `--timeout` elapses (`0`, the default, means wait indefinitely — matches the actual request that execution "should not stop until the human clicks"). Added a `runtime/hooks/capture.py::file_hash()` helper shared by both this and `ui_audit_runner.py` (previously duplicated as a private `_hash_file()`).
  3. **`--autonomous`** added as an explicit, self-documenting alias for `--yes`, so the two modes have clearly distinct names (`--autonomous` vs `--interactive`) instead of one obvious flag and one implicit default.
- **Investigated, then explicitly did not silently "fix," the `auto_approve=True` hardcoding** flagged in review (`execute_prompt()` always unattended, `confirm_spec_approval`/`low_confidence_prompt`/`confirm_heal_accept` only ever called `if not auto_approve`). Confirmed by tracing the code that this is correct behavior for a `--prompt`/`--yes` run, not a bug — there's no per-step list to approve when the person described intent in plain English. The real, previously-missing capability was "act with no instructions at all" (now `explore`) and "deliberately wait for a human mid-run" (now `--interactive`), which is what got built. Documented this reasoning explicitly in README.md's new "Autonomy modes" section rather than leaving it implicit, per the explicit ask to call this out separately.
- Added 8 new tests: `tests/test_human_in_the_loop.py` (3 tests covering the WAIT_FOR_HUMAN_ACTION polling branch — pass-on-change, escalate-on-timeout, on_waiting_for_human callback ticks) and 3 additions to `tests/test_ui_audit_runner.py` covering `run_exploration()` (all-bands clicking, prompt match, prompt no-match). `run_engine.py`'s refactor (`run()`/`run_spec()` split) required no test changes since `run()`'s public signature/behavior is unchanged.
- Full suite: **205/205 passing** (up from 199 before this session's feature work), `pyflakes` clean on all new/changed files.

**What changed:**
- New files: `aura/cli/explore_cmd.py`, `tests/test_human_in_the_loop.py`.
- Modified: `orchestrator/schemas.py` (`ActionType.WAIT_FOR_HUMAN_ACTION`, `TestStep.human_action_timeout_seconds`, `VisionActionResult.action_taken` literal), `config/settings.py` (`human_action_poll_interval_seconds`, `human_action_timeout_seconds`), `orchestrator/run_engine.py` (`run()`/`run_spec()` split, new polling branch, `on_waiting_for_human` callback, `sleep_fn` for testability), `orchestrator/ui_audit_runner.py` (generalized into `_run_click_audit()` + `run_ui_audit()`/`run_exploration()`), `runtime/hooks/capture.py` (`file_hash()` helper), `aura/cli/execute_cmd.py` (`execute_interactive()`), `aura/main.py` (`explore` command, `--interactive`/`--autonomous`/`--timeout` flags on `execute`), `tests/test_ui_audit_runner.py`.
- Docs: `README.md` (new "Autonomy modes" section + command-reference updates), `STATUS.md` (new section for this pass).

**Known limitations, disclosed rather than hidden:**
- `aura explore` doesn't produce an HTML report — `reports/render.py::render_html()` expects a full spec-driven `RunReport` persisted on disk, and `explore` deliberately has neither a spec nor a `RunEngine` pass. Output is terminal + a JSON file under `reports/explore_<run_id>/report.json`. Folding this into the HTML pipeline is a reasonable follow-up, not done here to avoid reshaping `report.html`'s schema as a side effect.
- The `--prompt` requirement check on `explore` is a keyword-overlap heuristic (shared words between the prompt and everything seen on screen), not semantic understanding — it says so in its own output every time, including on a match, not just a miss.
- `--interactive` mode's spec is hand-built (navigate + one wait step) rather than routed through the Planner, so it doesn't support multi-step interactive flows in this pass — one instruction, one wait, one verification per invocation. Chaining multiple `--interactive` steps in one spec is a natural extension, not built here.

**What should happen next:**
- Consider folding `explore`'s findings into the same HTML report template `--ui-audit` already uses, now that both share the same underlying `UIAuditReport` shape.
- Consider allowing `--interactive` to appear as a step type inside a written spec file (not just the CLI's synthesized two-step version), for specs that mix autonomous and human-in-the-loop steps.


## 2026-07-04 — Full debug-QA-finalize pass on the capability-adapter/service-layer code, then doc reconciliation

**What happened:**
- Ran a complete debug-qa-finalize pass over the whole repo (99 `.py` files). All files compiled; the real gap was cross-file schema drift left over from the Roadmap.md Phases 13–19 work (capability adapters + FastAPI service layer), which had never been run as a full suite together before, and had never been written up in `STATUS.md`/this file/`Roadmap.md`/`README.md` at all despite being fully present in the tree.
- `pyproject.toml` had a syntax error (`PyJWT>=2.8"` missing its opening quote) that broke `pip install -e .` outright — fixed.
- `orchestrator/schemas.py`'s `CapabilityResult` had been renamed to `CapabilityCheckResult` at some point, but `orchestrator/capability_adapter.py`, `orchestrator/capability_router.py`, `agents/capability/fake_adapter.py`, and `config/tool_registry.yaml` all still referenced the old name — `ImportError`/`AttributeError` on collection. Renamed consistently everywhere.
- `orchestrator/capability_router.py`'s dispatch function read `payload.step.capability_type`, but `CapabilityCheckInput` has no `step` field (it's `capability`/`target`/`params`/`expected`) — rewrote to use `payload.capability` directly, and kept both `route_capability` and the older `check_capability` name as an alias since both are referenced from different call sites.
- `orchestrator/schemas.py`'s `TestStep` was missing `target`/`expected` fields that `orchestrator/run_engine.py` already read for capability-check steps (`current_step.target`, `current_step.expected`) — this would have thrown `AttributeError` the first time a real `CAPABILITY_CHECK` step ran end to end. Added both fields (`target: str = ""`, `expected: Optional[dict] = None`).
- `agents/capability/fake_adapter.py` constructed `CapabilityCheckResult` with an entirely different, older field set (`step_id`, `capability_type`, `success`, `details`) that doesn't exist on the current schema — would have crashed at runtime the moment the fake adapter actually ran. Rewrote to the current fields (`capability`, `passed`, `confidence`, `evidence`, `escalate`).
- `tests/test_capabilities.py` (3 tests) and `tests/test_16_categories_verification.py` built `CapabilityCheckInput`/`TestStep` against the same stale field names — updated to match the current schema.
- `tests/test_file_doc_adapters.py` had a hand-typed SHA-256 expected value that was simply wrong (`916f00...` vs. the real `e7d87b...`) — corrected.
- `tests/test_cloud_workflow_adapters.py` mocked `httpx.Client(...).post(...)`, but `agents/capability/workflow_adapter.py` actually calls the more general `.request(method, ...)` (to support configurable HTTP methods) — updated the mock.
- Removed a handful of unused imports (`json` in `api/security.py` and `cross_modal_diagnoser.py`, `fastapi.status`, stray `pytest`/`os` imports in three test files).
- Result: **199/199 tests passing** (up from the 156 last recorded here), `pyflakes` clean except two pre-existing dead-branch smells left alone deliberately (see below).
- **Flagged but not silently fixed** (product decisions, not bugs): `agents/capability/cloud_adapter.py` parses `params["action"]` but never branches on it — only `s3_object_exists` is actually implemented, so other actions would silently run the same S3-head-object logic regardless of what was requested. `agents/planner/cross_modal_diagnoser.py` has a few parsed-but-unused locals (`error_type`, `query`, `missing_col`) suggesting an incomplete diagnosis branch.
- **Separately, did a full read-through of all `.md` docs against the actual repo state** (this had not been done since the Phase 13–19 code was written) and found the docs badly out of sync with the code — see the doc-reconciliation pass below.

**Doc reconciliation pass (same session):**
- `Roadmap.md`'s baseline table said "Web UI / REST service / webhooks — Not started" and "Backend/API/DB/Email/Excel/PDF/Cloud adapters — Not started." Both are false — all of it exists in `agents/capability/`, `api/`, and `webui/`. Updated the table and added a "Phase 13–19 status" section reflecting what's actually implemented vs. genuinely still incomplete.
- Discovered, while verifying the service layer for the doc update, that `api/routers/runs.py::execute_run()` is a stub that always reports `"passed"` without calling `RunEngine`, and that there's no endpoint anywhere that calls `api/security.py::create_access_token()` — meaning the API can't actually execute a real run or issue itself a token. Neither gap was documented before. Logged in `STATUS.md` as the top-priority next action rather than fixed silently, since "wire the stub to RunEngine" and "add a login endpoint" are implementation decisions someone should sign off on, not something to guess at during a docs pass.
- `README.md` had no mention of the capability adapters, the FastAPI service, or the web dashboard at all. Added a new section documenting what exists, how to start it (`uvicorn api.main:app`, since there's no `aura serve` command yet — noted as a gap), and an explicit "not production ready" caveat pointing at the `execute_run` stub.
- `STATUS.md` was frozen at 2026-07-03, pre-adapters. Rewritten (see this file's companion update) rather than patched, since most of "Where things stand" needed to change.
- `PHASES.md` and Roadmap.md both referred to the adapter output schema as `CapabilityResult` in prose — updated to `CapabilityCheckResult` to match the code, now that that name is consistent everywhere in the code itself.
- `TRD.md` and `WORKFLOW.md` described only the vision-only execution loop; added a short section to each covering the `CAPABILITY_CHECK` step type and cross-modal healing path, since that's now a real, tested part of the architecture, not a roadmap item.
- `PRD.md` and `APPFLOW.md` reviewed; added brief pointers to the new capability/service surface without rewriting their original vision-first CLI scope, since that scope is still accurate for the primary product.

**What changed:**
- Code: `pyproject.toml`, `orchestrator/schemas.py`, `orchestrator/capability_router.py`, `orchestrator/capability_adapter.py` (rename only), `agents/capability/fake_adapter.py`, `config/tool_registry.yaml`, `api/security.py`, `agents/planner/cross_modal_diagnoser.py`, and five test files.
- Docs: `STATUS.md` (rewritten), `Roadmap.md`, `README.md`, `PHASES.md`, `TRD.md`, `WORKFLOW.md`, `PRD.md`, `APPFLOW.md` (all updated), this file (new entry).
- Test count: 156 → 199, all passing.

**Known limitations, disclosed rather than hidden:**
- The FastAPI service layer is real code but not a working feature yet — see `STATUS.md`'s "service layer" section for the specific gaps (run-execution stub, no token issuance, no `aura serve`, in-memory-only run store, vault/JWT key reuse).
- `cloud_adapter.py`'s unused `action` variable and `cross_modal_diagnoser.py`'s unused locals were deliberately left as flags for a follow-up decision rather than guessed at.

**What should happen next:**
1. Wire `api/routers/runs.py::execute_run()` to the real `RunEngine` — the single highest-value fix now that the docs correctly describe this as a stub.
2. Add a token-issuance endpoint and an `aura serve` CLI command so the API is reachable without out-of-band knowledge.
3. Carry-over from 2026-07-03: run `--ui-audit` for real against a live external site with a display available.


## 2026-07-03 — Comprehensive UI audit + code bug detection ("professional QA tester" feature request)
**What happened:**
- Started with a full debug-qa-finalize pass on the uploaded phase-12 codebase: 119/119 tests passing, `ruff check` clean going in. Found and fixed a repeat instance of the D-011 bug class (unclosed `Image.open()` in `agents/vision/page_health.py`) during the review — same root cause as before, different file. Two tests mocking `Image.open` needed updating to support the context-manager protocol as a result.
- Built `agents/vision/ui_audit.py` + `orchestrator/ui_audit_runner.py`: classifies a page into nav/hero/footer landmark bands via OCR position + vocabulary heuristics, then live-clicks nav/footer elements and screenshot-diffs before/after to flag anything with no visible change as possibly non-functional. Wired to new `aura execute --ui-audit` flag.
- While wiring this into the report, found a real pre-existing gap: `--scroll-test`'s `autoscan_report` was computed and printed to the terminal but never actually passed into `render_html()` — so it never reached the saved report file, only the console. Fixed for both `--scroll-test` and the new `--ui-audit`.
- Built `agents/auditor/code_auditor.py` + `aura debug <path>` command: AST/regex-based bug detection (syntax errors, mutable default args, silently-swallowed exceptions, bare except, TODO markers, unmanaged file handles) plus an optional `ruff` pass. Explicitly detection-only, verified by a dedicated "never modifies the file" test.
- Dogfooded `aura debug .` against AURA's own codebase: found 3 genuine (but intentional/documented) `except NoDisplayError: pass` patterns and 1 known false positive in the auditor's own test file. Both outcomes are honest, expected behavior for a heuristic detector, not the tool malfunctioning.
- Full logged decision: see decisions.md D-013.

**What changed:**
- New files: `agents/vision/ui_audit.py`, `orchestrator/ui_audit_runner.py`, `agents/auditor/code_auditor.py`, `aura/cli/debug_cmd.py`, `tests/test_ui_audit.py`, `tests/test_ui_audit_runner.py`, `tests/test_code_auditor.py`.
- Modified: `agents/vision/page_health.py` (leak fix), `reports/render.py` + `run_report.html.j2` (audit report sections), `aura/cli/execute_cmd.py` + `aura/main.py` (`--ui-audit` wiring, `debug` command), `runtime/hooks/interact.py` (`browser_back`), `tests/test_autoscan.py` (fixed mocks), `tests/test_cli.py` (fixed test double signature).
- Test count: 119 -> 156. `ruff check` clean throughout.

**Known limitations, disclosed rather than hidden:** UI-audit landmark classification is a Y-position + vocabulary heuristic, not real DOM understanding — false negatives on unconventional layouts are expected. The live-click check can't distinguish "broken" from "visually-identical-but-actually-changed" (e.g. a same-looking modal). `code_auditor.py`'s regex checks (`todo-marker`, `unmanaged-file-handle`) can false-positive inside string literals, confirmed by the dogfood run.

**What should happen next:**
- Run `--ui-audit` for real against a live external site with an actual display (only mock-tested so far, same gap category D-009 already closed once for the core executor).
- Reconcile README.md / docs with the accumulated phase 7-12 feature surface.


**What happened:**
- User ran `python -m pytest` on Windows and hit 13 failures, all `OSError: cannot open resource` from Pillow's `ImageFont.truetype()`. Root cause: `target_app/demo_login_app.py` and `tests/test_vision.py` both hardcoded a Linux-only font path (`/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`), which doesn't exist on Windows (or macOS, or a bare Linux box without the `fonts-dejavu` package).
- Fixed by replacing the hardcoded path with `resolve_font(size)` in `target_app/demo_login_app.py`: tries a list of common TrueType font locations across Linux/macOS/Windows, and falls back to Pillow's bundled default font (`ImageFont.load_default(size=...)`) if none exist, so screenshot rendering for tests/demos never hard-fails on missing OS fonts again.
- `tests/test_vision.py` now imports and reuses `resolve_font()` from `target_app.demo_login_app` instead of duplicating its own hardcoded path.
- Verified: (1) resolver still picks up the real DejaVu font on this Linux sandbox, (2) manually forced the "no candidate found" branch to confirm the `load_default()` fallback also produces a working renderable font, (3) full suite re-run: **62/62 passing**.

**What changed:**
- `target_app/demo_login_app.py` no longer assumes a specific OS's font layout — this was the one piece of Phase 5/6 that hadn't actually been run anywhere but this Linux build sandbox until now.

**What should happen next:**
- Re-run `python -m pytest` on the Windows machine that reported the original failure to confirm the fix closes it out there too.


## 2026-07-02
**What happened:**
- Executed the full 6-phase build plan (`PHASES.md`) against the design docs from 2026-07-01. AURA now has a real, runnable, offline codebase, not just documentation.
- **Phase 1 — Scaffolding & core contracts:** `pyproject.toml` (pip-installable, `aura` console script), `config/settings.py`, `config/tool_registry.yaml`, `orchestrator/schemas.py` (pydantic models for every TRD §4 schema), CLI stub (`aura init/execute/schedule/skills`).
- **Phase 2 — Orchestrator kernel:** `orchestrator/kernel.py` (tool registry + dispatch + verbatim JSONL audit trace), `orchestrator/guardrails.py` (warn/hard-stop loop guardrails), `orchestrator/skill_store.py` (SQLite skill library with difflib-based similarity search and `agentskills.io`-compatible export/import), `orchestrator/memory.py` (run-state + escalation queue), `orchestrator/scheduler.py` (APScheduler wrapper). **Logged as D-006:** the Hermes Agent API is replaced by this in-repo kernel, since the external host isn't reachable/pinnable from the build environment — the *contract* from D-003 is preserved exactly, only the dispatch backend changed.
- **Phase 3 — Planner & Auditor agent:** `agents/planner/` — offline heuristic requirement parser (`spec_generator.py`, no network call, deterministic), failure diagnoser (`diagnoser.py`) classifying fixes as `retry_strategy` vs `spec_correction`.
- **Phase 4 — Vision Execution Core:** `agents/vision/` — OCR-based element location (`locator.py`, pytesseract), confidence-gated executor (`executor.py`, 0.75 threshold), assertion checker; `runtime/hooks/` for real screenshot capture (`mss`) and OS interaction (`pyautogui`), both with deferred imports so the rest of the system stays testable without a live display.
- **Phase 5 — Data Synth + integration:** `agents/data_synth/` (Faker-based generator + cache), `orchestrator/run_engine.py` (the real WORKFLOW.md sequencer wiring all agents together), `orchestrator/healing_loop.py` (the self-healing sub-loop with guardrail-checked retries), `target_app/demo_login_app.py` (Tkinter demo app + headless-safe synthetic screenshot renderer for tests). End-to-end test proves a full login-flow run completes, resumes correctly after interruption, escalates cleanly on a genuinely broken app, and reuses cached synthetic data.
- **Phase 6 — Reporting, scheduling, CLI/TUI polish (this session):**
  - `reports/templates/run_report.html.j2` + `reports/render.py` — HTML report generator (summary card, per-step detail, skills-learned section, audit trace) matching APPFLOW §2.6, plus optional PDF export via `weasyprint` (`pip install -e '.[report]'`).
  - `aura/cli/init_cmd.py`, `execute_cmd.py`, `schedule_cmd.py`, `skills_cmd.py` + `aura/tui/live_view.py` — every CLI command now does real work instead of printing a stub: `aura init` (setup wizard → `config/local_config.json`), `aura execute` (spec-approval checklist → live step ticker → low-confidence inline approval → self-healed-step accept/reject → report + Needs-Review queue), `aura schedule` (wraps the Phase-2 scheduler, runs unattended via `auto_approve=True`), `aura skills` (list/export/import).
  - Added optional progress-callback hooks (`on_step_start`, `on_step_result`, `on_skill_learned`) to `RunEngine` so the CLI's live view can observe a run without changing the engine's core control flow or breaking any Phase-5 tests (all default to `None`).
  - Added `SkillStore.delete()` to support the heal-reject path in `aura execute`.
  - New tests: `tests/test_reports.py` (renders a real run's artifacts, checks required sections and consistent numbers), `tests/test_cli.py` (init/skills/schedule commands via `typer.testing.CliRunner`; `aura execute` itself is left to the existing `test_run_engine.py` coverage since it needs a live display).
  - **Bug found and fixed during verification:** the report template and terminal summary were printing raw enum reprs (`RunStatus.PASSED` instead of `passed`) because Python 3.11+ changed `str()` behavior for `StrEnum`-style enums — fixed by using `.status.value` explicitly in both `reports/templates/run_report.html.j2` and `aura/tui/live_view.py`. Also fixed a step-count mismatch where the synthesized final-assertion pseudo-step was being counted in "Passed" but not in "Total steps."
- Full test suite: **62/62 passing** after Phase 6, including the new report/CLI tests, verified twice (before and after the enum/count bug fixes).

**What changed:**
- Project moved from "documentation only" to **feature-complete MVP**, matching every surface promised in `APPFLOW.md` and every requirement in `PRD.md`'s functional requirements table, runnable end-to-end offline against the bundled demo app.

**Known limitations carried forward (see STATUS.md):**
- `orchestrator/run_engine.py` calls agent tool functions directly rather than routing every call through `OrchestratorKernel.call_tool()`, so `trace.jsonl` (the audit trail promised in the report's "Full tool-call/tool-response audit trace" section) is empty for runs produced this way. `reports/render.py` degrades gracefully (renders an empty trace) rather than failing, but this is a real gap between the TRD's described architecture and the current wiring.
- `aura execute` requires a live display (real screenshot capture via `mss`/`pyautogui`); it hasn't been exercised against an actual running target app in this sandbox (no display available), only against the Phase 5 synthetic-screenshot test harness.
- Planner's default backend is a deterministic heuristic parser, not a real LLM — sufficient for the bundled example and tests, but requirement docs outside that pattern range will need either backend improvements or enabling the (currently off-by-default) `AnthropicBackend` path in `spec_generator.py`.

**What should happen next:**
- Decide whether to route `run_engine.py` through the kernel for real audit-trail completeness, or formally accept the current direct-call wiring as good enough and update the TRD to match reality.
- Try `aura execute` against `target_app/demo_login_app.py` on a machine with an actual display, to validate the live capture/interact path that's only unit-tested so far.
- Resolve the still-open items from `decisions.md` (sub-agent runtime choice for anything beyond the heuristic Planner backend, target OS priority, license, repo location).


## 2026-07-01
**What happened:**
- Initial project documentation set drafted: `PRD.md`, `TRD.md`, `WORKFLOW.md`, `APPFLOW.md`, and a project overview README, based on the original "Autonomous Offline Multi-Agent System for End-to-End RPA Test Automation" proposal (June 2026, Prakhar Doneria).
- Revised the full doc set to:
  1. Integrate the **Hermes Agent API** as the multi-agent orchestration layer (replacing the original "sequential Python state handler" design).
  2. Remove all references to specific underlying AI models — sub-agents are now defined purely by role and tool contract (Planner/Auditor, Vision Execution Core, Synthetic Data Generator), invoked via Hermes Agent tool calls.
  3. Remove fixed hardware/system specifications (VRAM, RAM, GPU model) — replaced with a resource-agnostic "compress as far as technically possible, on-demand invocation" philosophy.
- Set up this Obsidian vault folder (`AURA/`) with the four core memory files plus a `docs/` subfolder holding the detailed project documents.

**What changed:**
- Project moved from "raw proposal" to "structured, versioned documentation" (PRD/TRD/WORKFLOW/APPFLOW all at v2.1).

**What should happen next:**
- Confirm the open items in `STATUS.md` (next action, runtime choice, blockers).
- Once confirmed, log that decision in `decisions.md` and update `STATUS.md` accordingly.
