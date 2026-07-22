# Code audit report

Files scanned: 21

- **[warning]** `agents\vision\executor.py:114` (silent-exception-swallow) — except NoDisplayError: caught and silently ignored (bare 'pass') — errors here vanish without a trace.
- **[warning]** `agents\vision\executor.py:54` (silent-exception-swallow) — except BrowserNoDisplayError: caught and silently ignored (bare 'pass') — errors here vanish without a trace.

---

## Phase 0 — Full-tree static pass + pytest baseline

Scope: whole repo (186 Python files under `audit_path()`'s filters), plus `ruff` as the
supplementary lint layer, plus a full `pytest` run for the baseline pass count. No fixes
applied in this pass — findings only, per the "detect, don't fix silently" rule.

### AST pass (`code_auditor.audit_path('.', run_ruff=False)`)

Files scanned: 186. Errors: 0. Warnings: 27 — all `silent-exception-swallow`
(bare `except: pass` / `except Exception: pass`). Full list is reproducible via the same
call; the two most relevant to the phases ahead:

- **`orchestrator/ui_audit_runner.py:335`** — `except NoDisplayError: pass`. Directly
  relevant to Phase 3 (OCR/DOM bug hunt) — this swallow sits in the same runner that
  drives `--ui-audit`, so if `get_page()` is raising `NoDisplayError` on the run that
  looked "OCR only," this is a candidate spot where that signal could be getting eaten
  silently instead of surfacing. Worth instrumenting first per the Phase 3 plan.
- **`runtime/hooks/interact.py`** (lines 155/159/163/168/175) — five separate silent
  swallows clustered in the OS-input hook file that Phase 2 is about to touch. Worth
  reviewing alongside the cursor-coordinate fix, since silent failures here could mask
  whether a fallback path fired.

The rest (`api/security.py`, `install.py`, `runtime/hooks/browser.py`, etc.) are lower
priority — mostly advisory/best-effort cleanup paths — logged for completeness, not
flagged as urgent.

### Ruff pass

9× `E701` (multiple statements per line), 8× `F401` (unused import), 1× `E402`, 1×
`F541`, 1× `F841`, 1× `F821`. Two worth calling out as real bugs rather than style noise:

- **`aura/cli/execute_cmd.py:69`** — `F821 undefined name 'console'`. Confirmed real:
  `execute_cmd.py` never imports or constructs a `Console` (unlike `baselines_cmd.py` /
  `debug_cmd.py`, which both do `from rich.console import Console; console = Console()`).
  `_print_validation_warnings()` will raise `NameError` the first time a spec produces
  validation warnings and this function actually runs. Not yet fixed — flagged per the
  detect-don't-fix rule — but this is a one-line import + instantiation fix matching the
  existing pattern in the sibling CLI files.
- **`agents/capability/automation_anywhere_adapter.py:483`** — `F841`, `except
  subprocess.TimeoutExpired as e` where `e` is never used. Harmless but worth a pass
  when that file is touched — silently dropping the timeout detail makes debugging
  timeouts harder.

### Pytest baseline

`613 passed, 27 failed, 5 errors` (up from the "229+" prior baseline noted in the plan —
big jump, likely reflects a lot of work landed since that number was recorded).

All 27 failures + 5 errors are the **same root cause**: this sandbox has no Chromium
binary at the Playwright cache path (`/opt/pw-browsers/chromium-1228/...`), so every test
that launches a real browser raises `NoDisplayError: ... Executable doesn't exist ...`.
This is an environment gap, not an application bug — confirmed by the failure list being
exactly the browser-dependent suites: `test_accessibility_adapter`, `test_browser_hook`,
`test_cross_browser`, `test_dom_locator`, `test_link_checker` (one test),
`test_performance_adapter`, `test_run_engine_trace`, `test_run_engine_video`, and
`test_executor_dom_path` (5 errors, same cause, at fixture setup).

This sandbox can't run `playwright install` (its CDN isn't in the allowed egress list
here), so this baseline can't be pushed past 613 in this environment. On your machine,
where Chromium is presumably already installed (given the taskbar-jump bug report implies
real runs happening), re-run `pytest -q` and the true baseline should be all ~640
collected tests, modulo whatever Phase 2/3 work is mid-flight.

### Manual review order (not yet started)

Per the plan: `runtime/hooks/*` → `agents/vision/*` → `orchestrator/run_engine.py` +
`capability_router.py` → `orchestrator/hermes_client.py` + `agents/planner/*` → rest.
Static pass above already narrows the first two subsystems to specific line numbers
worth opening first (`interact.py`'s five swallows, `ui_audit_runner.py:335`,
`executor.py:114`/`:54` from the prior partial scan above).

### Fixed

- **`aura/cli/execute_cmd.py:69` `F821 undefined name 'console'`** — fixed. Added
  `from rich.console import Console` and module-level `console = Console()`, matching
  the existing pattern in `baselines_cmd.py`/`debug_cmd.py`. Re-ran `ruff check` on the
  file (clean) and `tests/test_cli.py` (21 passed, no regressions). No existing test
  exercised `_print_validation_warnings()` directly, which is why this shipped
  undetected — worth a follow-up unit test but not blocking.

---

## Phase 1 — Continuous-audit / Auditor agent (implemented)

