# AURA Re-Architecture Plan

Scope: (1) real integration-test fixture tier, (2) DOM-first dispatch
everywhere + full removal of OS-level mouse/keyboard/screen dependency,
(3) MutationObserver-based change detection replacing pixel-hash-diff,
(4) unified logging/debug infra + `aura explain <run_id>`, (5) CLI
loading/progress UX, (6) the architectural cleanup this all forces.

**Ordering principle:** build the fixture tier *first*, before touching
any core logic. Every phase after that is validated against real HTML
pages with known-correct answers, not against mocks that encode today's
(sometimes wrong) assumptions. This is also why phases 2-4 are sequenced
DOM-first-dispatch → mutation-detection → OS-mouse-removal rather than
ripping OS-mouse out first: each phase leaves the system in a shippable,
fully-tested state, so removal only happens once nothing outside tests
still depends on the fallback.

---

## Phase 0 — Fixture tier (build first, ~2-3 days)

**Why first:** the footer-heading bug, the false-pass bug, and the
`--interactive` bug all slipped through 700+ tests because none of them
run against a real page with a *known* right answer. Unit tests with
mocks encode assumptions; they can't catch "the assumption itself was
wrong." Everything else in this plan gets graded against this tier.

**Deliverables:**
- `tests/fixtures/pages/` — a handful of small, static, self-contained
  HTML files (no external network), each with a documented answer key:
  - `basic_marketing_site.html`: real `<nav>`, hero section with an
    `<h1>`+CTA, a footer with a heading (`<h2>Get In Touch</h2>`, not a
    link) and a real `<a>` link (mock LinkedIn-style, `target="_blank"`),
    one genuinely dead button (`<button>` with no handler), one working
    button that toggles visible DOM state.
  - `spa_like_no_reload.html`: click-driven DOM mutation without
    navigation (tests MutationObserver path specifically).
  - `icon_only_nav.html`: nav built from icon buttons with `aria-label`
    but no visible text (tests DOM ground-truth catching what OCR can't).
  - `tall_scroll_page.html`: for `--no-scroll-scan` / scroll-direction
    regression coverage.
- `tests/fixtures/answer_keys.py` — machine-readable expected results per
  fixture (`has_nav=True`, `footer_heading_is_not_clickable=True`,
  `dead_button_id="..."`, `working_link_id="..."`, etc.).
- `tests/integration/test_explore_against_fixtures.py` — runs real
  Playwright (headed off, real Chromium — this tier is the one place
  allowed to require the browser binary; CI must install it) against
  `file://` URLs of the fixtures above, asserts the *actual* audit
  report matches the answer key: footer heading not in `checked` as
  clickable, dead button reports `state_changed=False`, working link
  reports either a same-page mutation or `new_tab_opened=True`, nav/hero/
  footer all detected.
- Mark this tier explicitly (`@pytest.mark.integration` or a separate
  `tests/integration/` dir excluded from the fast unit run) so
  `pytest -q` stays fast, and add `pytest -q -m integration` (or
  `pytest tests/integration/`) as a required CI gate whenever a browser
  binary is available, with a documented skip when it isn't (matching
  the existing `NoDisplayError`/Chromium-unavailable posture, but as an
  explicit skip, not a silent pass).

**Exit criteria:** fixtures + answer keys committed; test file exists but
is *expected to fail* against current `main` (that failure is proof the
tier is catching real gaps) — captured in a `docs/decisions.md` entry as
the tier's baseline before Phase 2-4 fixes land.

---

## Phase 1 — Unified logging/debug infrastructure (foundation, ~2 days)

**Why before the dispatch rewrite:** phases 2-4 are the riskiest, most
invasive changes in this plan. Doing this first means every change after
it is *observable* from day one, instead of debugging the dispatch
rewrite with print statements and then unifying logs afterward.

**Current state (real, already exists, keep):**
- `orchestrator/decision_trace_log.py` — planner backend / capability /
  network-retry decisions, JSONL.
