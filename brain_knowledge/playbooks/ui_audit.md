---
# Playbook: `ui_audit` intent

Human-readable version of
`orchestrator/brain/router.py::Router._handle_ui_audit()`. Kept in sync
manually as of Phase B3 (D-075) — extending
`scripts/check_doc_drift.py` to diff this against the router's actual
call sequence is listed in `docs/AURA_BRAIN_ARCHITECTURE.md` §3 as
follow-on work, not yet built.

1. Normalize the given URL (`runtime/hooks/browser.py::normalize_url`).
2. Generate a `run_id` (`ui_audit_<8 hex chars>`).
3. Open the URL in a real Playwright browser
   (`runtime/hooks/browser.py::open_url`). If this fails, don't abort —
   record the error and proceed (same non-fatal-open pattern as the
   `explore` playbook's step 3).
4. Wait `settings.human_action_poll_interval_seconds` for the page to
   settle before the first screenshot.
5. Run the landmark audit
   (`orchestrator/ui_audit_runner.py::run_ui_audit`, up to
   `max_elements`): classify what's on the page into nav/hero/footer/
   body bands (DOM-first when a live page exists — Phase 2/D-073 —
   falling back to OCR classification otherwise, which as of Gap #2/
   D-079 actually reads its vocab/band-boundary rules from
   `brain_knowledge/rules/discovery.yaml`/`bands.yaml` via `Policy`
   rather than a hardcoded Python literal), then click through the
   interactive-looking elements found and check whether the page
   changed for each one.
   - Because this handler always passes the normalized URL as
     `page_url`, the real HTTP-level link check
     (`agents/capability/link_checker.py`) always runs too, scoped by
     `link_scope` (default `"all"`) — unlike `explore`'s playbook,
     where the link check is opt-in via a separate `check_links` flag.
     Best-effort: if the check itself fails, it degrades silently to
     the OCR-only click-audit result (`link_check_result` stays
     `None`), per `run_ui_audit()`'s own docstring.
6. Return the collected data (normalized URL, any open error, the
   landmark/click-audit report) to the caller for rendering.

**Standalone by design (see `router.py`'s module docstring, decision
2):** `aura ui-audit <url>` is a real, minimal CLI command in its own
right, not a flag on `execute` with nothing left to migrate — it reuses
`orchestrator/ui_audit_runner.py::run_ui_audit` exactly as the existing
`execute --ui-audit` flag already does (see `execute.md`'s step 9),
just without a full spec run wrapped around it. Neither adds new
capability; both just expose the same existing internal path two
different ways.

**What this playbook does NOT do (by design, G-000):** it doesn't
decide DOM-vs-OCR itself (that's `agents/vision/ui_audit.py` and
`agents/vision/dom_extractor.py`'s job, inside step 5, governed by
`Policy.discovery_source()`), and it doesn't render any output — that's
`aura/cli/ui_audit_cmd.py`'s job, after the Brain returns.