New file: `agents/auditor/run_monitor.py`. Two functions, no class needed
(matches this codebase's function-first style in `executor.py`/`spec_generator.py`):

- `review_step(step, result) -> MonitorVerdict` — independent second opinion on
  whether a vision step's self-reported outcome (`confidence`, `assertion_passed`,
  `verification_method`/`verification_evidence`) actually supports "fulfilled," as
  opposed to just re-checking the step's own confidence number. Text-over-evidence,
  not vision-over-screenshot — reuses `agents/vision/llm_verifier.py`'s existing
  `_get_backend_client()` (Hermes-then-cloud precedence, egress-allowlist check
  already fixed there) rather than standing up a second HTTP client. Fails soft always:
  no backend configured, unreachable, or unparseable reply → `agrees=True,
  checked=False`, never blocks or falsely flags a run.
- `log_verdict(run_id, verdict)` — writes every verdict (agree/disagree, checked or
  not) through the existing `orchestrator/audit_logger.py` sink, `action =
  "CONTINUOUS_AUDIT_VERDICT"`.

Wiring in `orchestrator/run_engine.py`: new `run_spec(..., continuous_audit:
bool | None = None)` param (`None` → `settings.enable_continuous_audit`, which
defaults `False` — new setting in `config/settings.py`, same off-by-default posture
as `enable_llm_semantic_verifier`). When on, the hook runs in the vision-execution
branch, after the assertion/visual-diff checks and *before* `aggregator.record_step_result()`,
so a disagreement's re-heal replaces what actually gets recorded rather than logging
a correction after the fact. On disagreement, reuses the same `healing_loop` object
already constructed for the step's own escalation path — `healing_loop.heal()` with
`escalate` forced `True` — no second retry mechanism built, per the plan's explicit
"reuse, don't duplicate" instruction. Gated on `not result.escalate` (an
already-escalated step has nothing new to second-guess).

Not yet wired: a `--continuous-audit` CLI flag on `aura execute` (the plan calls for
one; `run_spec()`'s param is ready for it, just needs a `typer` option added to
`execute_cmd.py` — small follow-up, didn't want to touch that file twice in one
session without you seeing this shape first). Also not yet extended into the
`CAPABILITY_CHECK` branch (lines ~319-489 of `run_engine.py`) — scoped to the vision
branch first since that's where "confident but wrong" is most plausible; capability
checks already get bot-trigger cross-validation via `bot_validation_group`.

### Verification

- `ruff check` clean on all three touched/new files.
- Manual smoke test: no-backend path → `agrees=True, checked=False`, verdict lands
  in `logs/audit.jsonl` correctly. Stubbed-backend disagreement path → `agrees=False,
  checked=True`, confirmed parses the JSON reply correctly.
- `pytest tests/test_run_engine.py tests/test_run_engine_keep_browser_open.py
  tests/test_cross_modal_healing.py tests/test_code_auditor.py tests/test_cli.py` —
  48 passed, no regressions (continuous_audit defaults off, so existing callers/tests
  are unaffected either way).
- Full suite re-run: **613 passed, 27 failed, 5 errors** — identical to the Phase 0
  baseline, same Chromium-binary-missing cause, no new failures introduced.

---

## Phase 2 — OS-level cursor removal / coordinate fix (implemented)

Ground-truth correction to the original plan: `orchestrator/autoscan.py`'s scroll call
site was **already fixed** in the current repo state — it already prefers
`browser_hook.dom_scroll()` (JS `window.scrollBy`, page-scoped) and only falls back to
`interact.scroll()` when no live page exists. No change needed there.

More importantly, static reading surfaced that **the taskbar-jump bug's real, most
consequential instance isn't `ui_audit_runner.py` (QA-audit mode only) — it's
`agents/vision/executor.py::_dispatch_ocr`**, which every normal `aura execute` run's
`VISUAL_CLICK`/`TYPE_TEXT` steps go through whenever OCR wins the dual-verification
tie-break (`settings.dual_verification_tie_break`, default `"highest_confidence"`) —
which can happen even when a live browser session exists, not only when Playwright/DOM
is unavailable. `ui_audit_runner.py:274`'s instance (the one the original plan named) is
real but narrower in blast radius (only `--ui-audit`/`aura explore`). Fixed both, plus a
same-class scroll issue in `execute_step`'s `SCROLL` branch (unconditional
`interact.scroll()`, same OS-focus-dependency `autoscan.py` already solved).

**Root cause, confirmed by reading (not assumed):** `runtime/hooks/capture.py`'s
`capture_screenshot()` grabs a full-monitor screenshot via `mss.mss().grab()` — physical/
device screen pixels, whole monitor, independent of where the Chromium window actually
sits. OCR's `(x, y)` result is a pixel offset *into that image*. `interact.click()` hands
that number straight to `pyautogui.moveTo()` as an absolute OS coordinate. Nothing in
that chain accounts for the browser window's on-screen position, or a DPI scale factor
between the physical pixels mss captures and the logical pixels pyautogui may operate in
— so any DPI scaling, multi-monitor offset, or non-maximized/non-(0,0) window position
sends the click somewhere else on the real desktop (observed: the taskbar).