- `orchestrator/assertion_audit_log.py` — assertion verdicts, JSONL.
- `config/logging_setup.py` — prose logs to `logs/aura.log`.
- `orchestrator/audit_logger.py` — compliance (who/what/tenant), separate
  concern, out of scope here.

**What's missing and gets built:**
- `orchestrator/click_resolution_log.py` — new, same JSONL shape as the
  other two. One record per click-audit element decision:
  `{run_id, step_id, label, band, source (dom|ocr|dom_extractor_direct),
  looks_interactive, rejected_reason (vocab_miss|no_dom_match|None),
  resolution_strategy, clicked, change_detection_method
  (mutation_observer|hash_diff), state_changed, new_tab_opened}`.
  This is the exact gap today's session hit: `resolution_strategy`
  existed on `ClickCheckResult` but nothing logged *why* an element was
  or wasn't a candidate in the first place.
- `orchestrator/run_timeline.py` — a merge layer, not a new log. Reads
  all three (+ compliance log optionally) JSONL files filtered by
  `run_id`, interleaves by timestamp into one ordered timeline of typed
  events. This is what `aura explain` renders; it owns no state of its
  own.
- Every existing silent-except site and every new one goes through one
  shared helper, `runtime.errors.log_and_continue(logger, msg, exc,
  **fields)`, instead of ad hoc `logging.getLogger(__name__).debug(...)`
  calls — keeps `scripts/check_silent_excepts.py`'s job easy and gives
  every swallowed exception a consistent, greppable shape.

**`aura explain <run_id>` command (`aura/cli/explain_cmd.py` +
`aura/main.py`):**
- Prints the merged timeline: planner backend attempts/escalations,
  every click-audit decision (candidate → accepted/rejected → clicked →
  change-detection verdict), every assertion check, in chronological
  order, human-readable.
- `--json` flag for the raw merged timeline (machine-readable, e.g. for
  CI to diff against fixture answer keys).
- `--screenshot` flag: for `explore`/`ui_audit` runs, generate one
  annotated PNG per checked step from the saved baseline screenshot —
  bounding boxes color-coded: green = DOM-confirmed interactive and
  clicked, yellow = clicked but no state change detected, red = OCR
  candidate downgraded by DOM cross-check (rejected before ever being
  clicked), blue = DOM-sourced element with no OCR/text match. This is
  the literal fix for "would have made the footer-heading bug obvious in
  seconds" — needs `Pillow` (already a dependency via the OCR path) for
  drawing, no new dependency.
- Reuses `aura audit-report`'s existing `find_anomalies()` as one section
  of the output rather than replacing it — `audit-report` becomes a thin
  wrapper that calls into the same timeline layer, so there's one
  merge implementation, not two.

**Exit criteria:** `aura explain <run_id>` works end-to-end against a
real `aura explore` run from Phase 0's fixtures, screenshot overlay
visibly shows the footer heading as red/rejected.

---

## Phase 2 — DOM-first dispatch (the core rewrite, ~4-5 days)

**Principle:** DOM is the primary source of truth for *finding* and
*clicking* elements everywhere. OCR becomes a fallback for the one thing
DOM genuinely can't do — reading rendered pixel content when no live
Playwright page/DOM access exists at all (a native desktop app, a PDF
render, or literally no browser session). Today's code already leans
DOM-first for click *dispatch* (`_try_dom_click` first) but element
*discovery* still starts from OCR (`audit_screenshot`) with DOM merged in
as a supplement, and even after today's cross-check, an OCR-only false
positive that happens to sit near a real DOM control still slips
through. This phase flips the primary/fallback relationship.

**`agents/vision/dom_extractor.py` becomes the primary discovery path:**
- `extract_interactive_elements()` already returns tag/role/name/
  position/cursor-style data — extend it to be the *sole* source of
  `looks_interactive` classification when a DOM page is available: a
  real `<a>`/`<button>`/`role="button"`/`onclick`-bearing element (or
  `cursor: pointer` + focusable) *is* interactive; a `<h2>` heading is
  not, full stop, no vocab list needed. This removes the false-positive
  class at the root instead of cross-checking it after the fact.
