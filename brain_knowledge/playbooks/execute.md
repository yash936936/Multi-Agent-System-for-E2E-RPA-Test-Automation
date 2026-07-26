---
# Playbook: `execute_spec` / `execute_prompt` intents

Human-readable version of
`orchestrator/brain/router.py::Router._handle_execute_requirement()`
(both `execute_spec` and `execute_prompt` route here — see that
method's own docstring for why one handler serves both kinds). Kept in
sync manually as of Phase B3 (D-075) — extending
`scripts/check_doc_drift.py` to diff this against the router's actual
call sequence is listed in `docs/AURA_BRAIN_ARCHITECTURE.md` §3 as
follow-on work, not yet built.

1. If a `built_spec` was given (D-079, api/routers/runs.py's "guided"
   mode: the caller already assembled a `TestSpec` from structured JSON
   steps), skip straight to step 4 — there is no free-text requirement
   to plan from.
2. Otherwise, try to extract a navigate-to URL from the requirement
   text (`agents/planner/spec_generator.py::extract_navigate_url`). If
   found, snapshot the target page's elements
   (`agents/planner/page_grounding.py::snapshot_page_elements`) so the
   planner has real page context, not just the raw text.
3. Generate a `TestSpec` from the requirement text + page context
   (`agents/planner/tool.py::generate_spec`, Planner.generate_spec).
4. Unless `auto_approve` is set, hand the spec to the caller's
   `approve_spec` callback (CLI: the spec-review checklist in
   `aura/tui/live_view.py`; API: always auto-approved, since there's no
   human in the loop for a background run). If rejected, stop here and
   return `cancelled=True` — no run happens.
5. If `refresh_data` is set, clear this spec's cached synthetic-data
   record (`agents/data_synth/cache.py::clear_cache`) so fresh data is
   generated this run instead of reusing a stale cache entry.
6. Build a fresh `RunEngine` (own `SkillStore`/`RunMemoryStore`, one per
   call — no shared process-wide instance, per Phase J/D-031) and run
   the spec:
   - `built_spec` given → `RunEngine.run_spec(spec, ...)` directly,
     skipping Planner entirely a second time.
   - Otherwise → `RunEngine.run(requirement_text, ...)`, which
     re-derives the spec internally via `Planner.generate_spec` (the
     spec generated in step 3 above is used only for the approval gate
     in step 4; `RunEngine.run()` always plans fresh, matching this
     handler's pre-migration behavior in `execute_cmd.py`).
   - `run_id` is the caller's override if one was given (API callers,
     which pre-create a `run_store` row under their own UUID); otherwise
     derived from `spec.test_id`.
7. For every skill the run learned via self-heal, ask the caller's
   `confirm_heal_accept` callback whether to keep it (skipped when
   `auto_approve` is set — auto-approved runs keep every learned skill
   without asking). A rejected skill is deleted from the `SkillStore`.
8. If `scroll_test` is set: run the full-page error scan
   (`orchestrator/autoscan.py::run_autoscan`) against the same run_id,
   after the spec's own steps finish.
9. If `ui_audit` is set: run the click-and-diff landmark audit
   (`orchestrator/ui_audit_runner.py::run_ui_audit`) against the
   navigate-to URL found in step 2, same run_id.
10. If either `scroll_test` or `ui_audit` ran, close the browser
    session (best-effort — a close failure here is swallowed, since the
    run itself already completed).
11. Return the collected data (spec, run result, autoscan/ui_audit
    reports, nav_url, memory store, `cancelled=False`) to the caller for
    rendering.

**Callback injection, not an event stream (see `router.py`'s module
docstring, decision 1):** every place this handler used to call
`live_view` directly — spec approval, per-step progress, the
low-confidence inline prompt, heal accept/reject — is now a callback
the caller builds and passes in via `Intent.params`
(`on_step_start`/`on_step_result`/`on_skill_learned`/`approve_spec`/
`confirm_heal_accept`/`on_scan_progress`). This handler never imports or
calls `live_view` itself; it just forwards these closures to
`RunEngine`/the approval points where they were always called from.

**What this playbook does NOT do (by design, G-000):** it doesn't
decide DOM-vs-OCR or how a step actually gets dispatched (that's
`agents/vision/executor.py`'s job, inside `RunEngine`), and it doesn't
render any output — reports (`render_json`/`render_html`/PDF/JUnit) and
the final run-summary print stay in `aura/cli/execute_cmd.py`, after
the Brain returns.