**Fix:** new `runtime/hooks/browser.py::get_click_point_in_page(screen_x, screen_y)` —
translates an OCR/mss-pixel coordinate into the live page's own CSS/viewport space using
one Chromium DevTools Protocol call (`Browser.getWindowForTarget`, which reports window
bounds in the same physical-pixel space mss captures in — no separate DPI lookup needed
for that part) plus `window.devicePixelRatio` and `outerWidth/outerHeight -
innerWidth/innerHeight` (both read directly from the live page) to size and subtract the
browser chrome. Returns the translated point, or `None` — never raises — whenever it
can't be computed: no active page, a non-Chromium engine (CDP is Chromium-only, gated on
`settings.playwright_browser == "chromium"`), any transform step failing, or the
translated point landing outside the page's own content area.

`_dispatch_ocr` (executor.py) and the OCR-strategy click in `ui_audit_runner.py` both now
call this first and dispatch via `page.mouse.click()`/`dom_page.mouse.click()` whenever
it returns a point; only fall back to raw `interact.click()` when it returns `None` (a
genuinely non-browser target, or the translation itself failed) — matching the plan's
"keep pyautogui only as a documented last-resort fallback, but fix its coordinate math"
guidance exactly. `ui_audit_runner.py` also had to guard against double back-navigation:
`dispatch_via_playwright` is now set `True` on a successful translated dispatch too, so
it correctly reuses the existing `dom_smart_back` tab-aware return and skips the
redundant OS-level `browser_back()` at the end of the loop.

**Known simplification, stated plainly rather than hidden:** the chrome-size subtraction
assumes standard top-only browser chrome (title bar/tabs/address bar) with no left/right
chrome (an undocked devtools panel, a browser sidebar). True for AURA's own launch
config (`get_page()` launches maximized, devtools closed) but not guaranteed for every
possible window layout — which is exactly why this fails soft into `None` rather than
ever returning a guessed-wrong point silently.

**This could not be verified against a real windowed/DPI-scaled display** — this sandbox
has no display and (per Phase 0/1) can't install the Chromium binary Playwright needs.
Every existing automated test that exercises these call sites mocks Playwright, so they
verify the *dispatch logic* (which path gets called, in what order, with what fallback)
but not the actual on-screen coordinate arithmetic. **This needs a real run on your
Windows machine to confirm the click actually lands correctly** — please try it against
the same scenario that originally showed the taskbar-jump, and report back what happens;
the CDP/DPI math above is my best-effort derivation from Chromium's own documented
behavior, not something I could empirically confirm from this environment.

### Verification

- `ruff check` clean on all three touched files (`runtime/hooks/browser.py`,
  `agents/vision/executor.py`, `orchestrator/ui_audit_runner.py`).
- Static AST audit: still 0 errors / 27 warnings (no new findings).
- `pytest tests/test_ui_audit_runner.py tests/test_autoscan.py tests/test_ui_audit.py`
  (the suites that actually exercise the edited dispatch logic) — 37 passed, no
  regressions.
- Full suite re-run: **613 passed, 27 failed, 5 errors** — identical to the Phase 0/1
  baseline; the Chromium-launch-dependent suites (`test_browser_hook`,
  `test_cross_browser`, `test_executor_dom_path`, etc.) fail/error for the same
  pre-existing missing-binary reason, not because of this phase's changes.

---

## Phase 3 — OCR + DOM working together (bug hunt — real bug found, not a miss)

The plan framed this as "reproduce the OCR-only observation and find why dual-mode
isn't triggering," suspecting either `NoDisplayError` swallowing a signal or a
tie-break quirk. Neither was the actual root cause. What static reading + direct
reproduction found instead: **`_resolve_dom()` in `agents/vision/executor.py` only ever
caught `NoDisplayError`** — raised solely by `browser_hook.get_page()` when no page
exists at all. Everything downstream of that (`locate_dom()`/`relocate_dom()`, which
both call `dom_locator.snapshot_elements()`, which calls Playwright's own
`page.locator("html").aria_snapshot()`) had **no exception handling whatsoever**.

**Verified by direct reproduction, not assumed:** a page mid-navigation, a closed
target, or a detached frame all raise a raw Playwright `Error` there (e.g. *"Execution
context was destroyed, most likely because of a navigation"* — exactly what happens
right after a click that triggers page load, which is a completely ordinary event
during a UI test run). Traced the full path: this propagated uncaught through
`execute_step` → `orchestrator/kernel.py`'s `call_tool` (re-wraps as a failed
`ToolResponse`) → `run_engine.py`'s `call_tool` closure (re-raises as `RuntimeError`) →
the main step loop (no try/except there) → **crashes the entire run**, instead of the
documented "only one method clears the threshold -> proceed on that one" single-method
fallback the dual-verification design is supposed to guarantee.

This is a materially better explanation for intermittent "looks like OCR only" reports
than a genuine dual-verification miss: a step whose DOM snapshot happens to land during
a navigation doesn't quietly prefer OCR, it can take the whole run down — and depending
on which specific steps hit that timing window on a given run, the visible symptom is
inconsistent/unpredictable, which is consistent with what was originally described.

**A third, arguably more exploitable instance of the exact same gap** was found in
`agents/vision/form_fuzzer.py` while checking every call site of
`locate_dom`/`relocate_dom`/`snapshot_elements` (not just the one the plan named) — its
own docstring already promises *"Never raises on an individual field's fill/submit
failure"*, but the DOM *resolution* calls (as opposed to the `dom_fill()`/`dom_click()`
*dispatch* calls, which were already correctly wrapped) had zero exception handling.
The most likely to actually fire in practice: the post-submit re-snapshot
(`agents/vision/form_fuzzer.py`, near the end of `fuzz_form()`) runs immediately after
triggering a form submit — an action whose entire purpose is often to navigate the
page — with nothing catching the same "execution context destroyed" class of error.