- `_NAV_VOCAB`/`_CTA_VOCAB`/`_FOOTER_VOCAB` heuristics in
  `agents/vision/ui_audit.py` become the fallback path only, used when
  `dom_page is None` (matches today's `NoDisplayError`/no-browser-session
  posture, e.g. `--browser` not launched, or a screenshot-only preflight
  check).
- Band classification (nav/hero/body/footer) is computed once, from
  whichever source ran (DOM when available, OCR-position fallback
  otherwise) — no more OCR-then-merge-then-recompute-landmarks dance;
  today's Phase-U-era merge/cross-check logic in
  `orchestrator/ui_audit_runner.py` gets deleted, not layered further.

**`orchestrator/ui_audit_runner.py::_run_click_audit` rewrite:**
- New flow: `if dom_page is not None: elements = dom_extractor path
  (primary)  else: elements = ocr path (fallback, same as today's
  audit_screenshot)`. One path executes per run, not both merged.
- Click dispatch: `dom_click(locator)` via accessible-name/role locator
  resolution (already exists as `_try_dom_click`) stays the only click
  path when DOM is available. The `dom_extractor_direct` (measured
  position, Playwright `page.mouse.click` at DOM coordinates) stays as
  the in-page fallback for elements DOM found but couldn't name — still
  Playwright-dispatched, still viewport-space, never OS-space.
- OCR-based click (`locate_text` + `interact.click`) is retained *only*
  as the last-resort path when there is no live DOM page at all — see
  Phase 3 for what "no OS mouse" means for that remaining case.

**Migration safety:** Phase 0's fixture tier is the acceptance gate here.
This phase is done when every fixture's answer key passes with the new
DOM-first path, and the OCR-vocab path is provably only reachable when
`dom_page is None` (add a unit test asserting this branch condition
directly, not just behaviorally).

---

## Phase 3 — Remove OS-level mouse/keyboard/screen dependency (~3-4 days)

**Current OS-level surface (confirmed by reading the code, not
assumed):**
- `runtime/hooks/interact.py`: `click()`, `type_text()`, `scroll()`,
  `browser_back()` — all via `pyautogui`, OS-absolute-pixel space.
- `runtime/hooks/capture.py`: `capture_screenshot()` — via `mss`,
  full-monitor capture.
- Callers: `orchestrator/autoscan.py`, `orchestrator/ui_audit_runner.py`,
  `agents/vision/executor.py`, plus screenshot callers in
  `agents/planner/page_grounding.py`, `api/routers/runs.py`,
  `aura/cli/execute_cmd.py`, `aura/cli/preflight.py`,
  `aura/cli/explore_cmd.py`.

**Replacement design:**
- **Click/type/scroll:** Phase 2 already makes DOM-first the only
  dispatch path when a page exists. This phase removes the *fallback*
  itself: `interact.click/type_text/scroll` get deleted outright, not
  kept as dead code behind a flag. Every remaining caller either already
  has a live Playwright page (use `page.mouse.click`/
  `locator.fill`/`page.mouse.wheel`, all viewport-space, no coordinate
  translation needed ever again — this also permanently kills the
  coordinate-space-mismatch bug class from your project history) or is
  explicitly a native-desktop-target use case, which AURA's own
  `README.md`/scope docs need to state is **no longer supported** rather
  than silently degrading to a flaky OS-level click. If native-app
  support is actually still a requirement, that's a separate, explicitly
  scoped RPA-adapter effort (e.g. a `pywinauto`-based adapter with its
  own accessibility tree, same DOM-first philosophy applied to Windows
  UIA) — not a reason to keep `pyautogui` as a silent fallback in the
  browser-testing path.
- **`browser_back()`:** replaced everywhere by `page.go_back()` (already
  used inside `dom_smart_back`) or removed where today's fix made it
  conditional on real navigation — no OS keystroke path needed.
