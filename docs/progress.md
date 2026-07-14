---
type: progress-log
project: AURA
---

# Progress Log

> Dated entries only. Don't edit past entries — append new ones. Newest at the top.

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
