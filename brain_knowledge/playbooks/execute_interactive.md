---
# Playbook: `execute_interactive` intent

Human-readable version of
`orchestrator/brain/router.py::Router._handle_execute_interactive()`.
Kept in sync manually as of Phase B3 (D-075) — extending
`scripts/check_doc_drift.py` to diff this against the router's actual
call sequence is listed in `docs/AURA_BRAIN_ARCHITECTURE.md` §3 as
follow-on work, not yet built.

1. Generate a `run_id` (`interactive_<8 hex chars>`).
2. Hand-assemble a minimal `TestSpec` with at most two steps:
   - If a `url` was given: a `NAVIGATE_URL` step to it first
     (`runtime.hooks.browser::normalize_url` applied).
   - A `WAIT_FOR_HUMAN_ACTION` step, always present, carrying the
     given `prompt` as its `target_description` and `timeout` (0 means
     no timeout) as `human_action_timeout_seconds`.
3. Build a fresh `RunEngine`, wiring the caller's `on_waiting` callback
   through as `on_waiting_for_human` (see `router.py`'s module
   docstring, decision 1 — this is the same callback-injection pattern
   `execute_spec`/`execute_prompt` use; this handler never calls
   `live_view` itself).
4. Run the spec directly (`RunEngine.run_spec`, not `.run()` — there's
   no free-text requirement to plan from, the spec is already fully
   hand-assembled) with `keep_browser_open` implied by the
   `WAIT_FOR_HUMAN_ACTION` step's own semantics (the human needs the
   browser open to act in it).
5. Return the run result to the caller for rendering.

**What "interactive" actually means here:** this is AURA pausing to let
a human perform an action it can't (or shouldn't) automate itself —
e.g. "solve this CAPTCHA," "log in with your 2FA device," "manually
navigate to the right account." `RunEngine`'s `WAIT_FOR_HUMAN_ACTION`
step type polls for a screen change (via
`orchestrator/brain/policy.py::Policy.change_detection_method` —
MutationObserver when a live page exists, hash-diff otherwise, per
Phase 4/D-077) and returns control once it detects one, or once the
timeout elapses.

**What this playbook does NOT do (by design, G-000):** it doesn't
decide when a screen change counts as "done" — that's
`RunEngine`'s/`Policy`'s job — and it doesn't render any output; the
CLI's `on_waiting` callback (a per-poll-interval tick print) and the
final run-summary print both stay in `aura/cli/execute_cmd.py`, after
the Brain returns.