- **Screenshots:** `capture_screenshot()`'s `mss` full-monitor capture
  gets replaced by `page.screenshot()` (Playwright-native, viewport or
  full-page, no monitor/DPI/multi-screen ambiguity at all) for every
  call site that has a live page — which, post-Phase-2, is effectively
  all of them during an active run. `mss` stays only for the narrow
  "explicitly given `--url` isn't AURA's own browser session, e.g. the
  `--interactive` human-in-the-loop mode watching an arbitrary
  already-open window" case — and even that should be revisited: if
  `--interactive` always opens its own Playwright-controlled tab (it can,
  per `execute_interactive`'s existing `NAVIGATE_URL` step), `mss` can be
  removed entirely too. This needs one explicit product decision, called
  out below.
- **`NoDisplayError`/`display_guard()`:** keeps existing shape but its
  meaning narrows to "no live Playwright page/browser session," not "no
  OS display" — rename consideration (`NoDisplayError` →
  `NoBrowserSessionError`, with a deprecated alias for one release) so
  the exception name matches what it actually means post-migration.

**Open product decision to resolve before this phase starts:** does
`--interactive` mode ever need to watch a window AURA didn't launch
itself (e.g. a native app, or a browser tab opened outside AURA)? If
no — `mss`/`pyautogui` are removed as dependencies entirely. If yes —
that one narrow path is documented and kept, isolated behind a single
clearly-named module (`runtime/hooks/os_fallback.py`) instead of being
threaded through the main execution/audit paths as it is today.

**Exit criteria:** `pyautogui` and `mss` either fully removed from
`pyproject.toml`, or reduced to the one documented, isolated fallback
module above; Phase 0's fixture tier still green; `CONVENTIONS.md`'s
coordinate-space section gets deleted (nothing left to document once
there's only one coordinate space, Playwright's own).

---

## Phase 4 — MutationObserver-based change detection (~3 days)

Sequenced after Phase 2/3 because it only applies "wherever a live page
exists" — which, after Phase 2, is the default case, so this phase's
payoff is maximized once DOM-first dispatch is already the norm.

**Design:**
- `agents/vision/dom_change_detector.py` (new): before a click,
  `page.evaluate()` installs a `MutationObserver` on `document.body`
  (childList + attributes + subtree), capturing added/removed/changed
  node summaries plus URL, into a JS-side buffer. After the click (and a
  short settle wait, reusing existing `settings.human_action_poll_interval_seconds`-style
  timing), a second `page.evaluate()` reads the buffer back: did
  anything real mutate (excluding a small denylist of known-noisy nodes
  — ad iframes, analytics beacons, animation-only class toggles the
  project already has some notion of from D-056's OCR-noise work)? Also
  captures `location.href` before/after directly, so a `go_back()` or
  real navigation is caught structurally, not inferred from a hash diff.
- Returns a structured result: `{mutated: bool, mutation_count: int,
  url_changed: bool, sample_mutations: [...]}` — logged into the new
  `click_resolution_log.py` from Phase 1, so `aura explain` can show
  *which specific DOM nodes changed*, not just "changed: yes/no."
- **Fallback:** `agents/vision/assertions.py`'s existing pixel-hash-diff
  (`file_hash` comparison) is kept, used only when `dom_page is None`
  (matches Phase 2's discovery fallback exactly, same condition, one
  mental model for "when does AURA fall back to vision-only mode").
- `orchestrator/ui_audit_runner.py`'s `state_changed` field becomes
  `state_changed: bool` derived from `mutated or url_changed` when DOM
  available, else the existing hash-diff bool — same field name/shape
  downstream (reports, `aura explain`, JSON output) so this doesn't
  ripple into report schemas, just changes how the bool gets computed
  and adds a `change_detection_method` field alongside it for
  transparency.
- `orchestrator/run_engine.py`'s `WAIT_FOR_HUMAN_ACTION` branch: the
  polling loop (`file_hash(latest_path) != baseline_hash`) gets the same
  treatment when a live page is open — `MutationObserver` polling
  instead of screenshot-hash polling, which is also strictly cheaper
  (no repeated screenshot capture needed at all during the wait, just a
  cheap `page.evaluate()` poll) and removes another `capture_screenshot`
  call site ahead of Phase 3.

**Exit criteria:** Phase 0's `spa_like_no_reload.html` fixture (DOM
mutation without navigation) passes; a fixture with only a CSS
animation/pure visual noise (no real mutation) correctly reports
`state_changed=False` where the old hash-diff approach would have
false-positived.