`orchestrator/ui_audit_runner.py::_try_dom_click` was checked too and is **already
correctly guarded** (`except Exception: return None`, with a comment naming this exact
scenario) — no change needed there.

`dual_verification_tie_break` (`config/settings.py`, default `"highest_confidence"`)
was also checked per the plan: no bug found there. A consistent OCR-wins-ties pattern
would show up in `verification_evidence` as `"dual-method-confirmed"` with
`tie_break_applied` set — genuinely different from a `"single-method"` result — so it
wouldn't produce the literal "OCR only" symptom on its own. Ruled out as the sole
cause; the crash-on-exception gap above is the confirmed one.

### Fixes

- **`agents/vision/executor.py::_resolve_dom`** — now wraps `locate_dom()`/
  `relocate_dom()` in a broad `except Exception`, logging the actual exception type/
  message and returning `DomLocateResult(found=False)` so OCR's result can still be
  dispatched, matching the documented single-method fallback instead of crashing.
  Every DOM miss is now logged with which of three cases it was (no live page /
  genuine no-match / caught exception) — kept as permanent `info`/`warning`-level
  logging rather than "temporary, stripped after diagnosis" per the original plan,
  since it's cheap (only fires on the already-slower DOM path) and directly useful for
  diagnosing the next report like this one.
- **`agents/vision/form_fuzzer.py::fuzz_form`** — wrapped all four previously-unguarded
  resolution call sites (candidate-field snapshot, per-field locate, submit-button
  locate, post-submit re-snapshot) the same way, each degrading to its existing
  graceful-failure path (skip the field / report "not submitted" / report no markers
  seen) instead of raising, consistent with the function's own pre-existing "never
  raises" contract for the calls that were already wrapped.

### Verification

