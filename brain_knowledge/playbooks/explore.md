# Playbook: `explore` intent

Human-readable version of `orchestrator/brain/router.py::Router._handle_explore()`.
Kept in sync manually as of Phase B1 — extending
`scripts/check_doc_drift.py` to diff this against the router's actual
call sequence is listed in `docs/AURA_BRAIN_ARCHITECTURE.md` §3 as
follow-on work, not yet built.

1. Normalize the given URL (`runtime/hooks/browser.py::normalize_url`).
2. Generate a `run_id` (`explore_<8 hex chars>`).
3. Open the URL in a real Playwright browser
   (`runtime/hooks/browser.py::open_url`). If this fails, don't abort —
   record the error and proceed assuming the page may already be open
   (matches the CLI's original behavior, preserved through the B1
   migration).
4. Wait `settings.human_action_poll_interval_seconds` for the page to
   settle before the first screenshot.
5. If `scroll_scan` is true (default): run the full-page error scan
   (`orchestrator/autoscan.py::run_autoscan`) — scrolls the whole page
   looking for error-string indicators. This is separate from, and runs
   before, the click-audit below.
6. Run the click-and-diff engine
   (`orchestrator/ui_audit_runner.py::run_exploration`): discover every
   interactive-looking element (nav/hero/body/footer bands, up to
   `max_elements`), click each one, check whether the page changed,
   click back / handle any new tab, move to the next element.
   - If `check_links` is true: also run a real HTTP-level link check
     (`agents/capability/link_checker.py`) scoped by `link_scope`.
   - If a `prompt` was given: keyword-heuristic-match it against what
     was found (disclosed as a heuristic, not certainty — G-004).
7. Return the collected data (autoscan report, click-audit report,
   normalized URL, any open error) to the caller for rendering.

**What this playbook does NOT do (by design, G-000):** it doesn't
decide DOM-vs-OCR itself (that's `agents/vision/ui_audit.py` and
`agents/vision/dom_extractor.py`'s job, inside step 6), and it doesn't
render any output (that's `aura/cli/explore_cmd.py`'s job, after the
Brain returns).