---

## Phase 5 — CLI loading/progress UX (~1-2 days, can run in parallel with any phase above)

**Design:**
- `aura/tui/live_view.py` already owns the `console` (rich-based, given
  `console.print` calls throughout). Add a shared helper,
  `live_view.spinner(message)`, a thin wrapper over `rich.status.Status`
  (or `rich.progress` for steps with a known count, e.g. "clicking
  element 4/12") — no new dependency, `rich` is already in use.
- Applied at every currently-silent wait: browser launch
  (`browser.open_url`), the initial page-load sleep in `explore_cmd.py`,
  each autoscan scroll step, each click-audit element (replace the
  current plain `console.print` announcing "Clicking every detected
  element..." with a live-updating status line that ticks per element:
  `Clicking element 4/12: "Sign Up" (nav)...`), the planner LLM call
  (`spec_generator.py` — this is the ~9s dead-air case from the pasted
  log; a spinner here is the highest-value single placement, since it's
  the longest silent wait in the whole system), and the
  `WAIT_FOR_HUMAN_ACTION` poll loop (already has `on_waiting` — thread
  the spinner through that existing callback instead of `console.print`
  per tick).
- Respect `--json`/non-interactive/CI output modes: `rich.status.Status`
  degrades gracefully when not attached to a real TTY (prints plain
  lines instead of animating) — verify this explicitly with a test that
  runs a command with stdout piped to a file, not just eyeballed in a
  terminal.

**Exit criteria:** every command that can take >1s of silent wait has a
visible status/spinner; piping output to a file produces clean
non-animated log lines, not raw ANSI escape codes.

---

## Phase 6 — Documentation & architecture write-up (~1 day)

- `docs/decisions.md`: one consolidated entry (not scattered across
  micro-phases like the historical D-0xx pattern) documenting this as a
  deliberate re-architecture pass, with before/after diagrams of the
  dispatch flow (OCR-primary+DOM-cross-check → DOM-primary+OCR-fallback)
  and the change-detection flow (hash-diff-always →
  mutation-observer-primary+hash-diff-fallback).
- `CONVENTIONS.md`: remove the coordinate-space section (Phase 3 deletes
  the whole problem it was documenting), add a "when does AURA fall back
  to OCR/hash-diff" section stating the single condition (`dom_page is
  None`) that governs both fallbacks, so it's one rule to remember, not
  two independent ones that happen to coincide.
- `README.md`: update "Autonomy modes" section to state the native-app/
  OS-level scope decision from Phase 3 explicitly, whichever way it's
  resolved.

---

## Sequencing summary

| Phase | Depends on | Est. | Risk |
|---|---|---|---|
| 0. Fixture tier | — | 2-3d | Low — additive only |
| 1. Unified logging + `aura explain` | 0 (for validation) | 2d | Low — additive only |
| 2. DOM-first dispatch rewrite | 0, 1 | 4-5d | **High** — core path rewrite |
| 3. Remove OS-mouse dependency | 2 | 3-4d | Medium — deletion, needs the product decision on `--interactive` scope |
| 4. MutationObserver change detection | 2, 3 | 3d | Medium — new JS injection surface |
| 5. CLI spinners | none (parallelizable) | 1-2d | Low |
| 6. Docs | all above | 1d | Low |

**Total: ~16-20 working days** for one engineer working sequentially;
phases 1 and 5 can run in parallel with 0 to compress the front end by
~2 days.

**Non-negotiable gate between every phase:** Phase 0's fixture-tier
integration tests plus the full existing unit suite (700+ tests) both
green before moving to the next phase — this plan explicitly avoids
the historical pattern of layering phase N+1 on top of an unverified
phase N.