- Direct reproduction (a fake Playwright page whose `aria_snapshot()` raises "Execution
  context was destroyed…") confirmed the crash at three levels before the fix
  (`_resolve_dom` directly, `execute_step`, and `fuzz_form`) and confirmed it's gone
  after, with the expected graceful degradation in each case (`escalate=True` when OCR
  also has nothing to go on, or a populated `.note` field for `fuzz_form`).
- `ruff check` clean on both files. Static AST audit: 0 errors, 28 warnings (one new,
  intentional, documented `except Exception: pass` in the post-submit re-snapshot guard
  — matches this file's own pre-existing best-effort philosophy just above it).
- `pytest tests/test_form_fuzzer.py` — 6 passed (all pass in isolation; this suite
  doesn't need a real browser binary).
- `pytest tests/test_dom_locator.py tests/test_executor_dom_path.py` — same
  Chromium-binary-missing failures as the established baseline, unrelated to this
  phase's changes.
- Full suite re-run: **613 passed, 27 failed, 5 errors** — identical to the Phase 0/1/2
  baseline, no new failures.

---

## Phase 4 — Hermes / API / LLM backend routing (implemented)

The plan explicitly flagged this as needing operator input before building ("which
backend is good for a specific task is a judgment call, not something to hardcode").
Asked three questions before writing anything; answers: scope and priority were both
"show me trade-offs" (resolved below), availability check was explicit —
**health-check ping first**.

**Scope, decided after laying out the trade-off:** centralize only the two call sites
that already duplicated the exact same Hermes-then-cloud logic (`llm_verifier.py`'s
semantic tie-break, `run_monitor.py`'s continuous-audit monitor from Phase 1) —
`agents/planner/spec_generator.py`'s spec-generation backend selection stays untouched.
That system is materially richer (4-way heuristic/local_llm/cloud_llm/hermes_agent
registry, its own auto-detection matrix, its own runtime escalation policy inside
`generate_spec()`) and already ships/is documented/is tested — unifying it in would mean
either reimplementing that whole system for zero behavior change, or a pass-through
indirection with no benefit. Not worth the risk to working code.

**Priority, decided the same way:** one shared Hermes-then-cloud order for every task
type today — this is a refactor of the existing duplicated logic, not a behavior change.
The plan's own "fast/cheap tie-break vs. higher-quality audit" framing doesn't actually
hold up against how Phase 1 wired the monitor in: it fires at essentially the same
per-step frequency as the tie-break, not less often, so there's no evidence yet that the
two tasks need to diverge. `task_type` is still a first-class parameter from the start
(not retrofitted), with a genuine per-task settings override
(`semantic_tie_break_backend_priority` / `continuous_audit_backend_priority`, both
`None` by default = inherit the shared `backend_router_priority`) for if that ever
changes.

**Availability, per the operator's explicit choice:** a real minimal chat call
(`"Reply with exactly: ok"`), not a bare TCP/HTTP ping — neither Hermes Agent nor an
arbitrary OpenAI-compat endpoint is guaranteed to expose a dedicated health route, so a
raw connection check could pass while the actual `/v1/chat/completions` contract still
fails (wrong model name, auth misconfigured). Costs a small amount of real latency/
tokens per task-that-needs-a-backend, which is the explicit tradeoff chosen.

New: `orchestrator/backend_router.py`, `select_backend(task_type) -> client | None`.
Reuses `HermesAgentClient` as-is and `is_egress_host_allowed()` for the cloud path's
egress check (same allowlist mechanism `CloudLLMBackend`/`HermesAgentClient` already
use) — one implementation of that HTTP+security logic, not a third. As part of wiring
this in, removed the real duplication this created: `llm_verifier.py` had its own
private cloud-chat-adapter class; both `llm_verifier.py::semantic_verify` and
`run_monitor.py::_get_backend_client` now call `backend_router.select_backend(...)`
directly instead of each resolving a backend independently.

### Verification

- Direct smoke tests: no-config → `None`; unreachable Hermes (bad port) → health check
  correctly fails and logs why, falls through to `None` with nothing else configured;
  unreachable Hermes + reachable cloud → correctly falls through to the cloud client;
  per-task priority override (`continuous_audit_backend_priority = "cloud_first"`)
  correctly diverges from the shared default while the other task's order stays
  unaffected.
- Egress allowlist verified directly (not assumed): a disallowed cloud host correctly
  raises and refuses the call.
- `ruff check` clean on all four touched/new files. Static AST audit: 0 errors, 28
  warnings (same count as Phase 3 — no new findings from this phase).
- `pytest tests/test_phase_w_hermes_and_llm_verifier.py` — 25 passed, confirming the
  rewire didn't change either call site's observable behavior.
- Phase 1's `review_step()`/`log_verdict()` re-verified working end-to-end through the
  new router path.
- Full suite re-run: **613 passed, 27 failed, 5 errors** — identical to the established
  baseline, zero new failures.

### One thing worth flagging honestly

A substantial, well-integrated draft of `orchestrator/backend_router.py` (plus its
supporting `config/settings.py` fields) was already present in the working directory
before I wrote anything for this phase — untracked in git, not something I'd written
earlier in this session. Rather than either blindly trusting it or discarding working
code, I verified it directly the same way I'd verify anything: read it fully, confirmed
every settings field it depends on actually exists, confirmed `HermesAgentClient`'s
constructor matches how it's called, and ran it against several real scenarios (no
config, unreachable backend, fallthrough, priority override, egress blocking) before
deciding it was sound and wiring the rest of the phase (both call sites, the
`llm_verifier.py` de-duplication) around it. Flagging this so you know it didn't come
from a step-by-step build in this conversation the way Phases 1–3 did — it was already
sitting there, and I verified rather than assumed.

---

## Phase 5 — Verify Hermes is actually wired (root cause of the original CLI error found)

This explains the exact error pasted at the start of this session:
`hermes: error: argument command: invalid choice: 'api-server'`.

**Root cause, confirmed against Hermes Agent's real, current docs** (not assumed from
memory): there is no `hermes api-server` command in the real CLI. The correct command
is **`hermes gateway`**, after setting `API_SERVER_ENABLED=true` and
`API_SERVER_KEY=<key>` in `~/.hermes/.env`. Once running, it logs
`API server listening on http://127.0.0.1:8642` — **port 8642 by default, not 4141**.

**Both of those wrong values — the nonexistent `hermes api-server` command and the
wrong port 4141 — were baked into AURA's own code and docs in five places**:
`orchestrator/hermes_client.py`'s config-error message and module docstring,
`agents/planner/spec_generator.py`'s config-error message, `config/settings.py`'s
`hermes_agent_base_url` field comment, and two spots in `docs/README.md` (the config
table and the Hermes setup walkthrough). Anyone following AURA's own error messages or
docs literally — exactly what happened here — would hit precisely this dead end. All
five fixed to the real command/port, with a link to Hermes Agent's actual API Server
docs. `docs/README.md`'s setup walkthrough also had a second small inaccuracy fixed
along the way: it described `AURA_HERMES_AGENT_API_KEY` as needed "if [Hermes] requires
one" — Hermes's own docs state `API_SERVER_KEY` is required for every deployment, not
optional, including the default loopback-only bind.

**Also fixed:** `.env.example` had zero mention of any `AURA_HERMES_AGENT_*` variable —
step 1 of this phase ("confirm `AURA_ENABLE_HERMES_AGENT=true` and
`hermes_agent_base_url` are set") had no template to check against. Added a full section
matching the file's existing style, with the corrected port/command guidance inline.

**Verified request/response contract** (step 4 of the plan) by reading
`tests/test_phase_w_hermes_and_llm_verifier.py` directly rather than re-deriving it:
`HermesAgentClient` sends `POST {base_url}/v1/chat/completions` with
`Authorization: Bearer <api_key>`, an OpenAI-format `messages` array, and an optional
`X-Hermes-Session-Id` header; expects back
`{"choices": [{"message": {"content": "..."}}]}`; raises `RuntimeError` on non-200. This
matches Hermes Agent's real, documented `/v1/chat/completions` contract exactly (cross-
checked against the fetched docs above) — no mismatch found there, only the base URL/
command getting you to that endpoint in the first place.

**What still needs a real machine, and can't be done from here** (steps 2–3 of the
plan): confirming an actual Hermes instance is running and reachable, and running
`HermesAgentClient(...).chat(...)` against it directly. This sandbox has no way to run
or reach a real Hermes Agent process. **Once you've run `hermes gateway`** (with the
corrected env vars above), the direct isolation check from the original plan is:

```python
from orchestrator.hermes_client import HermesAgentClient
client = HermesAgentClient(base_url="http://localhost:8642", api_key="<your API_SERVER_KEY>")
print(client.chat("You are a test.", "Reply with exactly: ok"))
```

If that prints `ok` (or similar), Hermes is correctly wired end to end and
`AURA_ENABLE_HERMES_AGENT=true` / `AURA_PLANNER_BACKEND=hermes_agent` (or
`AURA_ENABLE_LLM_SEMANTIC_VERIFIER=true` / `AURA_ENABLE_CONTINUOUS_AUDIT=true` for the
Phase 4/1 paths) should work immediately, since `backend_router.py`'s health check
(Phase 4) uses this exact same call shape.

### Verification

- Confirmed the real CLI command/port against Hermes Agent's current, official docs
  (fetched directly, not recalled from training data) — not assumed.
- `ruff check` clean on all three touched Python files. Static AST audit: 0 errors, 28
  warnings (unchanged from Phase 4 — these are doc/error-message-text-only changes).
- `pytest tests/test_phase_w_hermes_and_llm_verifier.py` — 25 passed, confirming the
  error-message text changes didn't break any `pytest.raises(..., match=...)` assertion
  (all matched substrings are still present verbatim in the corrected messages).
- Full suite re-run: **613 passed, 27 failed, 5 errors** — identical to the established
  baseline, zero new failures.

---

## Wrap-up — `--continuous-audit` CLI flag + manual review + doc-vs-code verification

### `--continuous-audit` flag (Phase 1's last open item)

Added end to end, not just at the top level: `aura/main.py`'s `execute()` command now
has `--continuous-audit` (`typer.Option`), threaded through all five of its dispatch
branches (`--prompt`, `--all` sequential, `--all` parallel, `--url`, `test_id`) into
`execute_cmd.py`'s `execute_prompt`/`execute_url`/`execute_test`/`_run_requirement_text`,
into `RunEngine.run()` (which needed its own new `continuous_audit` param — it didn't
forward arbitrary kwargs to `run_spec()`), through to `run_spec()`'s existing
`continuous_audit` param from Phase 1.

One correctness detail worth being explicit about: the CLI flag is a plain boolean
switch (`False` when not passed), but `run_spec(continuous_audit=None)` means "inherit
`settings.enable_continuous_audit`" specifically so an env-configured default isn't
silently forced back off just because the flag wasn't typed this run. So `main.py`
converts `False` (not passed) to `None` before forwarding, and only `True` (flag passed)
forwards as an explicit override — not a direct pass-through of the raw flag value.

`execute_interactive` (Mode B — AURA doesn't execute steps itself, just polls for a
human to act) deliberately does not get this flag; there's nothing for the monitor to
review in that mode.

Confirmed with a real test, not just by reading the diff: `runner.invoke(app, ["execute",
"--help"])` shows the flag; a new `test_continuous_audit_flag_reaches_engine_run` in
`tests/test_cli.py` patches `RunEngine.run` itself and asserts the exact value that
reaches it for both `--continuous-audit` passed and not-passed, catching the
`False`-vs-`None` distinction specifically (a test that only checked "some value gets
through" would have missed that). Two pre-existing tests
(`test_execute_prompt_runs_fully_unattended`, `test_execute_prompt_forwards_junit_out`)
needed their `fake_run` test doubles updated to accept the new kwarg — expected
fallout from adding a parameter to a function with existing mocked call sites, not a
sign of anything wrong.

### Manual review (Phase 0's other open item — never actually started until now)

Phase 0 named an explicit order: `runtime/hooks/*` → `agents/vision/*` →
`orchestrator/run_engine.py` + `capability_router.py` → `orchestrator/hermes_client.py`
+ `agents/planner/*` → everything else. In practice, Phases 1–5's deep-dive work already
hand-reviewed every file in the first four groups line by line while fixing what those
phases found (`interact.py`, `browser.py`, `capture.py`, `executor.py`, `dom_locator.py`,
`form_fuzzer.py`, `ui_audit_runner.py`, `run_engine.py`, `hermes_client.py`,
`spec_generator.py`, `llm_verifier.py`, `backend_router.py`). What was genuinely never
read until now: `orchestrator/capability_router.py` and the rest of `agents/planner/*`
(`diagnoser.py`, `cross_modal_diagnoser.py`, `explainer.py`, `parser.py`, `tool.py`).

**`capability_router.py`**: well-reasoned, already-documented security decisions
(egress allowlist, fail-open-when-unresolvable posture, Azure/GCP host resolution) —
no bug found in the file itself. But reading it end to end, alongside how it's called
from `run_engine.py`, surfaced a fourth instance of Phase 3's exact bug class:

**`run_engine.py`'s `CAPABILITY_CHECK` branch had the same unguarded-crash gap Phase 3
fixed in the vision path — verified by direct reproduction, not assumed.** Most
capability adapters guard their own transport errors already (checked `ApiAdapter`
directly: `except Exception` wraps its whole `httpx` call), but nothing at the
`call_tool("Capability.check", ...)` call site itself defended against an adapter that
doesn't — a bug in any single adapter (present or future) would crash the entire run
the same way an unguarded DOM snapshot did before Phase 3. Reproduced with a stub
adapter that raises a plain `Exception`: confirmed the crash at both the
`capability_router.route_capability()` level and the full `RunEngine.run_spec()` level
before the fix, confirmed graceful `RunStatus.ESCALATED` (not a crash) after it. Fixed
by wrapping that one call site and converting a caught failure into an escalated,
`unhealable`-flagged `CapabilityCheckResult` — reusing the loop's existing
`evidence.get("unhealable")` short-circuit rather than inventing new semantics, and
deliberately not attempting a cross-modal heal on a raw adapter crash (that diagnoser is
for schema-drift, not adapter bugs).

**The rest of `agents/planner/*`**: read fully, no bugs found. `diagnoser.py`'s
`HermesAgentDiagnoser` deliberately raises rather than fails soft on a transport/parse
error (documented reasoning: the self-healing loop's own retry/guardrail handling
already owns that, swallowing here would hide it one layer too early) — consistent with
its own stated design, not a gap. It also builds its own `HermesAgentClient()` directly
rather than going through Phase 4's `backend_router.py` — consistent with Phase 4's own
explicit scope decision (Planner-family backend selection stays untouched), not an
oversight. `cross_modal_diagnoser.py`, `explainer.py`, `parser.py`, `tool.py` are all
small, self-contained, and free of the exception-handling gap pattern this whole review
was looking for.

### Doc-vs-code verification

Before finalizing, grepped the actual current files for a marker of every phase's
claimed change (rather than trusting the write-up) — `execute_cmd.py`'s `console =
Console()`, `run_monitor.py`'s existence and both its call sites in `run_engine.py`,
`get_click_point_in_page`'s presence in all three Phase 2 files, the broad-except fix
markers from Phase 3, `backend_router.select_backend` actually being called from both
Phase 4 consumers, zero remaining `4141`/`hermes api-server` references outside
corrective context, and `continuous_audit` threading through every layer. One check
came back suspiciously empty at first (`backend_router.select_backend` string match in
`llm_verifier.py`/`run_monitor.py`) — turned out to be a grep-pattern mismatch on my
part (the code imports `select_backend` and calls it bare, not dotted), not a real gap;
re-checked directly and confirmed present. Everything else matched on the first pass.

### Final verification

- `ruff check .` — same categories as Phase 0's original sweep (E701/F401/E402/F541/
  F841), nothing new introduced; `F401` count actually dropped 8→7 (the `httpx` cleanup
  from Phase 4's llm_verifier.py refactor).
- Static AST audit: 0 errors, 30 warnings — the 2 new ones are both in
  `tests/test_cli.py`, my own new test's deliberate `except _StopHere: pass`
  sentinel-exception pattern for test isolation (not a real silent-swallow risk, just
  the generic heuristic flagging test-only control flow).
- `pytest tests/test_capability_egress_controls.py tests/test_cross_modal_healing.py
  tests/test_run_engine.py tests/test_cli.py` — all passed, no regressions from either
  the CAPABILITY_CHECK fix or the CLI flag work.
- Full suite re-run: **614 passed** (+1 net new real test), **27 failed, 5 errors** —
  same failure set as every prior phase's baseline, all Chromium-binary-missing, zero
  new failures anywhere in the wrap-up.

---

## Post-plan session — grounding fix, scroll-test DOM fix, OCR+link-check merge

Prompted by a live user report: (1) invented button names that don't exist on the
target page, (2) DOM detection "not working," (3) `--scroll-test` "not working," and
(4) a request that OCR and a real HTML/link fetch both run and both report during
scroll-test/ui-audit. Did a full line-by-line read of every file in `agents/planner/*`
(the fifth, most important one, `spec_generator.py`, hadn't been read end-to-end
before) before implementing anything.

### 1. Planner grounding (root cause of invented button names)

Confirmed at the line level: all four backends (`LocalHeuristicBackend`,
`LocalLLMBackend`, `CloudLLMBackend`, `HermesAgentBackend`) take only
`requirement_text: str` — `RequirementInput` (the actual input schema) had no field
for page content at all. Every `target_description` was a guess based purely on the
requirement doc's wording, with zero visibility into the real page — this is the
direct cause of names that don't exist on the site.

Fix, new module `agents/planner/page_grounding.py::snapshot_page_elements(url)`:
best-effort opens the target page and returns real, currently-visible interactive
element names — DOM-first (`dom_locator.snapshot_elements`, same as `executor.py`'s
existing path), OCR fallback (`ui_audit.audit_screenshot().interactive_elements`, same
as `ui_audit_runner.py`'s existing path) when no live DOM is available. Reuses both
existing detection engines rather than writing a third. Fails soft to `None` always —
confirmed directly in this no-display sandbox.

Wiring: `RequirementInput` gained an additive `page_context: list[str] | None = None`
field (fully backward compatible — every existing caller/test unaffected).
`spec_generator.py`'s new `_build_grounded_text()` builds an augmented prompt (original
text + a clearly-delimited "Elements actually found on the live target page" block)
*only* for what's sent to `backend.generate()` — the stored `requirement_text` itself
stays the raw, unmodified doc everywhere else (reports, audit). No `SpecBackend`
protocol/signature change, so zero risk to existing backend mocks/tests.
`execute_cmd.py::_run_requirement_text` calls `snapshot_page_elements()` right before
`generate_spec()` whenever a navigate URL is present in the requirement text (true for
essentially every real run — `--url`, or a "Given: navigate to X" precondition).

Also promoted `LocalHeuristicBackend._extract_navigate_url`'s regex loop to a
module-level `extract_navigate_url()` (same rationale `infer_test_id`'s own docstring
already gives for that pattern in this file) so `execute_cmd.py` can reuse the exact
same URL-matching logic rather than a second, driftable copy.

**Secondary finding from the same line-by-line read, not yet acted on**:
`LocalHeuristicBackend._extract_steps` only captures one action per line
(`.search()` + `break`/`continue`) — a requirement line describing two actions in one
sentence silently drops the second. Documented, not fixed this session (lower priority
than the grounding gap, and changing multi-action-per-line parsing risks behavior
drift in the heuristic backend's existing, tested output for every current spec).

### 2. `--scroll-test` DOM-based bottom detection

Root cause, confirmed by reading (no live display available to reproduce directly,
so this is a strong-confidence design fix, not an empirically-observed-then-fixed bug
like Phases 1-5): `orchestrator/autoscan.py` detected "reached the bottom" by hashing
**full-monitor screenshots** (`runtime/hooks/capture.py`'s mss capture, confirmed
whole-screen in Phase 2's investigation) and comparing scroll-to-scroll. Any unrelated
on-screen change (animation, video, cursor blink, OS clock) keeps hashes different
forever → burns the full `max_scrolls` budget every run. Conversely a repainting page
or a large sticky header can make hashes match too early → false "reached bottom"
after one scroll.

Fix: new `runtime/hooks/browser.py::get_scroll_position()` — reads
`window.scrollY`/`document.body.scrollHeight` directly from the live page's own DOM,
returning `(scroll_y, remaining_pixels)`. `autoscan.py`'s loop now checks this first
(deterministic, immune to unrelated on-screen noise) and only falls back to the old
screenshot-hash comparison when no live DOM exists at all. Verified with three
simulated scenarios (normal multi-scroll page, already-fits-in-viewport, genuine
infinite-scroll hitting the cap) plus the no-DOM fallback path — all four behave
correctly. `tests/test_autoscan.py` — 10/10 passed, no regressions.

### 3. OCR + real HTML/link fetch merged report

Found `UIAuditReport.link_check_result` already existed as a field, and
`run_exploration()` (`aura explore --check-links`) already populated it via
`agents/capability/link_checker.py::LinkCheckAdapter` — a real HTTP fetch + HTML parse
+ per-link status check, already correct and tested. But `run_ui_audit()` (what
`aura execute --ui-audit` actually calls) had no path to it at all — only the OCR
click-and-diff heuristic ran, which can tell "clicking produced no visible change" but
not "this link's target actually resolves." This is exactly the disconnect the request
described.

Fix: added the same `page_url`/`link_check_scope` wiring `run_exploration()` already
has to `run_ui_audit()` — reuses `LinkCheckAdapter` directly, no logic duplicated.
`execute_cmd.py`'s `--ui-audit` call site now passes the already-known `nav_url`
(same URL extracted for the grounding fix above) through, so both the OCR pass and the
real link check run against the same target and both surface in one merged report:
console output now prints a link-check summary (broken links, or "all N resolved")
right alongside the existing OCR-based nav/hero/footer/possibly-broken output. Fails
soft — no known URL, or the check itself failing, degrades cleanly to the pre-existing
OCR-only behavior (confirmed directly: a broken stub adapter logged its failure reason
and returned `None` rather than crashing the audit).

### Verification

- Direct functional tests for every new/changed function: `snapshot_page_elements`
  (fail-soft confirmed), `_build_grounded_text` (correct augmented-prompt construction
  and backward-compat no-grounding case), `extract_navigate_url` (reuse confirmed),
  `get_scroll_position`/`autoscan.py`'s new bottom-detection (4 simulated scenarios),
  `run_ui_audit`'s link-check wiring (success path + fail-soft path, both confirmed
  with stubs after catching and fixing a bug in my own first test stub, not the code).
- `ruff check` clean on all seven touched/new files.
  Static AST audit: 0 errors, 30 warnings (same as before this session — the two extra
  from the earlier wrap-up's own test, nothing new from this work).
- `pytest tests/test_ui_audit_runner.py tests/test_ui_audit.py tests/test_autoscan.py
  tests/test_cli.py tests/test_planner.py tests/test_schemas.py` — 97 passed, no
  regressions.
- Full suite re-run: **614 passed, 27 failed, 5 errors** — identical to the established
  baseline (all 27+5 are the pre-existing Chromium-binary-missing environment gap),
  zero new failures from this session's changes.

### Honest limitations of this session's work

- The scroll-test fix and the grounding fix are both design-level fixes derived from
  reading the code and simulating the relevant logic in isolation — **neither could be
  reproduced against a real live site in this sandbox** (no display, no Chromium
  binary). Confidence is high (the screenshot-hash approach is fundamentally the wrong
  instrument regardless of environment; the grounding gap was confirmed structurally at
  the code level, not inferred), but both need a real run against a real site to
  confirm they behave as intended end to end, the same way Phase 2's coordinate fix
  and Phase 5's Hermes fix needed your machine to confirm.
- Grounding currently only benefits the LLM-backed planner paths (Cloud/Local LLM/
  Hermes) — `LocalHeuristicBackend` receives the same augmented text but has no logic
  to act on it yet (its regex patterns just ignore the extra block). If you're running
  fully offline with the heuristic backend, this fix doesn't help yet; extending it
  would mean adding fuzzy-matching logic to `_extract_steps` against the element list,
  not yet built.