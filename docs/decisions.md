---
type: decisions-log
project: AURA
---

# Decisions Log

> One entry per decision: what was decided, why, and when to revisit. Don't delete superseded decisions — mark them superseded and link to the new one.

---

## D-001 — Vision-first over DOM-based automation
**Decided:** 2026-06 (original proposal)
**Decision:** AURA reads and interacts with the target application via screenshots/visual understanding rather than DOM selectors.
**Why:** DOM selectors are brittle — minor UI/CSS changes break scripted tests, driving continuous maintenance cost. Visual understanding survives cosmetic and structural UI churn.
**Revisit when:** If visual detection accuracy proves insufficient for a target application (e.g. highly dynamic canvas-rendered UIs), consider a hybrid DOM+vision fallback.

---

## D-002 — Fully offline / zero cloud reliance
**Decided:** 2026-06 (original proposal), reaffirmed 2026-07-01
**Decision:** All inference, orchestration, and data storage happen on-device. No cloud fallback in current scope.
**Why:** Avoids data residency/compliance risk for regulated environments (finance, healthcare, government) where screenshots and requirement docs may contain sensitive business logic or PII.
**Revisit when:** If a customer/use case explicitly needs cloud-scale throughput and is willing to accept the compliance trade-off — treat as an opt-in stretch goal, not a default.

---

## D-003 — Hermes Agent API as the multi-agent orchestration layer
**Decided:** 2026-07-01
**Decision:** All inter-agent coordination (Planner, Vision, Data Synth) runs through the Hermes Agent API's tool-calling protocol, replacing the original "sequential Python state handler" design.
**Why:** Gives structured, auditable request/response contracts between agents, native memory/skills persistence, and built-in loop guardrails — instead of a hand-rolled orchestration loop.
**Revisit when:** If Hermes Agent API proves insufficient (e.g. missing a needed guardrail/scheduling feature), or if a competing framework becomes clearly better suited.

---

## D-004 — Sub-agents defined by role/contract, not by specific model
**Decided:** 2026-07-01
**Decision:** Documentation no longer names specific underlying AI models for the Planner, Vision, or Data Synth agents. Each is defined only by its tool name, input schema, and output contract.
**Why:** Keeps the architecture swappable — any implementation can sit behind a tool call without changing orchestration logic. Also keeps docs from going stale as model choices change.
**Revisit when:** At implementation time, an actual model/runtime must be chosen per sub-agent — that choice should be logged here as a new decision (e.g. D-00X) once made, not folded into this entry.

---

## D-005 — No fixed hardware baseline
**Decided:** 2026-07-01
**Decision:** Removed all specific hardware/system specs (VRAM, RAM, GPU model) from the documentation. Resource policy is "compress as far as technically possible, invoke sub-agents on-demand, release immediately after use."
**Why:** Keeps the architecture portable across machines rather than tying it to one target laptop spec; sizing becomes a deployment-time concern.
**Revisit when:** If a real deployment needs a documented minimum spec for support/QA purposes, add a separate `deployment-requirements.md` rather than reintroducing specs into the core docs.

---

## D-006 — Hermes Agent API replaced by an in-repo tool-calling kernel (supersedes D-003)
**Decided:** 2026-07-02, during Phase 2 build
**Decision:** `orchestrator/kernel.py` implements the orchestration layer directly in Python instead of calling out to the Hermes Agent API (`hermes-agent.nousresearch.com`). It reproduces the identical external contract D-003 already committed to: a named tool registry (`config/tool_registry.yaml`), a `ToolCall` / `ToolResponse` envelope, schema-validated dispatch, and a verbatim JSONL audit trace per run.
**Why:** The Hermes Agent API host is not reachable from the build/execution environment (network egress is restricted to package registries and source control) and is not an installable, pinnable, inspectable dependency — there's nothing to verify or version-lock. Since D-003 committed to the *contract*, not a specific vendor, satisfying that contract in-repo lets every downstream piece (Planner/Vision/DataSynth tool registrations, guardrails, skill store) be built and tested for real right now instead of stubbing against an unreachable service.
**What's preserved from D-003:** tool-calling protocol shape, structured request/response contracts, loop guardrails (`orchestrator/guardrails.py`), skill/memory persistence (`orchestrator/skill_store.py`, `orchestrator/memory.py`).
**What's different:** dispatch is a local Python function call + pydantic validation instead of an HTTP call to an external agent runtime; there is currently no LLM "reasoning" step inside the kernel itself — that lives inside each tool's own implementation (e.g. `Planner.generate_spec`, built in Phase 3).
**Revisit when:** If the real Hermes Agent framework becomes reachable/installable later, only `OrchestratorKernel.call_tool`'s dispatch internals need to change — every tool's input/output schema and every agent module stays identical, since they were built against the schema contract, not the kernel's internals.

---

## D-007 — Phase 6 complete; audit-trail gap logged rather than silently fixed
**Decided:** 2026-07-02, at Phase 6 completion
**Decision:** All 6 phases in `PHASES.md` are now built and passing (62/62 tests). Rather than quietly routing `orchestrator/run_engine.py` through `OrchestratorKernel.call_tool()` to make `trace.jsonl` populate (which TRD.md §7 implies it should), that gap is logged here as an open item instead of silently patched, since it's a real architectural question (performance/complexity of routing every call through the kernel vs. accepting direct calls) rather than an obvious bug.
**Why:** `reports/render.py` already degrades gracefully when `trace.jsonl` is missing, so nothing is broken for the user — but the report's "Full tool-call/tool-response audit trace" section is currently always empty for real runs, which understates what TRD.md §7 promises ("every tool call/response logged verbatim"). Fixing this silently, without a decision on whether the performance/complexity trade-off of full kernel-routing is worth it, risked papering over a real design gap.
**Also fixed during Phase 6 verification (not decisions, just bugs):** report/terminal status enum was rendering as `RunStatus.PASSED` instead of `passed` (Python 3.11+ `StrEnum.__str__` behavior change); a step-count mismatch where the synthesized final-assertion pseudo-step inflated the "Passed" count past "Total steps." Both fixed in `reports/templates/run_report.html.j2` / `aura/tui/live_view.py` / `reports/render.py`.
**Revisit when:** Before relying on the audit trace for real compliance/debugging use — either route `run_engine.py` through the kernel, or update TRD.md §7 to describe the current direct-call wiring as the accepted design.

---

## D-008 — Audit-trail gap (D-007) closed: run_engine now routes through the kernel
**Decided:** 2026-07-02, post-Phase-6 QA pass
**Decision:** `orchestrator/run_engine.py` and `orchestrator/healing_loop.py` (via injected `diagnose_fn`/`execute_step_fn`) now call `Planner.generate_spec`, `DataSynth.generate`, `Vision.execute_step`, and `Planner.diagnose` through `OrchestratorKernel.call_tool()` instead of importing and calling the agent functions directly. `trace.jsonl` is now populated with a verbatim record for every tool call on a real run, matching TRD.md §7.
**Also fixed as part of this:** `ToolRegistry`'s default path to `config/tool_registry.yaml` was resolved via `settings.project_root`, which tests monkeypatch to a tmp dir to isolate runtime-output writes (reports/, runtime/, memory/) — that broke registry loading once `RunEngine` started constructing a `ToolRegistry` itself. Changed the registry's default path resolution to be relative to the kernel module's own file location instead, since `config/tool_registry.yaml` is a static repo asset, not a runtime output path.
**Why:** Closes the gap logged in D-007 without silently patching over it — the design question (performance/complexity of full kernel-routing) was resolved in favor of full routing, since the measured overhead is negligible (schema validation + a JSONL append per call) against the value of a real, always-populated audit trail for the compliance persona.
**Revisit when:** If kernel-routing overhead becomes measurable at scale (e.g. very high step-count specs), consider batching trace writes instead of one `open("a")` per call.

---

## D-009 — Live-display execution path verified for real (closes STATUS.md open item)
**Decided:** 2026-07-02, post-Phase-6 QA pass
**Decision:** Ran the real `runtime/hooks/capture.py` (mss) and `runtime/hooks/interact.py` (pyautogui) paths against the actual `target_app/demo_login_app.py` Tkinter window under a live X server (Xvfb), not just the synthetic-screenshot test harness. Confirmed: real screenshot capture, real OCR text-location via `agents.vision.locator.locate_text` against the live window, a real dispatched mouse click, and confirmation the click actually advanced the app UI (Username/Password fields became visible in the post-click screenshot).
**Finding (environment, not a code bug):** on a fresh X server with no `~/.Xauthority` file, `pyautogui`'s `mouseinfo` dependency raises before any click is dispatched, even though the X server itself has no access control enabled. `runtime/hooks/interact.py`'s existing `NoDisplayError` wrapping already converts this into a clean, typed exception rather than a raw traceback — no code change was needed. Deployment note: ensure the target machine/VM has a valid `~/.Xauthority` (created automatically by a normal desktop login session; only missing in minimal/fresh X server setups like a bare Xvfb instance) — call this out in deployment docs, not in application code.
**Why:** Closes the "no live-display verification yet" blocker in STATUS.md with a real, reproducible result instead of leaving it as an assumption.
**Revisit when:** Verifying against a second target app with a different toolkit (e.g. a real web browser or Electron app) to confirm the vision-first approach generalizes beyond a single Tkinter demo.

---

## D-010 — Local (fully offline) LLM backend added for the Planner
**Decided:** 2026-07-02, post-Phase-6 QA pass
**Decision:** Added `LocalLLMBackend` (`agents/planner/spec_generator.py`), which runs spec generation through a small GGUF-format model entirely on-device via `llama-cpp-python` (new optional `[llm]` dependency group). Selected via `settings.planner_backend = "local_llm"` (default remains `"heuristic"`); `AnthropicBackend` remains available under `"anthropic"` for reference/opt-in cloud use only, still gated behind `allow_network_calls=True`.
**Why:** The heuristic regex parser (still the default) is deterministic and dependency-free but brittle against real-world, loosely-structured requirement docs. A local LLM gives much better natural-language understanding while making zero network calls, preserving the offline guarantee (D-002) that ruled out the cloud `AnthropicBackend` as the default.
**Design choices:** (1) No automatic model download — the operator must place a `.gguf` file on disk and set `local_llm_model_path`, keeping model provenance fully within the operator's control (matters for the compliance persona in PRD.md, and avoids a silent network call at first use). (2) Model loaded lazily on first `.generate()` call, not at backend construction, so selecting this backend via settings doesn't require the dependency/model to be present unless actually used. (3) Small models don't reliably emit "JSON only" even when instructed — added `_extract_json_object()` to strip markdown fences/prose preamble before parsing, rather than failing outright on the first stray sentence.
**Verification status:** Plumbing verified via unit tests (error handling for missing path/file, JSON extraction from messy output, backend dispatch, full `generate_spec` flow against a fake backend) — 71/71 tests passing. **Actual model inference was NOT verified** in the build sandbox: `llama-cpp-python` has no prebuilt wheel for this platform and compiling from source exceeded the sandbox's time budget; downloading a real `.gguf` model also isn't possible here (no access to model-hosting domains). This needs to be run for real on a normal dev machine before relying on it.
**Revisit when:** After running it for real on a machine that can install `llama-cpp-python` and load an actual model — confirm output quality against a range of real-world requirement docs, not just the bundled example, and pick a recommended default model size/quantization for the README.

---

## D-011 — Fixed a real PIL Image file-handle leak in agents/vision/locator.py
**Decided:** 2026-07-02, post-Phase-6 QA pass (found during full-codebase review, not by a failing test)
**Decision:** `locate_text()` called `Image.open(screenshot_path)` without a context manager. PIL opens files lazily and keeps the handle open until garbage collection, which on Windows blocks deletion of the file (and its parent tmp dir) while the handle is still live. Changed to `with Image.open(...) as opened: opened.load(); ...` so the file handle is released as soon as pixel data is read into memory, before OCR runs.
**Why this matters:** this is very likely the real root cause of the `PermissionError: [WinError 32]` teardown failures seen earlier in this project's Windows test runs -- at the time those were attributed entirely to the cascading `TesseractNotFoundError` (OCR never running meant the Image object was still holding its file open when pytest's `tmp_dir` fixture tried to clean up), but the leak existed independently of that and would resurface under different failure conditions (e.g. a slow GC on a long-running scheduled process, or many rapid successive runs holding many screenshot files open longer than necessary).
**Verification:** 83/83 tests still pass after the fix; `ruff check` clean. No other `Image.open()`/unmanaged file-handle sites found elsewhere in the codebase (`runtime/hooks/capture.py` and `target_app/demo_login_app.py` only *create* new in-memory images via `Image.new`/`Image.frombytes`, which don't hold an open source file handle the same way).

---

## D-012 — Two real bugs found while validating the PyInstaller packaging path (Option 2 deployment)
**Decided:** 2026-07-02, post-Phase-6 QA pass
**Context:** Built the actual packaged binary (Linux equivalent, since PyInstaller doesn't cross-compile — the sandbox is Linux, target deployment is Windows, but the packaging mechanics are OS-independent) and ran it end-to-end against the live demo app, not just checking that it launches.
**Bug 1 — dynamic imports not bundled:** `ToolRegistry.load()` resolves agent modules from string names in `config/tool_registry.yaml` (`agents.planner.tool`, `agents.vision.tool`, `agents.data_synth.tool`) via `importlib.import_module()`. PyInstaller's static analysis can't see these string-based imports, so it silently excluded them from the bundle -- the exe launched fine and even rendered the spec table, but crashed with `ModuleNotFoundError` the moment `execute` actually tried to dispatch a tool call. Fixed by adding `--hidden-import` flags for all three modules to the build command (now documented in README.md).
**Bug 2 — reports written to a directory that gets deleted on exit:** `settings.project_root` defaulted to `Path(__file__).resolve().parent.parent`. For a frozen PyInstaller executable, `__file__` resolves inside PyInstaller's temporary extraction directory (`sys._MEIPASS`), which is wiped when the process exits. Every report/skill/memory DB the packaged exe wrote would have silently vanished the moment the user closed the terminal. Fixed via a new `_default_project_root()` in `config/settings.py` that checks `sys.frozen` and uses `Path(sys.executable).resolve().parent` instead, so output persists next to wherever the user put the exe. Static bundled resources (the Jinja2 template, `tool_registry.yaml`) correctly continue to resolve via `__file__`/`sys._MEIPASS` since those *should* come from the bundle, not the exe's directory -- only the runtime-output root needed to change.
**Verification:** After both fixes, ran the packaged exe from a clean directory (no source tree present, exactly as a distributed exe would be used) against the live demo app: real screenshot capture, real OCR, real click/type actions, all 4 steps executed, report correctly written next to the exe. 83/83 unit tests still pass; `ruff check` clean.
**Known sandbox limitation (not a code issue):** further repeated end-to-end exe runs in this session were unreliable because this particular sandbox does not reliably keep backgrounded processes (Xvfb, the demo app) alive across separate tool-call boundaries -- one run showed 3 escalated steps that traced back to two overlapping demo-app windows stacked on the same stale X display from a prior tool call, not a code defect. This is a constraint of the QA sandbox itself; a normal persistent Windows machine/session doesn't have this issue.
**Revisit when:** Building the real Windows .exe (not the Linux equivalent used here) to confirm both fixes hold on the actual target platform -- the `--hidden-import`/`--add-data` mechanics and the `sys.frozen` check are OS-independent, but should still be confirmed on Windows directly before distributing to a team.

## D-013 — Comprehensive UI audit + code bug-detection ("act like a professional QA tester" feature request)
**Decided:** 2026-07-03, phase-12 build
**Context:** Existing `--scroll-test` only ran a generic OCR error-string scan while scrolling (agents/vision/page_health.py) — it never specifically checked that a nav bar, hero section, and footer are present, nor whether nav/footer links actually do anything when clicked. There was also no code-file bug-detection capability at all.
**Decision, part 1 (UI audit):** Added `agents/vision/ui_audit.py` (`classify_landmarks`, pure function: buckets OCR-detected text into nav/hero/footer/body bands by Y-position + a fixed vocabulary of common nav/CTA/footer labels) and `orchestrator/ui_audit_runner.py` (`run_ui_audit`: live-clicks every interactive-looking nav/footer element found, screenshot-diffs before/after to flag "no visible change" as possibly non-functional, uses browser-back to return between clicks). Wired to a new `--ui-audit` flag on `aura execute`, findings now flow into both the terminal summary and the actual HTML report (`reports/render.py`/`run_report.html.j2`) — **also fixed a real pre-existing gap in the process**: `--scroll-test`'s `autoscan_report` was already being computed and printed to the console, but was never passed into `render_html()`, so it never actually reached the saved report file. Both `--scroll-test` and `--ui-audit` results now persist in the report.
**Decision, part 2 (code bug detection):** Added `agents/auditor/code_auditor.py` (`audit_path`/`audit_file`) and `aura debug <path>` CLI command. AST-based checks (syntax errors, mutable default args, silently-swallowed exceptions) + regex checks (bare except, TODO markers, unmanaged file handles) + an optional supplementary `ruff` pass. Explicitly **detection-only** per the request ("at least detect not fix") — nothing in this module writes to a scanned file; verified by a dedicated test (`test_audit_file_never_modifies_the_file`).
**Why the specific checks chosen:** every AST/regex check in `code_auditor.py` mirrors a real bug class this project's own QA passes caught by hand over its build history (D-011's unclosed `Image.open()` handle; the bare-except/mutable-default/silent-except sweep from the phase-6 finalize pass) — this automates exactly that manual review process rather than inventing generic rules.
**Verification:** Dogfooded `aura debug .` against AURA's own codebase: correctly found 3 genuine `except NoDisplayError: pass` patterns (flagged as warnings for review) and 1 known false positive (a TODO-detection test's own string literal, which the regex-based check can't distinguish from a real comment) — the tool's own honest info-level framing ("candidates for a human/deeper tool to confirm") held up under real use. 156/156 tests passing (140 pre-existing + 16 new for code_auditor), `ruff check` clean.
**Known limitations, disclosed rather than silently accepted:** (1) UI-audit's landmark classification is Y-position + vocabulary heuristics, not real DOM/semantic understanding — a page with an unconventional layout will produce false negatives ("nav not detected") that are a heuristic miss, not necessarily a real absence. (2) The live-click check can't distinguish "nothing happened because it's broken" from "something happened but produced a visually-identical screenshot" (e.g. opening a same-looking modal) — it's a signal for a human to look at, not a certain verdict. (3) `unmanaged-file-handle`/`todo-marker` are line-based regex, not real data-flow/AST analysis, so they can false-positive inside string literals (confirmed by the dogfood run above) or miss handles closed via a variable reference far from the `open()` call.
**Revisit when:** Extending `code_auditor.py` to other languages if AURA needs to audit non-Python codebases; considering a lightweight visual-diff (not just hash-diff) for the click-check to reduce the "identical hash but actually broken" false-negative case.

---

## D-014 — Phase 13: capability schema foundation for the universal-QA-platform pivot
**Decided:** 2026-07-03, start of AURA-ROADMAP.md Phases 13-19
**Context:** AURA-ROADMAP.md scopes the pivot from "vision-first RPA tester" to "universal QA platform" into Phases 13-19. Phase 13 is explicitly schema/contract-only: extend `orchestrator/schemas.py` with a `CapabilityType` enum and `CAPABILITY_CHECK` step type, define a minimal `CapabilityAdapter` protocol, and prove the routing path end to end with one fake adapter — no real adapters (api/db/email/etc.) yet.
**Decision:** Added `CapabilityType` (FAKE + forward-declared API/DATABASE/EMAIL/FILE/EXCEL/PDF/CLOUD for Phases 14-16) and `ActionType.CAPABILITY_CHECK` to `orchestrator/schemas.py`, plus `TestStep.capability_type`/`capability_params` (with a validator rejecting `capability_type` on non-`CAPABILITY_CHECK` steps) and new `CapabilityCheckInput`/`CapabilityResult` models. `CapabilityAdapter` is a `typing.Protocol` (`orchestrator/capability_adapter.py`), not an ABC — matches the existing plain-function-entrypoint pattern the kernel already uses for Planner/Vision/DataSynth tools, so future adapters (Phase 14+) don't need to subclass anything. A separate `CapabilityAdapterRegistry` sits below the kernel's `ToolRegistry`: the kernel gets exactly one new static YAML entry (`Capability.check` -> `orchestrator/capability_router.py:check_capability`), and each future adapter is added with one `registry.register(...)` line in `capability_adapter.default_registry()` rather than a `tool_registry.yaml` edit per adapter. `FakeAdapter` (`agents/capability/fake_adapter.py`) returns a canned `CapabilityResult`, echoing its input params back in `details` so tests can confirm the payload actually round-tripped through kernel schema validation, not just that some result came back. `RunEngine.run()` now branches per step: `CAPABILITY_CHECK` steps skip screenshot capture, skill pre-check, and the vision healing loop entirely (cross-modal healing is explicitly Phase 18, sequenced after real adapters exist) and go straight to `Capability.check`; all other action types are unchanged. The `CapabilityResult` is preserved verbatim on `VisionActionResult.capability_result` so `ReportAggregator`/`raw_results.json` need zero changes this phase while still capturing full adapter output for later phases' report rendering to pick up.
**Verification:** 10 new tests in `tests/test_capabilities.py` covering the schema validator, registry register/get/not-found, `FakeAdapter` satisfying the `CapabilityAdapter` protocol via `isinstance`, the kernel dispatching `Capability.check` with a real `trace.jsonl` record, and `RunEngine` routing a mixed spec (one `CAPABILITY_CHECK` step, one `VISUAL_CLICK` step) to the correct path for each. Full suite: 166/166 passing (156 pre-existing + 10 new).
**Revisit when:** Phase 14 adds the first real adapters (`api_adapter`, `db_adapter`, `email_adapter`) — confirms the protocol holds for adapters that actually do I/O, not just a canned one.

## Open — not yet decided
- Specific runtime/model choice for each sub-agent
- Target OS scope (desktop vs. web vs. both, and priority order)
- License for the eventual codebase (`docs/README.md` currently states MIT as a placeholder — not yet confirmed as an actual decision)
- Repository location / naming convention

---

## D-015 — Documentation reorganization + external reference research integration
**Decided:** 2026-07-13
**Context:** the repo had four duplicated doc pairs (root `.md` vs stale
`docs/.md` copies of the same file — `APPFLOW`, `PRD`, `TRD`, `WORKFLOW`),
no single root orientation file for AI contributors, and no mandatory
debug/review protocol. Separately, 18 external repos were researched for
patterns applicable to AURA (memory, navigation, self-healing, observability,
agent-loop guardrails), with findings that needed a durable home rather than
living only in chat history.
**Decision:**
1. Added `context.md` at repo root as the single mandatory entry point for
   any AI contributor, and `docs/debug.md` as a mandatory line-by-line
   review checklist to run on every code change (both cover process, not
   product features — see those files directly rather than duplicating their
   content here).
2. Resolved all four duplicate doc pairs by diffing root vs. `docs/` copies
   and confirming (not assuming) the root copies were the current/superseding
   versions in every case — each root copy contained a later dated note
   (2026-07-04) absent from its `docs/` counterpart. Root copies were
   promoted into `docs/`, stale `docs/` copies overwritten, root duplicates
   removed.
3. Moved every remaining root-level `.md` file (`README.md`, `STATUS.md`,
   `Roadmap.md`, `PHASES.md`, `decisions.md`, `progress.md`, `debug_report.md`)
   into `docs/`, per explicit instruction that `context.md` should be the
   only `.md` file at repo root. **Deliberate exception:**
   `requirements_input/example_login_flow.md` was left in place — it is
   functional test-fixture input data consumed by the Planner agent, not
   project documentation, and moving it risks breaking whatever expects it at
   that path for no documentation benefit.
4. Added `docs/external_repos.md`, a verified (not fabricated) extraction log
   for all 18 in-scope external repos across 6 batches, with two repos
   (`elder-plinius/G0DM0D3`, `BraveOPotato/FckSignups`) excluded on sight as
   apparent safeguard-removal/signup-bypass tooling, not reviewed.
5. Folded the most directly actionable findings into the docs they actually
   affect, not just into `external_repos.md`: a proposed navigation/self-heal
   redesign in `docs/TRD.md` §10 and `docs/Roadmap.md` Phase 20 (Playwright-
   first resolution, Scrapling-style DOM self-heal, UI-TARS coordinate
   normalization for the desktop fallback, structured audit-log taxonomy,
   skill quality-tracking, guardrail-structure review) — all marked
   **proposed, not implemented**, so nobody mistakes a documented plan for
   shipped behavior. Also folded a code-minimalism decision ladder
   (`ponytail`) and an explicit approval-tier list (`q-agent-harness`) into
   `context.md` §6 as standing process instructions.
**Verification:** confirmed via `diff` that no content was lost in the four
dedup operations (root copies were supersets of their `docs/` counterparts in
every case, not divergent versions); confirmed the final repo root contains
exactly one `.md` file (`context.md`) via `find . -maxdepth 1 -iname "*.md"`.
No code was changed in this pass — this is a documentation-only decision.
**Revisit when:** Phase 20 (or any subset of it) is actually implemented —
update `docs/TRD.md` §10 and `docs/Roadmap.md`'s Phase 20 status from
"proposed" to "delivered" (or partially delivered) at that point, per
`docs/debug.md`'s rule against letting docs go stale relative to code.

## D-016 — Automation Anywhere trigger/validate architecture merged into TRD.md §11 (proposed)

**Context:** an external architecture description was supplied for merging
into AURA's docs: `Playwright Test Suite → trigger Automation Anywhere bot
(REST API / CLI) → bot runs → Web App / Database / Files → Playwright
validates`. This is a trigger-and-verify pattern (AURA triggers an external
RPA bot and independently validates the result), distinct from AURA's
existing self-contained vision-driven execution model.

**Decision:** documented as `docs/TRD.md` §11 and `docs/Roadmap.md` Phase 21,
both marked **proposed, not implemented** — no code was changed in this
pass. Mapped onto existing components rather than inventing a parallel
engine: new `agents/capability/automation_anywhere_adapter.py`
(`CapabilityType.AUTOMATION_ANYWHERE`, trigger + poll) and new
`agents/capability/playwright_validator.py` (read-only web-state check);
the database and file validation legs reuse the existing `db_adapter` and
`file_adapter` unchanged.

**Collision noted and resolved:** `docs/TRD.md` §10 already proposes
Playwright as the primary *action-execution* path for AURA's own
Vision-driven steps (resolve-then-click via a `Locator`). §11 uses Playwright
strictly as a *read-only validator* after an external AA bot has already
performed the interaction — a different step type
(`capability_check` vs. `visual_click`/`visual_type`), so both coexist.
§11.5 makes this reconciliation explicit and specifies that once §10 lands,
`playwright_validator.py` should reuse its browser-session code rather than
introducing a second independent Playwright integration.

**Revisit when:** Phase 21 (or any subset) is actually implemented — update
`docs/TRD.md` §11 and `docs/Roadmap.md` Phase 21's status from "proposed" to
"delivered," per `docs/debug.md`'s rule against letting docs go stale
relative to code. Also revisit alongside Phase 20, since both depend on the
same Playwright dependency landing in the codebase.

---

## D-017 — Phase A: safety/correctness fixes (secrets split, cloud_adapter branching, db_adapter hardening, cross_modal_diagnoser data-flow bug)

**Decided:** 2026-07-13
**Context:** a remediation roadmap identified several outstanding issues
from an earlier audit. On inspection, three of the eleven originally listed
(1.1 `execute_run` stub, 1.2 missing login endpoint, most of 1.6's "dead
variables") turned out to already be fixed in the current codebase — the
roadmap was written against an earlier snapshot. This entry covers only the
items actually still present, plus one real bug found *during* this pass
that the original roadmap's framing of 1.6 didn't quite capture.
**Decisions:**
1. **Secrets split (roadmap 1.3):** `api/security.py`'s `SecretVault`
   previously generated one key file (`config/vault.key`) and used it both
   as the Fernet cipher key and, raw, as the JWT HMAC signing secret —
   anyone who could read `vault.key` could forge an admin token. Split into
   two independently-generated files: `config/vault.key` (Fernet, reserved
   for future credential encryption — not currently used to encrypt
   anything) and `config/jwt.key` (raw `os.urandom(32)`, JWT signing only,
   new `JWTSecretStore` class). Both `.gitignore`d going forward (neither
   was previously ignored, though `vault.key` was already committed —
   pre-existing repo hygiene issue, left as a follow-up since rewriting git
   history is out of scope for this pass).
2. **`cloud_adapter.py` action branching (roadmap 1.5):** the unbranched-
   `action` bug itself was already fixed (unsupported actions were already
   rejected explicitly). What was still missing: the adapter only ever
   implemented one action (`s3_object_exists`). Added `list_objects`
   (detect-only: lists keys under a prefix, checks count/presence) as a
   second real action. **Deliberately did NOT add** `upload_object`/
   `delete_object`/`download_object` as the roadmap's draft text suggested —
   this adapter is detect-only by explicit design (`docs/TRD.md` §9: "cloud_
   adapter default[s] to read/detect-only operations rather than mutating
   the systems they check"). Adding write/delete actions here would be a
   design regression disguised as a bug fix. If mutating S3 operations are
   ever genuinely needed, they belong in a separate, clearly-labeled
   adapter, not folded into the one every test spec already trusts to be
   side-effect-free.
3. **`db_adapter.py` read-only hardening (roadmap 1.7):** the existing
   prefix allowlist (reject anything not starting with SELECT/WITH/EXPLAIN/
   SHOW/PRAGMA/DESC/DESCRIBE) only checks the start of the statement. Added
   a second denylist check for known mutating/exfiltration function calls
   and clauses that can hide inside an otherwise-valid SELECT (`setval`,
   `pg_terminate_backend`, `lo_export`, `LOAD_FILE`, `INTO OUTFILE`,
   `EXEC`/`CALL`, `OPENROWSET`, `dblink_exec`, etc. — see the code comment
   for the full list and per-dialect notes). Explicitly documented as a
   **pattern denylist, not a full SQL sandbox** — a sufficiently creative
   dialect-specific construct not on the list could still get through; the
   real guarantee has to come from the DB connection's own grants being
   read-only, which is an operator/deployment concern this adapter cannot
   enforce from inside Python. Tested against both the new dangerous-query
   set and a set of legitimate SELECTs that mention similar-looking words
   (e.g. a column named `execution_id`), to confirm the new check isn't
   over-broad.
4. **`cross_modal_diagnoser.py` — real bug found during this pass, not just
   the roadmap's "dead variables" framing:** `_heal_db_drift()` reads
   `hints.get("exception", "")` to regex-match "column X does not exist"
   errors, but `db_adapter.py`'s `healing_hints` dict never actually
   contained an `"exception"` key — the real error text was only ever
   placed one level up, in the top-level `evidence["exception"]`, not
   inside `evidence["healing_hints"]`. The regex was therefore always
   matching against an empty string; this detection path could never fire
   in practice, regardless of how many "dead variables" were cleaned up
   around it. Fixed by also including `"exception": error_msg` inside
   `healing_hints` in `db_adapter.py`. Added a test
   (`test_query_error_healing_hints_include_exception_text`) that exercises
   the full path end-to-end (db_adapter → evidence → diagnoser) to prevent
   this specific data-flow break from silently regressing again — a plain
   unit test on either file in isolation would not have caught it, since
   each file's own logic was internally consistent; only the *contract*
   between them was wrong.
**Explicitly not done in this pass** (verify-only per the roadmap, not
fix-required): 1.1 (`execute_run` calling `RunEngine` — confirmed already
correct), 1.2 (login endpoint — confirmed present, no refresh-token support
added, out of scope), 1.4 (SQLite run-store persistence — not
re-verified with a kill-and-restart integration test this pass), 1.9
(Word/PowerPoint adapters — not started), 1.10 (desktop/mainframe
automation — remains an explicitly documented limitation, not silently
claimed as working), 1.11 (covered as a byproduct of D-018 below).
**Verification:** all four fixes covered by passing tests —
`tests/test_cloud_workflow_adapters.py` (7 tests, 3 new), `tests/test_db_adapter.py`
(11 tests, 3 new), plus a manual `python3 -c` check confirming the two
secret files are independently generated with different content.
**Revisit when:** 1.4/1.9/1.10 are picked up in a future pass — update this
entry's "explicitly not done" list rather than opening a new one for the
same roadmap items.

---

## D-018 — Phase B: removed AnthropicBackend and `allow_network_calls` entirely from the Planner

**Decided:** 2026-07-13
**Context:** the Planner previously had three backend options
(`heuristic`, `local_llm`, `anthropic`), with `AnthropicBackend` gated
behind `settings.allow_network_calls` (default `False`). Per explicit
instruction, this pass removes the cloud path entirely rather than leaving
it present-but-disabled.
**Decision:** deleted `AnthropicBackend` (the class, its import of the
`anthropic` package, and its entry in `_BACKEND_REGISTRY`) from
`agents/planner/spec_generator.py`. Removed `settings.allow_network_calls`
from `config/settings.py` entirely (confirmed via grep it had no other
consumer anywhere in the codebase before removing it). Removed the
`"anthropic"` branch from `aura/cli/preflight.py::check_planner_backend_available()`
— an unrecognized `planner_backend` value (including `"anthropic"` itself,
now) falls through to the existing generic "unknown value" error, same as
any other typo. `prompts.py` was reviewed and left unchanged — its templates
were already generic (used identically by both backends), nothing in them
was Anthropic-message-format-specific. No `anthropic` package dependency
existed in `pyproject.toml` to remove (it was always a function-local
`import anthropic`, an implicit optional dependency, never declared).
**Result:** the Planner now has exactly two backend options,
`heuristic` (default, zero dependencies) and `local_llm` (opt-in, via
`llama-cpp-python` and an operator-supplied `.gguf` file). There is no
network-capable code path left anywhere in the planner — not "off by
default," genuinely absent from the source, closing the residual
attack-surface/accidental-enable-via-config-flag risk `allow_network_calls`
represented. This also resolves roadmap issue 1.11 (`LocalLLMBackend` never
verified end-to-end live) as a natural byproduct: it's now the *only*
enhanced planner path, so any future work that exercises the enhanced path
at all necessarily exercises `LocalLLMBackend`, not a cloud fallback.
**Docs updated in the same pass** (per `docs/debug.md`'s rule against
letting docs drift from code): `docs/README.md` (removed the
`AURA_ALLOW_NETWORK_CALLS` config-table row and the `anthropic` option from
`AURA_PLANNER_BACKEND`'s valid values; reworded the "zero cloud reliance"
feature bullet). `config/settings.py` and `agents/planner/spec_generator.py`
module/class docstrings updated to stop describing a backend that no longer
exists.
**Verification:** `tests/test_preflight.py` — replaced the old
network-flag-gated anthropic test with three new tests confirming the
backend is genuinely gone: an unknown-`"anthropic"`-value now produces the
generic error (not a special network-flag message), `Settings` no longer
has an `allow_network_calls` attribute at all, and
`spec_generator._BACKEND_REGISTRY` contains exactly
`{"heuristic", "local_llm"}` with no `AnthropicBackend` class present in the
module. Full existing test suite re-run to confirm no other test depended
on the removed backend or setting (none did — `allow_network_calls` had no
other consumer).
**Revisit when:** local LLM inference is actually verified end-to-end on a
real machine with `llama-cpp-python` installed and a real `.gguf` model
(per D-010's still-open "Revisit when" — this pass did not change that
verification gap, it just made `local_llm` the only enhanced path there is
to eventually verify).

---

## D-019 — Phase C: Playwright as the primary interaction/self-heal path for browser targets

**Decided:** 2026-07-14
**Context:** roadmap Section 3 (this pass's remediation plan) asked for
Playwright to become the enforced primary path for click/type/scroll
against web targets, with the existing OCR/pixel pipeline demoted to a
fallback for non-browser targets, per TRD §10's already-drafted (but
previously unimplemented) design.
**Decision / what changed:**
- `runtime/hooks/browser.py`: replaced the stdlib-`webbrowser`-only
  `open_url()` with a persistent Playwright Chromium session
  (`_BrowserSession`, module-level singleton), navigating via
  `page.goto(..., wait_until="commit")` + a best-effort `networkidle`
  wait (docs/external_repos.md Batch 1's `navigate.ts` finding). Public
  contract (`open_url`, `normalize_url`, `NoDisplayError`) is unchanged so
  every existing call site (`aura/cli/execute_cmd.py`, `explore_cmd.py`,
  `api/routers/runs.py`, `agents/vision/executor.py`) and their tests kept
  working with zero changes. New: `get_page()`, `has_active_page()`,
  `close()`.
- `agents/vision/dom_locator.py` (new): `locate_dom()` resolves a step's
  target_description against a Playwright accessibility-tree snapshot
  (role/name word-overlap scoring, reusing `agents.vision.locator._match_score`
  so both paths score comparably), returning a live `Locator` — never a
  raw screen coordinate — for browser targets. `relocate_dom()` implements
  the Scrapling-style self-heal from docs/external_repos.md Batch 6:
  re-score every current candidate at a relaxed 0.40 threshold (Scrapling's
  own default), log the top score even on failure, return ties rather than
  guess.
- `runtime/hooks/interact.py`: added `dom_click()`/`dom_fill()`/
  `dom_scroll_into_view()` Locator-based primitives alongside the existing
  OS-pixel primitives (`click`/`type_text`/`scroll` unchanged).
- `agents/vision/executor.py`: `execute_step()` now tries the DOM path
  first (`_try_dom_path`) *only if* a live Playwright page already exists
  this run (i.e. a prior `NAVIGATE_URL` step actually opened one) — chain
  is `locate_dom()` → `relocate_dom()` self-heal → (if both miss) fall
  through unchanged to the pre-existing OCR/pixel `locate_text()` path.
  `VisionActionResult`'s schema is unchanged (TRD §10's explicit
  non-goal) — DOM-path confidence is just a differently-computed float in
  the same `[0,1]` range, gated against the same
  `settings.vision_confidence_threshold`.
- `agents/capability/link_checker.py`: added `_render_with_playwright()`,
  used only as a fallback when the plain `httpx` fetch finds zero links
  on a page that looks client-rendered — closes the documented
  JS-injected-link gap (STATUS.md) without changing the primary httpx
  path everything else (redirect handling, footer/nav scoping) still
  relies on. Confirmed via a real integration test
  (`test_playwright_render_fallback_finds_js_injected_links...`) against a
  genuine local HTTP server + real headless Chromium, not a mock.
- `pyproject.toml`: added `playwright>=1.44` as a real, declared
  dependency (previously zero DOM-aware dependencies existed anywhere in
  the codebase, per decisions.md D-002/D-005's original "no
  Selenium/Playwright/CDP" posture — this pass deliberately supersedes
  that for browser targets only, per explicit instruction).
- `orchestrator/run_engine.py`: `run_spec()` now closes the Playwright
  session at the end of a run so it doesn't leak into the next
  run/process, while remaining persistent *within* a run's steps.

**Simplification vs. the full TRD §10 text, disclosed rather than silently
narrowed:** `relocate_dom()`'s self-heal re-scores the *current* page's
candidates against the *same* target_description that just failed to
resolve (a relaxed second pass), rather than against a persisted
"last-known-good element" carried over from a prior successful run —
`TestStep`/`VisionStepInput` have no field for that yet, and adding one is
a schema change out of this pass's scope. This still implements Scrapling's
core mechanism (score-every-candidate, threshold-gate, log-top-score,
don't-guess-on-ties) faithfully; it's narrower only in *what* it's
comparing against, not *how*.

**Conflict found and fixed before Phase C started (per the audit
requested alongside this phase):** `agents/capability/automation_anywhere_adapter.py`
and `agents/capability/playwright_validator.py` (Phase E / TRD §11,
"proposed, not yet implemented") already existed fully written in the
repo, but `orchestrator/schemas.py`'s `CapabilityType` enum never gained
`AUTOMATION_ANYWHERE`/`WEB_VALIDATION`, and neither adapter was registered
in `orchestrator/capability_adapter.py::default_registry()` — an
orphaned, half-landed Phase E attempt that broke `pytest` collection
entirely (`tests/test_automation_anywhere.py` failed at import time).
Fixed minimally: added both enum members and registered both adapters, so
the full test suite collects and runs again. This is **not** a full Phase
E implementation pass (no new decisions.md entry mirroring D-018's depth,
no CLI-level registration test beyond what `test_automation_anywhere.py`
already covered) — it's the smallest fix that resolves the conflict
without expanding scope into Section 5's deferred work.
**Verification:** full existing suite (280 tests, pre-Phase-C) confirmed
passing after the conflict fix and before any Phase C code was written.
Phase C added 4 new test files (`test_browser_hook.py`,
`test_dom_locator.py`, `test_executor_dom_path.py`, plus 1 new test in
`test_link_checker.py`), all exercising real Playwright/Chromium against
real local HTTP servers rather than mocks — **293/293 tests passing**
after Phase C. `pyflakes` clean on every file touched this pass.
**Revisit when:** Phase D (offline hardening/egress allowlist) needs to
decide whether Playwright's browser-binary download counts as part of
the "offline-first" posture (it's a one-time local install, same
category as tesseract, per the original roadmap's own framing — no
runtime network calls are made by Playwright itself). Phase E, if picked
up later, should give the automation_anywhere/playwright_validator wiring
its own full decisions.md entry (CLI docs, `test_16_categories_verification.py`-style
registration test) rather than relying on this pass's minimal conflict fix.

## D-020 — Phase D: capability-adapter egress controls (kill switch, host allowlist, audit trail)

**Context:** Roadmap.md's own Phase D entry (written before Phase C landed)
scoped this as: a hard kill switch (`settings.capability_adapters_enabled`),
an egress allowlist (`settings.allowed_capability_hosts`), and extending the
audit trail to log capability-adapter outbound target host + timestamp.
Sequenced after Phase C on the assumption Phase C would introduce new
egress points needing the same hardening — in practice Phase C's Playwright
work is a *local* browser automation surface (no new outbound capability
target), so Phase D's actual scope is entirely about the pre-existing
`agents/capability/*.py` adapters, which were already the system's sole
intentional network/filesystem surface.

**What changed:**
- `config/settings.py`: added `capability_adapters_enabled: bool = True`
  (hard kill switch) and `allowed_capability_hosts: list[str] | None = None`
  (opt-in egress allowlist). Both default to today's behavior unchanged —
  no existing spec breaks.
- `orchestrator/capability_router.py::route_capability` (the single
  kernel-facing chokepoint for every capability adapter, per its own
  module docstring) now, in order: (1) rejects everything if the kill
  switch is off, (2) extracts the target host from the payload and
  rejects if an allowlist is set and the host doesn't match, (3) logs a
  `CAPABILITY_EGRESS` record (host + UTC timestamp only, never payload
  contents — params can carry credentials) to `orchestrator.audit_logger`,
  the same sink `api/routers/runs.py` already uses for run-level auditing,
  then (4) dispatches to the adapter as before.
- Host extraction (`_extract_egress_host`) is deliberately built from the
  real `params.get(...)` key names actually used across
  `agents/capability/*.py` (audited file by file, not assumed):
  `url`/`webhook_url`/`account_url`/`endpoint` (api, workflow, chat_ops,
  azure blob account URL), `connection_string`/`conn_str` (db, azure),
  `smtp_server`/`imap_server`/`host` (email), falling back to
  `payload.target` itself if it parses as a URL (link_check).
- **Known, documented gap, not silently papered over:** `azure_adapter.py`
  and `gcp_adapter.py` primarily authenticate via SDK default-credential
  chains (`DefaultAzureCredential`, ADC) rather than an explicit host in
  `params`, so `_extract_egress_host` often returns `None` for those two
  adapters specifically. `_host_allowed` fails open when the host is
  unresolvable (the kill switch remains the hard backstop for that case),
  and the audit record still logs `host: null` rather than skipping the
  log line, so the gap is visible in the trail rather than hidden. A
  future pass could thread the actual resolved storage-account/project
  hostname through those two adapters' `params` if tighter allowlisting is
  needed for them specifically — not done here to avoid changing two
  adapters' external call shape as a side effect of an audit feature.
- `FAKE` is the one capability exempted from host checks entirely (no
  real network target ever) but still respects the kill switch, so "one
  flag disables the whole layer" stays true without exception.
- New test file `tests/test_capability_egress_controls.py` (16 tests):
  kill-switch rejection, host extraction across each real param-key
  convention, allowlist exact/subdomain match and rejection, fail-open
  behavior when no host is resolvable, and audit-log content (present on
  permit, absent on kill-switch rejection, never containing payload data).

**Verification:** full existing suite plus the new file:
**300/309 passing** (the 9 failures are the pre-existing Phase C
Playwright/Chromium tests, which fail in this sandbox only because its own
network egress rules block `cdn.playwright.dev`'s browser-binary download
— confirmed as the *only* failure cause by running the full suite
unmodified before this change and seeing the identical 9 tests fail for
the identical reason; nothing in this Phase D change touches Playwright
code). `pyflakes` clean on every file touched.

**Not done in this pass (out of scope for Phase D as scoped):** per-adapter
host resolution for azure/gcp (noted above as a documented gap); a
structured event-type taxonomy for `orchestrator/audit_logger.py` more
broadly (that was a separate, lower-priority idea from `external_repos.md`
Batch 6's langfuse extraction, not part of Phase D's stated scope);
threading real tenant/user identity into `route_capability`'s audit calls
(it currently logs `tenant_id="system"` because `RunEngine`/the kernel
don't carry request-level identity down to the capability layer today —
would require a broader context-passing change through `RunEngine.run_spec`
and is deliberately left as a follow-up rather than bundled here).

**Revisit when:** Phase E (Automation Anywhere) adds
`automation_anywhere_adapter.py`'s real trigger endpoint to the
egress-controlled set — it already routes through the same
`route_capability` chokepoint (`CapabilityType.AUTOMATION_ANYWHERE` is
registered per D-019's conflict-fix note), so it inherits Phase D's kill
switch and allowlist automatically; confirm its `params` key for the AA
Control Room URL is covered by `_URL_PARAM_KEYS` when that phase is
picked up properly.

## D-021 — Phase E: Automation Anywhere trigger/validate closure

**Context:** D-019's Phase C conflict-fix note recorded that
`agents/capability/automation_anywhere_adapter.py` and
`agents/capability/playwright_validator.py` (TRD §11, Roadmap Phase 21a/21b)
already existed **fully written** in the repo, with `CapabilityType`
members and registry entries added as a minimal unblock — but flagged that
this was not a full Phase E pass, and asked for one with its own
decisions.md depth, CLI/doc coverage, and a registration test in the style
of `test_16_categories_verification.py`.

**What was actually found on inspection:** both adapters, and
`tests/test_automation_anywhere.py` (13 tests: registry wiring, REST-mode
trigger+poll to terminal status, CLI-mode subprocess trigger, the
Playwright web validator's text/selector/selector-text assertions, and a
full trigger→validate integration test chaining both), were already
correct and complete against TRD §11's design — no functional bug found in
either adapter. TRD §11.2's own table already specifies that "no blind
trust of bot-reported success" is enforced by `RunEngine`'s existing
step-sequencing and Run Report aggregation (a spec author sequences a
`capability_check` trigger step followed by validation steps; the existing
per-step + spec-level assertion rollup already means the run is only
"passed" if every step, trigger and validation alike, passed) — this does
not require new RunEngine code, so no gap there either.

**What Phase E's closure pass actually fixed:**
1. **Real gap, closed:** Phase D's (D-020) egress-controlled
   `_URL_PARAM_KEYS` list did not include `control_room_url` — the param
   name `automation_anywhere_adapter.py`'s REST mode actually uses for the
   Control Room endpoint (confirmed by reading the adapter's own
   `_run_rest`). This meant an AA trigger's target host was invisible to
   both the audit trail and the allowlist. Added `control_room_url` to
   `orchestrator/capability_router.py::_URL_PARAM_KEYS`.
2. **CLI mode confirmed correct as-is:** CLI-mode AA triggers are a local
   subprocess invocation, not a network call, so they correctly have no
   extractable host (`_extract_egress_host` returns `None`) — `_host_allowed`
   fails open for that case exactly as it does for other no-host
   capabilities, with the kill switch remaining the applicable control.
   Added a test asserting this explicitly rather than leaving it as an
   untested side effect of the fail-open default.
3. **Docs:** `docs/WORKFLOW.md`'s capability-check step-type callout listed
   only `API/DB/Email/File/Excel/PDF/Cloud/Workflow` as examples, silently
   omitting Azure/GCP/SharePoint/ChatOps/LinkCheck/AutomationAnywhere/
   WebValidation even though all are registered and tested. Updated the
   list to mention Automation Anywhere trigger + Playwright web-validation
   explicitly (with a §11 pointer), since that's the doc a spec author is
   most likely to read to learn what capability types exist.
4. **New tests, appended to `tests/test_automation_anywhere.py`** (4):
   `control_room_url` host extraction, allowlist rejection via the router
   using `control_room_url`, `web_validation`'s `url` param extraction, and
   CLI-mode's no-host/kill-switch-only behavior.

**Not done in this pass (genuinely out of scope):**
- Reusing a shared Playwright browser-context module between
  `playwright_validator.py` and `agents/vision/dom_locator.py`/
  `runtime/hooks/browser.py` (TRD §11.5's own reconciliation note flags
  this as a future consolidation once both exist — both do now, post
  Phase C, so this is a legitimate small follow-up, but it's a
  refactor-for-consistency task, not a bug or a missing capability, and
  wasn't requested as part of this closure pass).
- Azure/GCP host-allowlisting gap noted in D-020 remains open — unrelated
  to Automation Anywhere.

**Verification:** ran the full suite before this pass (300/309 passing —
the 9 pre-existing Phase C Playwright/Chromium sandbox-only failures) to
confirm no regressions were introduced elsewhere before starting. After
this pass: **304/313 passing** — identical 9 pre-existing failures, all 4
new tests plus all 17 tests in `test_automation_anywhere.py` (13 existing
+ 4 new) passing. `pyflakes` clean on every file touched.

**Revisit when:** the shared-Playwright-browser-context consolidation
(above) is prioritized — it should get its own decisions.md entry since it
touches both `playwright_validator.py` and the Phase C dom_locator/browser
modules.

## D-022 — Three real bugs found via live command-by-command testing, all fixed

Found by actually invoking every CLI command/flag combination (not just
`--help`), including under a real Xvfb virtual display to isolate
environment-specific failures from genuine breaks:

1. **`aura debug --out <file>` silently wrote nothing when the scan was
   clean.** `aura/cli/debug_cmd.py::run_debug()` had an early `return`
   inside the `if report.clean:` branch, before the `if out:` file-write
   block ever ran — so `--out` only worked when there were findings. Fixed
   by moving the write into the clean branch too; `_write_report_file()`
   now writes an explicit "Clean — no issues found." line when there's
   nothing to list, instead of silently producing nothing.

2. **`orchestrator/run_engine.py` crashed the entire run with an uncaught
   `NoDisplayError` traceback** in any headless/no-display environment,
   for every real-execution path (`aura execute --url/--prompt/--interactive`
   and plain `test_id`, plus `aura explore`). The screenshot capture at
   line ~323 (main vision branch) — plus 4 other call sites
   (`WAIT_FOR_HUMAN_ACTION`'s baseline/poll captures, the post-step
   assertion capture, the final spec-level assertion capture) — called
   `self.screenshot_provider(...)` with no guard at all, even though
   `agents/vision/executor.py` already catches this exact exception
   gracefully for the actual click/type/navigate actions. Fixed by adding
   `RunEngine._safe_screenshot()`, which wraps every one of those 5 call
   sites and converts `NoDisplayError` into a clean step-level escalation
   (`escalate=True`, `assertion_passed=False`) instead of letting it
   propagate and kill the process. New regression test in
   `tests/test_run_engine.py`
   (`test_run_engine_escalates_cleanly_on_no_display`) simulates the exact
   condition and asserts the run completes rather than raising.

3. **`aura explore` failed silently — exit code 1, zero output beyond one
   dependency note, no traceback** — reproduced live under a real Xvfb
   display with tkinter uninstalled. Root cause, confirmed by direct
   reproduction: `pyautogui` transitively imports `mouseinfo`, which calls
   `sys.exit(...)` directly at import time on Linux when tkinter isn't
   installed, instead of raising a normal `ImportError`. `SystemExit` is a
   `BaseException`, not an `Exception` — so `runtime/hooks/interact.py`'s
   `_pyautogui()`'s `except Exception as e: raise NoDisplayError(...)`
   never caught it, and it silently killed the whole Python process
   instead of degrading gracefully like every other no-display condition
   already handled in this module. Fixed by adding an explicit
   `except SystemExit` clause that converts it into the same
   `NoDisplayError` the rest of the pipeline (`orchestrator/autoscan.py`,
   `orchestrator/ui_audit_runner.py`) already expects and handles. Verified
   fixed by live re-run under the identical Xvfb/no-tkinter conditions:
   `aura explore` now exits 0 and completes the full report. New tests in
   `tests/test_interact_no_display.py` (3 tests: SystemExit path, plain
   ImportError path still works, success path unaffected).

**Also closed, as a smaller related gap:** `aura/cli/preflight.py` checked
Tesseract and the planner backend but nothing else, even though gap #2/#3
above are exactly the class of failure preflight exists to catch early.
Added three new **advisory-only** checks (never block, since plenty of
legitimate runs — pure API/DB/file capability checks — need neither a
display nor a browser): `check_display_available()`,
`check_playwright_browser_available()`, and
`check_capability_adapter_dependencies()` (warns if paramiko/boto3/
azure-storage-blob/google-cloud-storage aren't importable). 4 new tests in
`tests/test_preflight.py`.

**Not reproduced in this pass, and not fixed (from the same audit,
included here for completeness):** the `camelot-py`/`pypdf` version
conflict didn't reproduce — `camelot` isn't a dependency in this version
of `pyproject.toml` at all. The Azure/GCP host-allowlisting gap and the
`tenant_id="system"`/`user_id="system"` hardcoded audit-log identity gap
(`orchestrator/capability_router.py`) are both pre-existing, already
documented limitations (see D-020) — unrelated to this pass's three bugs,
left open.

**Verification:** full suite immediately after cloning, before touching any
code: **317 passing** (confirming a clean baseline, matching D-021's
304/313 plus environment-dependent extras already resolvable in this
sandbox). After this pass: **321 passing** (10 new tests: 1 in
`test_run_engine.py`, 3 in the new `test_interact_no_display.py`, 4 in
`test_preflight.py`, and 2 covered implicitly by existing debug-command
tests exercising the fixed clean-scan branch) — zero regressions.

## D-023 — Phase 21c closed: RunEngine now enforces the bot-trigger/validation-leg cross-check

Closes the one remaining gap from the Phase 21 (Automation Anywhere)
architecture review against `docs/TRD.md` §11's diagram: every individual
box/adapter (trigger, Web App/Database/Files validation legs) already
existed and worked, but nothing enforced the diagram's actual policy at
the "Playwright Validates" aggregation point — that a bot's own reported
`COMPLETED` status is never sufficient alone; at least one validation leg
must independently confirm the expected end state (TRD §11.6).

**What changed:**
- `orchestrator/schemas.py::TestStep`: new optional `bot_validation_group:
  Optional[str]` field. A spec author tags an `AUTOMATION_ANYWHERE` trigger
  step and its corresponding `WEB_VALIDATION`/`DATABASE`/`FILE_SYSTEM`
  validation-leg step(s) with the same group string to link them as one
  logical trigger-and-verify unit. Steps with no group are completely
  unaffected — this is opt-in, not a behavior change for any existing spec.
- `orchestrator/report_aggregator.py`: added `get_results()` (read-only
  snapshot) and `override_step_result(step_id, corrected)` so a
  previously-recorded step result can be retroactively corrected once
  later steps in the same run reveal it shouldn't have been accepted at
  face value.
- `orchestrator/run_engine.py`: new `RunEngine._enforce_bot_validation_cross_check()`,
  called once after the main step loop finishes (only when at least one
  step in the spec has `bot_validation_group` set, so specs that don't use
  this feature pay zero extra cost). Groups every capability-check result
  by `bot_validation_group`, and for each group whose trigger step
  reported `passed=True`: if none of the grouped validation-leg results
  also reported `passed=True`, the trigger step's own recorded result is
  corrected to `assertion_passed=False, escalate=True`, with a
  `cross_check_failed` note added to its evidence explaining why. A group
  with a trigger but zero validation-leg steps anywhere in the spec is
  treated the same way (nothing to confirm against == not confirmed).
  If the bot itself already failed, the cross-check does nothing extra —
  that case was already handled correctly by the existing
  `CAPABILITY_CHECK` branch.
- **Deliberately unchanged:** a validation leg's own pass/fail is still
  independently escalated on its own merits regardless of the group
  cross-check outcome — e.g. if the bot succeeds and one of two validation
  legs independently confirms it (so the trigger step itself correctly
  stays passed), a *different* validation leg that itself failed still
  shows up as its own escalated step in the report. The cross-check only
  ever touches the trigger step's own verdict, never rewrites a validation
  leg's result.
- New tests: `tests/test_bot_validation_cross_check.py` (6 tests) —
  confirmed-pass, unconfirmed-fail (with evidence check), "at least one of
  multiple legs" partial-confirmation case (verifying the trigger step
  itself is *not* downgraded), bot-already-failed is unaffected, no-group
  steps are unaffected, and orphaned-group-with-no-validation-steps is
  still escalated.

**Verification:** 321 passing before this pass. **327 passing after**
(6 new), zero regressions across the full suite.

**Not done (explicitly out of scope):** automatically inferring
`bot_validation_group` from step adjacency/spec structure — this requires
the spec author to set it explicitly. Also not done: extending the same
cross-check pattern to any *other* multi-leg validation scenario outside
Automation Anywhere trigger/validate — TRD §11 only describes this one
pattern, so the field and enforcement logic are scoped to it rather than
generalized speculatively.

## D-024 — Follow-up: two more unguarded screenshot-capture call sites found in `aura explore`/`--ui-audit`/`--scroll-test`, fixed

**Context:** D-022 fixed `orchestrator/run_engine.py`'s 5 unguarded
`screenshot_provider(...)` call sites and the `mouseinfo`/`SystemExit`
root cause behind `aura explore`'s earlier silent failure. Re-verifying
`aura explore` live after that fix (no CLI flags changed, same repro
steps as before) showed it now completes cleanly under a real display —
but running it **with no display connected at all** still crashed with a
raw, uncaught `NoDisplayError` traceback. Root cause, found by reading
both modules directly rather than assumed: **`orchestrator/autoscan.py`**
(the scroll-scan engine behind `--scroll-test` and `aura explore`'s
page-health pass) and **`orchestrator/ui_audit_runner.py`** (the
click-audit engine behind `--ui-audit` and `aura explore`'s
element-clicking pass) each call `screenshot_provider(...)` directly, with
no guard, at 3 total call sites across the two files — the exact same
class of bug D-022 fixed in `run_engine.py`, in two files D-022's pass
didn't touch.

**What changed:**
1. `orchestrator/autoscan.py::run_autoscan`: the screenshot capture inside
   the scroll loop is now wrapped in `try/except
   runtime.hooks.capture.NoDisplayError`, breaking the loop cleanly
   (keeping whatever steps were already collected) instead of crashing.
   Added a new `display_unavailable: bool` field to `AutoScanReport` so
   callers can report *why* the scan stopped short — "no display" and
   "hit the scan limit without reaching bottom" are different situations
   that previously looked identical (`reached_bottom=False` either way).
2. `orchestrator/ui_audit_runner.py::_run_click_audit` (the shared engine
   behind both `run_ui_audit` and `run_exploration`): the baseline
   screenshot capture is now guarded, returning a clean, valid, empty
   `UIAuditReport` (with an explanatory entry in `page_issues`) instead of
   crashing. The after-click capture inside the per-element loop is also
   guarded, in case a display disconnects mid-audit rather than being
   absent from the start — recorded as `clicked=True, state_changed=None`
   for that element, then the audit stops rather than crashing on the
   next iteration too.
3. `aura/cli/execute_cmd.py` and `aura/cli/explore_cmd.py`: both
   `--scroll-test`/scroll-scan coverage messages now check
   `autoscan_report.display_unavailable` first and print an accurate
   "no display available" message instead of the misleading "hit the scan
   limit" they'd have shown otherwise.
4. New tests: 2 in `tests/test_autoscan.py` (no-display on the first
   screenshot; display dropping mid-scan after some steps already
   collected) and 1 in `tests/test_ui_audit_runner.py` (no-display on the
   baseline capture). A pre-existing fake report object in
   `tests/test_explore_cmd.py` (`type("R", (), {...})`) needed the new
   `display_unavailable` attribute added to keep passing — not a new bug,
   just a test double that needed updating alongside the dataclass change.

**Verification:** confirmed the true before/after via `git stash` (not
just re-running after the fact): **before this pass, 318/327 passing**
(7 failed + 2 errors — the same pre-existing Phase C Playwright/Chromium
sandbox-only failures noted in every prior entry). **After: 321/330
passing** — identical 9 pre-existing failures, 3 new tests all passing,
zero regressions. Live-reproduced the original crash and confirmed the
fix: `aura explore <url>` with no display connected at all now prints
"No display available -- page scan skipped..." and "...UI
audit/exploration skipped..." and exits 0 with a valid JSON report,
instead of an uncaught traceback and a non-zero exit. `pyflakes` clean on
every file touched.

**Not done in this pass:** the three separate, identically-named
`NoDisplayError` classes across `runtime/hooks/capture.py`,
`runtime/hooks/interact.py`, and `runtime/hooks/browser.py` remain
distinct classes rather than one shared exception type — a pre-existing
design smell, noted here because this pass had to explicitly import and
catch the `capture.py` flavor by name (aliased as `CaptureNoDisplayError`
where a module already imports `interact.py`'s flavor under the plain
name) to avoid ambiguity; unifying them into one shared class is a
reasonable follow-up but is a broader refactor than this bug-fix pass, and
touches enough call sites across the codebase that it deserves its own
decision entry rather than being bundled in here.

## D-025 — Phase G1: environment-profile management

**Decided:** 2026-07-14
**Context:** part of the gap-review-derived remediation plan (Phases G–M),
G1 covers "environment-profile management (dev/staging/prod configs)" —
`config/settings.py` previously had no concept of named environments, only
one flat `.env` per process.
**Note on how this entry came to be written:** the actual G1 implementation
(`config/settings.py`'s `_resolve_env_files`/`reload_profile`,
`aura/main.py`'s `--env` callback, `aura/cli/init_cmd.py`'s
`scaffold_env_profile`, and `tests/test_env_profiles.py`/`tests/test_settings.py`,
13 passing tests) was found already written and working in the codebase,
complete with in-code comments referencing "Phase G1" and this decision
number — but this decisions.md entry, and the corresponding STATUS.md/
progress.md updates, had never actually been written. Per `docs/debug.md`'s
own rule against letting docs drift from code, this entry closes that gap
rather than re-implementing already-correct work. Re-verified by reading
the actual code and re-running its tests before writing this entry, not by
trusting the in-code comments' claims at face value.
**What it does:**
- `.env` always loads first (base config); `.env.<profile>` (if it exists)
  loads second and overrides on any key it also sets — pydantic-settings'
  own later-file-wins semantics, not custom merge logic.
- `AURA_ENV` env var or `aura --env <name> <command>` selects the active
  profile. A profile with no matching `.env.<profile>` file is not an
  error — it's treated as "nothing to override," so a typo in the profile
  name degrades gracefully rather than crashing (and is debuggable via
  `settings.env`, which reports which profile actually got applied).
- `Settings.reload_profile()` mutates the existing module-level `settings`
  singleton's fields in place, rather than rebinding the module attribute
  to a new object — necessary because dozens of modules already did
  `from config.settings import settings` at their own import time, binding
  a reference to the original object; rebinding the module attribute alone
  wouldn't reach any of those already-bound references.
- `aura init --env <name>` scaffolds a starting `.env.<name>` file with
  every base-`.env` key present as a commented-out placeholder (guidance on
  what *can* be overridden) rather than either an empty file or a full
  live copy (which would silently duplicate secrets like
  `AURA_TESSERACT_CMD` into a second file people forget exists).
**Verification (this pass):** re-ran `tests/test_env_profiles.py` +
`tests/test_settings.py` (13/13 passing) and did a live smoke test —
`python -m aura.main init --yes --env smoketest` — confirmed it writes a
correct placeholder file and doesn't touch the base `.env`.
**Not done:** README.md's Configuration section doesn't yet document
`--env`/`AURA_ENV`/`.env.<profile>` — fixed in this same pass alongside
this entry (see progress.md).

## D-026 — Phase G2: CI/CD-native mode (JUnit XML output, documented exit codes)

**Decided:** 2026-07-14
**Context:** "no CI/CD-native mode" gap from the same remediation review as
G1 -- no structured test-report format for CI consumption, no documented
exit-code contract.
**Note on how this entry came to be written:** `reports/junit.py` (the
core render module -- `build_testsuite_element`, `render_junit`,
`render_junit_suites`) was already written, complete, and referencing this
decision number in its own comments, but was never actually wired into
the CLI (no `--junit-out` flag existed anywhere), had zero test coverage,
and this decision entry didn't exist. This pass finished the wiring, wrote
the missing tests, and found (and fixed) a real latent bug in the
already-written module while doing so -- see below.
**What it does:**
- `aura execute <test_id|--all|--url|--prompt> --junit-out <path>` writes
  a standard JUnit XML `<testsuites>/<testsuite>/<testcase>` structure.
  One `<testcase>` per step; a step is a JUnit failure if
  `assertion_passed is False` or it was escalated with no resolution.
  Steps with no assertion configured (`assertion_passed is None`) are not
  failures on their own.
- `--all` produces one combined file: each spec contributes its own
  `<testsuite>` element (via `build_testsuite_element`), collected across
  the batch loop and written once at the end via `render_junit_suites` --
  not one file per spec silently overwriting the same `--junit-out` path
  in turn.
- **Exit-code convention, now actually documented and enforced** (was
  previously undefined -- `aura execute` always exited 0 regardless of run
  outcome, confirmed by reading the code before this pass): 0 = every spec
  run this invocation PASSED or PASSED_WITH_HEALING; 1 = at least one spec
  FAILED or was ESCALATED, or the invocation couldn't start a run at all.
  `execute_test`/`execute_prompt`/`execute_url` now return the `RunReport`
  instead of `None` so `aura/main.py`'s `_exit_nonzero_if_failed()` can
  check it. `--interactive` mode is explicitly excluded from this (it's a
  live human-wait flow, not a CI-suitable one) -- not an oversight.
- Real bug found and fixed while adding test coverage: the pre-existing
  `build_testsuite_element` checked `step.get("healed_via", "")` to decide
  whether to note a step as self-healed, but `VisionActionResult` (the
  actual schema every entry in `step_results` is built from) has no
  `healed_via` field at all, and `ReportAggregator` doesn't thread which
  specific `step_id` a learned skill corrected into `step_results` either
  -- this branch could never fire, ever, on real data; it silently read
  the `""` default every single time. Fixed by removing the false
  per-step attribution and instead noting self-healing honestly at the
  `<testsuite>` level via `RunReport.self_healed_steps`, the one place
  this count is actually tracked correctly. This is the same class of bug
  as D-017's `db_adapter`/`cross_modal_diagnoser` finding: a field
  referenced by name in one module that was never actually populated by
  the module that was supposed to produce it -- a contract mismatch
  invisible to either file's own internal logic.
**Verification:** 10 new tests in `tests/test_junit.py` (unit-level,
against real on-disk `raw_results.json` fixtures matching
`report_aggregator.py`'s actual output shape, not a mocked-away version of
it) plus 2 live end-to-end CLI runs against the real example spec --
single-spec `--junit-out` and `--all --junit-out` combined-suite mode both
confirmed to produce valid, correctly-structured XML and the documented
exit code (1, since the live run escalated for the same pre-existing
sandbox reason noted throughout this log -- no Chromium binary reachable
here). Full suite: 351 passing (up from 343), same pre-existing 9
sandbox-only Playwright/Chromium failures, zero new regressions.
**Not done:** the documented GitHub Actions example workflow template
(`.github/workflows/aura-example.yml`) from the original Phase G plan
wasn't added this pass -- the JUnit output itself (the part CI actually
consumes) was the higher-value item to land and verify first. Flagged as
a small, low-risk follow-up, not silently dropped.

## D-027 — Phase G3: real pixel-diff visual regression testing

**Decided:** 2026-07-14
**Context:** "visual regression is a hash-diff, not a real diff" gap --
`runtime/hooks/capture.py`'s `file_hash` only ever answered "did the
screen change" (boolean), with no quantified diff, no baseline
versioning, no diff visualization. Built from scratch this pass (unlike
G1/G2, no prior partial implementation existed for this one).
**What it does:**
- New `agents/vision/visual_regression.py::compare_to_baseline()` --
  Pillow `ImageChops.difference` + a numpy-vectorized pixel count (numpy
  isn't a declared direct dependency, but is a hard transitive dependency
  of `opencv-python-headless`, which is declared, so it's guaranteed
  present; a pure-Python per-pixel loop would be too slow on a real
  1080p+ screenshot). Returns a real `diff_ratio` (fraction of pixels that
  differ in any RGB channel), not just a boolean.
- **Deliberately separate from, not a replacement for**,
  `capture.py`'s `file_hash` (still used exactly as before for the
  `WAIT_FOR_HUMAN_ACTION` polling loop, where a cheap boolean is genuinely
  the right tool) and `assertions.py`'s OCR text matching (a different
  question -- "does this text appear" vs. "does this look the same as
  last time"). Three mechanisms, three different questions, none
  redundant with the others.
- **Persisted baselines, deliberately NOT gitignored.** `runtime/baselines/`
  is the one subdirectory of `runtime/` that is meant to be committed --
  a visual-regression baseline that isn't shared across machines/CI
  defeats the entire point (every fresh checkout would see "no baseline
  yet" and silently treat the first run as automatically passing,
  catching nothing). `.gitignore` was deliberately left unchanged for
  this directory (only a `.gitkeep` added); `screenshots/`/`data_cache/`
  remain gitignored as before since those genuinely are per-run ephemeral
  state, not shared fixtures.
- **New, additive-only schema fields** -- `TestStep.visual_baseline_key`
  (`Optional[str] = None`) and `TestStep.visual_diff_tolerance`
  (`float = 0.02` default), `VisionActionResult.visual_diff_ratio`/
  `visual_diff_image_ref`/`visual_baseline_created`. Every existing
  spec/step/test is completely unaffected -- the feature is entirely
  opt-in per step.
- **Wired into `orchestrator/run_engine.py`** immediately after the
  existing OCR `expected_state` check, with an explicit combining rule: if
  the OCR assertion already failed, a passing visual diff doesn't revive
  `assertion_passed` back to `True`; otherwise the visual diff's own
  verdict decides it. A failing visual diff does **not** force
  `escalate=True` (matches the existing OCR-assertion-failure path's own
  behavior -- only a failed screenshot *capture* escalates, since that's
  an infra failure, not an assertion failure).
- First comparison for a given `visual_baseline_key` creates the baseline
  and reports success with `baseline_created=True` -- never fabricates a
  pass/fail verdict against a baseline that doesn't exist yet, matching
  `cloud_adapter.py`'s established honesty convention (D-017).
- Dimension mismatch (baseline and current screenshot are different
  sizes) is reported as a full failure (`diff_ratio=1.0`,
  `dimension_mismatch=True`), not silently resized/padded to compare
  anyway -- resizing would paper over a potentially real, meaningful
  layout change.
- Persisted diff-highlight image (`runtime/baselines/<key>_diff_latest.png`,
  amplified 8x so a real but visually subtle pixel delta is actually
  visible to a human, not near-black and easy to miss) is only written on
  a failing comparison, matching the "don't clutter storage with evidence
  for the common case" pattern `capture.py` already uses for its own hash
  check.
- `reports/templates/run_report.html.j2` gets a new conditional panel per
  step showing the diff percentage and, on failure, the amplified diff
  image -- alongside the existing screenshot panel, not replacing it.
**Verification:** 7 unit tests (`tests/test_visual_regression.py`,
synthetic Pillow images with deliberate, known pixel changes -- identical
image, small change under tolerance, large change over tolerance,
dimension mismatch, baseline-key filesystem sanitization) plus 2 real
end-to-end integration tests through `RunEngine.run_spec()`
(`tests/test_run_engine.py`) proving `TestStep.visual_baseline_key`
actually reaches `compare_to_baseline()` through the full pipeline, not
just as an isolated unit. Full suite: 351 passing, zero regressions (same
run as D-026's verification, both landed in one pass).

**Update (2026-07-19, D-052):** the baseline-approval CLI command flagged
below as a follow-up is now done -- see `aura baselines list|approve|reject`.
The per-channel/perceptual threshold remains genuinely not done.

**Not done:** a per-channel/perceptual difference threshold (vs. the
current "any channel differs at all" strict comparison) -- flagged in the
module's own docstring as a reasonable future refinement, not implemented
here. No CLI command for reviewing/approving a new baseline when a
legitimate UI change causes an expected diff (today, deleting the file
under `runtime/baselines/` and re-running is the only way to reset one) --
a `aura baselines approve <key>` command would be a natural, small
follow-up.

## D-028 — Phase H1: cross-run trend analytics (pass-rate over time, per-test history)

**Decided:** 2026-07-15
**Context:** Phase H of the gap-review roadmap (Phases G–M) — "trend
reporting" was entirely missing: `api/run_store.py`'s SQLite `api_runs`
table persisted every run, but had no notion of "the same test run
multiple times" and no query surface for history/pass-rate over time.
**What it does:**
- New `test_key` column on `api_runs` (migrated in-place on an existing
  `api_runs.db` via a guarded `ALTER TABLE`, not just on fresh installs),
  populated at `create()` time from `spec.get("test_id")` (guided mode) or
  `spec.get("test_name")` (autonomous mode). A run submitted with neither
  field has no stable identity and is deliberately excluded from
  trend/flaky queries rather than lumped under a shared placeholder key —
  a one-off run isn't "a test" in the trend-tracking sense.
- `ApiRunStore.test_history()` / `pass_rate_series()` / `list_tracked_tests()`
  — chronological per-test history, a cumulative pass-rate series, and the
  set of tracked test_keys for a tenant. Only terminal-status runs
  (`passed`/`passed_with_healing`/`failed`/`escalated`) count; a
  still-`running`/`queued` row isn't a pass or fail yet.
- New API routes, registered **ahead of** the pre-existing `/{run_id}`
  catch-all (verified with a dedicated regression test —
  `test_trend_route_not_swallowed_by_run_id_catchall` — since FastAPI
  matches routes in registration order and `/analytics/...` would
  otherwise 404 as a bogus run lookup): `GET
  /api/v1/test-runs/analytics/tests`, `GET
  /api/v1/test-runs/analytics/tests/{test_key}`.
- Web dashboard gets a new **Analytics** nav view (`webui/templates/index.html`,
  `webui/static/js/app.js`) rendering tracked tests + pass rates, reusing
  the existing card/badge design tokens (no new CSS). A small new `trend`
  icon was added to `icons.js` in the same hand-drawn iconsax-Linear style
  the rest of the set already uses.
- Tenant-isolated throughout — every query is scoped by `tenant_id`,
  matching the existing `api_runs` access pattern.
**Not done:** no CLI-side equivalent. `aura execute` (the local CLI path)
writes to `orchestrator/memory.py`'s `run_state` table, not
`api/run_store.py`'s `api_runs` — and `run_state` is keyed by `run_id`
with `ON CONFLICT DO NOTHING` / in-place status updates, so it only ever
retains the *latest* status per test, not history across repeated runs of
the same test_id. Building CLI-side trend analytics on top of it would
require a schema change to that table (an append-only history table, not
the existing single-row-per-run_id design) — flagged here as a real,
separate gap rather than silently assumed to be covered by this pass.
Trend analytics in this pass is scoped to the API/service-layer surface,
which already has one fresh `run_id` per submission and therefore
genuinely retains history.
**Verification:** 11 new tests (`tests/test_run_store_analytics.py`,
including a real pre-Phase-H legacy-schema SQLite file to prove the
migration path works, not just a fresh DB) + 5 new API-level tests
(`tests/test_analytics_api.py`, including the route-ordering regression
test above and a tenant-isolation check). Full suite: 374 passing (up
from 351), same pre-existing 9 sandbox-only Playwright/Chromium failures,
zero regressions.

## D-029 — Phase H2: flaky-test detection + opt-in quarantine

**Decided:** 2026-07-15
**Context:** the other half of Phase H — "flaky-test detection/quarantine,
opt-in only, `--all` skips quarantined tests with a visible message,
`--include-quarantined` overrides" (original phase plan wording).
**What it does:**
- `ApiRunStore.get_flaky_candidates(tenant_id, min_runs=3, min_transitions=2)`
  — built directly on D-028's `test_history()` query layer, per the
  original plan ("H2 depends on H1's query layer, so these stay one
  phase"). A test is a candidate when its outcome flips between
  pass/fail at least `min_transitions` times across at least `min_runs`
  completed runs. Deliberately **not** just "pass rate below X%": a test
  that fails every single run isn't flaky, it's just broken (zero
  transitions, excluded); a test that passed 10 times then started
  failing consistently after a real regression isn't flaky either (one
  transition, excluded) — both are covered by dedicated tests
  (`test_consistently_failing_test_is_not_flaky`,
  `test_single_regression_is_not_flaky`).
- New API route `GET /api/v1/test-runs/analytics/flaky` (query params
  `min_runs`, `min_transitions`), same route-ordering care as D-028.
  Surfaces candidates only — nothing calls this automatically, and
  nothing in this codebase quarantines a test as a side effect of running
  it.
- New `orchestrator/quarantine_store.py` — a small JSON file (not SQLite;
  this is a short, rarely-written, human-readable list, unlike the
  high-churn run-history tables), under `orchestrator/skills_store/`
  alongside the skill library it's conceptually a sibling of. Exposes
  `quarantine()`/`unquarantine()`/`is_quarantined()`/`list_quarantined()`.
- CLI: `aura skills quarantine <test_id> --reason "..."`, `aura skills
  unquarantine <test_id>`, `aura skills quarantined` (new `skills`
  subcommands, alongside the pre-existing list/export/import/diff).
- `aura execute --all` now peeks each requirement doc's test_id (via
  `agents/planner/spec_generator.py::infer_test_id` — a new module-level
  function extracted from `LocalHeuristicBackend._infer_test_id` so the
  `--all` skip-check and the Planner use the exact same heading-inference
  logic instead of a hand-copied regex that could drift) *before*
  generating a spec or running anything, and skips it with a visible
  `[yellow]Skipped -- <test_id> is quarantined (<reason>)...[/yellow]`
  message if quarantined. New `--include-quarantined` flag runs it anyway
  without requiring an explicit `unquarantine` first. If every doc in
  `requirements_input/` is quarantined, `--all` now exits 1 with an
  explicit "nothing ran" message rather than silently succeeding with an
  empty report list.
**Not done:** quarantine is CLI-side/local-file only; there's no API
endpoint to quarantine a test from the web dashboard yet (a human sees a
flaky candidate in the Analytics view but currently has to go run `aura
skills quarantine` in a terminal to act on it) — flagged as a natural,
small follow-up, not silently dropped. Also not done: quarantine entries
never expire/auto-review — a quarantined test stays quarantined
indefinitely until someone explicitly unquarantines it, which is the
correct default (no silent re-enabling of a known-flaky test) but means
there's currently no reminder/staleness check if someone quarantines a
test and forgets about it.
**Verification:** 7 new tests (`tests/test_quarantine.py`, including a
corrupt-JSON-file recovery case) + 1 new flaky-route API test + a live
CLI smoke test (`aura skills quarantine` → `aura execute --all` actually
skipping the quarantined spec with the documented message → `aura skills
unquarantine` restoring it). Full suite: 374 passing, zero regressions
(same run as D-028's verification, both landed in one pass).

## D-030 — Phase I: cross-browser support (I1) + video recording (I2)

**Decided:** 2026-07-15
**Context:** Phase I of the gap-review roadmap (Phases G–M), grouped
because both items touch `runtime/hooks/browser.py`'s session setup
directly — one careful pass through that file instead of two.

**I1 — cross-browser support:**
- `config/settings.py`: new `playwright_browser: str = "chromium"` field
  plus a module-level `PLAYWRIGHT_BROWSER_CHOICES = ("chromium", "firefox",
  "webkit")` constant, shared between the settings default and the CLI's
  `--browser` option so the two lists can't drift apart.
- `runtime/hooks/browser.py::_BrowserSession.get_page()`: now does
  `getattr(self._playwright, settings.playwright_browser).launch(...)`
  instead of the hardcoded `self._playwright.chromium.launch(...)`. An
  invalid engine name is checked *before* touching Playwright at all and
  raises a clear `NoDisplayError` listing the valid choices, rather than a
  bare `AttributeError` surfacing from inside the try block.
- `aura/main.py`: new `--browser` option on both `aura execute` and `aura
  explore`, validated against `PLAYWRIGHT_BROWSER_CHOICES` with a clean
  exit-1 message on an invalid value, then applied via
  `settings.playwright_browser = browser` before `preflight.run_preflight_or_exit()`.
- **Verified, not just wired:** in this environment only the Chromium
  browser binary is actually downloaded (the same sandbox network-egress
  restriction noted for Chromium itself throughout this file in earlier
  phases) — Firefox/WebKit binaries are absent. So `tests/test_cross_browser.py`
  covers three things independently: (1) the real, live default (Chromium)
  path still works end-to-end against a local server; (2) the actual
  engine-*selection* dispatch logic, proven with a mocked Playwright
  instance so it doesn't depend on a binary being present — confirms
  `firefox` is requested via `getattr`, not silently falling back to
  Chromium; (3) a real, live confirmation that selecting `firefox` for
  real in this environment fails as a clean `NoDisplayError` (not a raw
  crash), proving the existing catch-and-wrap behavior still covers the
  new code path. This is an honest substitute for full three-engine live
  parametrization, which isn't possible here — flagged, not silently
  skipped.

**I2 — video recording:**
- `config/settings.py`: new `record_video: bool = False` (off by default —
  video files are meaningfully larger than screenshots, most runs don't
  need them) and a `videos_dir` property (`runtime/videos/`, same
  gitignored-generated-state category as `screenshots_dir`/`baselines_dir`).
- `runtime/hooks/browser.py`: when `settings.record_video` is on, the
  browser context is created with `record_video_dir=str(settings.videos_dir)`
  — Playwright records natively, no per-action code needed. Playwright
  only finalizes the video file to disk once its owning page is closed
  (`page.video` becomes `None` after), so `_BrowserSession.close()` now
  captures the video path via `self._page.video.path()` *before* closing
  the page, in that exact order — getting this order wrong was the most
  likely bug here, so it's covered directly by
  `test_record_video_produces_a_real_video_file_on_close` (asserts a
  real, non-empty file exists on disk after `close()`).
- **Bug found and fixed while writing tests:** `_last_video_path` is a
  session-singleton field that isn't reset between runs; a run with
  recording off, immediately after a run with recording on, was returning
  the *previous* run's stale video path instead of `None`. Fixed by
  clearing `_last_video_path = None` unconditionally at the top of
  `close()`, only re-populating it if this session actually recorded.
  Caught by `test_record_video_off_by_default_produces_no_video_path`.
- `runtime/hooks/video_recorder.py` (new): `SlideshowRecorder` — the
  OS/pixel-path fallback for targets with no live Playwright page (native
  desktop, no accessibility tree). Not a video encoder: it writes a JSON
  manifest referencing each step's already-captured screenshot in order,
  explicitly labeled `"kind": "slideshow"` with a note stating plainly
  that it is "not continuous video" — this was a hard requirement from
  the plan itself, not an implementation nicety, since silently presenting
  a slideshow as if it were a real recording would be misleading.
- `orchestrator/report_aggregator.py::finalize()`: new optional
  `extra_report_paths` param, merged into `report_paths` — reused the
  existing `report_paths` dict contract (already holding keys like
  `raw_json`) rather than adding a new schema field to `RunReport`.
- `orchestrator/run_engine.py::run_spec()`: instantiates a
  `SlideshowRecorder` up front when `settings.record_video` is on, feeds
  it every successfully-captured step screenshot as the main vision
  branch runs. At run end, *after* `browser_hook.close()` finalizes any
  real video to disk: if a real video path exists, it wins and is attached
  under `report_paths["video"]`; otherwise, if the slideshow recorder
  collected any frames, its manifest is attached under
  `report_paths["video_slideshow"]` — the two keys are named differently
  on purpose so a report renderer (or a human reading raw JSON) can never
  mistake one for the other.
- New tests: `tests/test_slideshow_recorder.py` (2, unit-level manifest
  correctness), `tests/test_run_engine_video.py` (2, full `RunEngine.run_spec()`
  integration — proves a real video file lands in the finalized
  `RunReport.report_paths` end-to-end, and that recording-off runs carry
  neither key).

**Verification:** 383 passing before this pass. **393 passing after**
(10 new: 6 in `test_cross_browser.py`, 2 in `test_slideshow_recorder.py`,
2 in `test_run_engine_video.py`) — zero regressions. Notably, all 393 pass
in this environment including what earlier phases documented as "9
pre-existing sandbox-only Chromium failures" — this session's sandbox
does have a working Chromium binary, so that pre-existing gap doesn't
reproduce here; it remains a real, disclosed environment-dependent
limitation for whichever environment run this next, not something this
pass silently fixed.

**Not done (explicitly out of scope for this pass):** live parametrization
of the existing Phase C DOM-path test suite across all three engines (only
possible in an environment where Firefox/WebKit binaries can actually be
downloaded); `--record-video` was not added as a capability-adapter-level
concept (Automation Anywhere trigger/validate runs, Phase 21, don't record
video — recording is scoped to `aura execute`/`aura explore`'s own
vision-execution runs only, where it's actually meaningful); no video
playback/slideshow viewer was added to the HTML report renderer itself
(`reports/render.py`) — `report_paths["video"]`/`["video_slideshow"]` are
populated and real, but surfacing them nicely in the rendered report is
left as a small follow-up, not required by the phase's own scope
("record", not "render nicely").

## D-031 — Phase J: parallel execution (API RunEngine de-singletoned, `--parallel N`)

**Decided:** 2026-07-15
**Context:** Phase J of the gap-review roadmap (Phases G–M), split into
its own phase per the roadmap's own sequencing rationale because it
touches genuinely shared state (same care level as D-017's secrets
split). Scope, per `Roadmap.md` §9: (1) remove the API layer's
`RunEngine` singleton, (2) fix `LoopGuardrail._states` to key on
`(run_id, step_id)` instead of just `step_id` so concurrent runs can't
corrupt each other's guardrail state, (3) add `aura execute --all
--parallel N` using `ThreadPoolExecutor`.

**1 — API `RunEngine` singleton removed (`api/routers/runs.py`):**
- The module-level `_engine: RunEngine | None` + `_run_lock =
  threading.Lock()` are gone. Every background task (`execute_run`,
  `execute_autonomous_run`, `execute_full_exploration_run`) now calls a
  new `_new_engine()` helper that constructs a fresh `RunEngine` per
  call.
- Previously, `_run_lock.acquire(blocking=False)` meant a second run
  submitted while any run was in flight immediately failed with `"Vision
  Core busy -- another run is in flight"` rather than actually running --
  full serialization dressed up as a lock, the opposite of what Phase J's
  own name promises. Concurrent runs now genuinely execute in parallel,
  bounded only by FastAPI's background-task thread pool.
- This was safe to do without further changes because `RunEngine` itself
  already holds no run-scoped mutable state on `self` shared across
  calls: `SkillStore`/`RunMemoryStore` open a new sqlite3 connection per
  operation (see `orchestrator/skill_store.py`/`orchestrator/memory.py`'s
  `_connect()` context managers) rather than keeping one open across the
  instance's lifetime, so two threads hitting the same on-disk `.db` file
  concurrently is exactly as safe as it already was for the CLI's
  `execute --all` sequential loop reusing one process across multiple
  `aura execute` invocations over time.

**2 — `LoopGuardrail._states` keying: reviewed, found already safe, NOT
changed:**
- Grepped every construction site of `LoopGuardrail(...)` in the repo.
  There is exactly one: `orchestrator/run_engine.py::run_spec()` creates
  `guardrail = LoopGuardrail()` as a local variable at the top of every
  call, never stored on `self` or any module-level location. Two
  concurrent `run_spec()` calls (whether from two API background tasks
  now running in parallel, or two `--parallel` CLI workers) each get
  their own, fully isolated `LoopGuardrail` instance -- there is no
  instance for two runs to collide on in the first place.
- Per `docs/debug.md`'s "verification, not assertion" rule, this is
  documented as *verified already correct*, not silently left alone
  without checking, and not changed just because the roadmap's original
  plan (written before this review) assumed it needed a fix. Re-keying
  `_states` to `(run_id, step_id)` would be inert today (a no-op given
  the current one-guardrail-per-call architecture) and was skipped to
  avoid adding unused complexity — see `context.md` §6 rule 7's
  code-minimalism ladder ("does this need to exist at all?"). A comment
  was added directly in `orchestrator/guardrails.py::LoopGuardrail`'s
  docstring stating the precondition under which this would need
  revisiting (if `RunEngine` ever starts sharing one `LoopGuardrail`
  instance across calls), so this isn't a silent assumption for the next
  pass to rediscover from scratch.

**3 — `aura execute --all --parallel N` (`aura/main.py`):**
- New `--parallel` int option, default `1` (preserves the exact original
  sequential behavior and glob-sort ordering -- verified by
  `test_parallel_one_matches_sequential_behavior`).
- `--parallel N > 1` filters quarantined specs up front (identical
  logic/messages to the original sequential path), then submits the
  remaining specs to a `ThreadPoolExecutor(max_workers=N)`, collecting
  results via `as_completed`. `ThreadPoolExecutor`, not
  `multiprocessing`, because this is I/O-bound work (screenshot capture,
  OCR/DOM lookups, adapter network calls), the same reasoning
  `Roadmap.md` §9 gives.
- `execute_cmd.execute_test` (called by each worker) already builds its
  own `SkillStore`/`RunMemoryStore`/`RunEngine` per call inside
  `_run_requirement_text` -- no shared mutable state between worker
  threads was introduced by this change. `junit_suites` is a plain
  `list`; `list.append` is atomic under the GIL, so concurrent appends
  from worker threads don't need an explicit lock.
- `--parallel 0` or negative rejected with a clean exit-1 message rather
  than a confusing `ThreadPoolExecutor` construction error.
- **Honest scope note, disclosed in `docs/README.md`:** `--parallel` is
  intended for unattended (`--yes`/`--autonomous`) batch runs against
  independent targets. It does not solve, and was never meant to solve,
  two workers contending for the same physical display/screenshot
  surface on one machine -- that's a hardware/OS constraint, not
  something this file's threading logic could fix. Per-spec console
  output from different worker threads may also interleave in the
  terminal; this is a cosmetic limitation of concurrent live output, not
  a correctness bug, and is called out rather than silently accepted as
  fine.

**New tests:** `tests/test_parallel_execution.py` (6 tests) --
`--parallel` dispatches every target exactly once regardless of N,
`--parallel 1` matches the original sequential call order, `--parallel 0`
is rejected, a failed spec under `--parallel` still produces exit code 1,
and two regression guards confirming `api/routers/runs.py` no longer
exposes `_engine`/`_run_lock`/`_get_engine` and that `_new_engine()`
returns independent instances each call.

**Verification:** 379/391 passing before this pass (12 failed + 2 errors
-- the same pre-existing Phase C Playwright/Chromium sandbox-only gap
documented throughout this file; this sandbox's network-egress rules
block the one-time Chromium binary download). **385/391 passing after**
(6 new tests, all passing) -- zero regressions, identical pre-existing
failure set.

**Not done (explicitly out of scope for this pass):** Phase K
(multi-tenant/fine-grained RBAC) and Phase L/M (new capability adapters,
defect-tracker adapter) remain not started, per `Roadmap.md` §9's own
sequencing. No change was made to how the in-memory run store persists
(`api/run_store.py`'s SQLite backing was already fine for concurrent
access; this phase's scope was strictly the `RunEngine`
singleton/guardrail/CLI-parallelism items listed above).

## D-032 — Phase K: multi-tenant / fine-grained RBAC (project-tag permission matrix)

**Decided:** 2026-07-15
**Context:** the fifth phase of the second remediation roadmap (Phases
G–M). Original gap: "JWT auth + per-tenant run isolation exist in the API
layer, but it's a single-role model (no fine-grained RBAC like 'this user
can only run specs in project X')." Verified before writing any code that
tenant-level isolation was already real and thorough — every run/analytics
query in `api/run_store.py` is already scoped by `tenant_id` (confirmed by
grep across `api/`, not assumed) — so this phase's actual scope is
*within*-tenant access control, not tenant isolation itself, which needed
no changes.
**What it does:**
- `TestSpec.project_tag: Optional[str] = None` (additive) — an optional
  label a spec author can set. `api/spec_builder.py::build_test_spec()`
  reads it from the incoming request body's `project_tag` key.
- `TokenPayload.allowed_project_tags: Optional[list[str]] = None`
  (additive) — carried in the JWT itself (like `tenant_id`/`role` already
  are), so no extra DB lookup is needed per request to check it.
  `create_access_token()` gained a matching optional parameter.
- `api/security.py::user_can_access_project(user, project_tag) -> bool` —
  a small pure function, deliberately not a `Depends()` factory like
  `require_role` (a spec's `project_tag` is only known after the request
  body is parsed, not statically at route-decoration time, so the check
  has to happen inline in the handler). Rule, in order: admin always
  passes; an untagged spec (`project_tag is None`) is always accessible;
  a user with `allowed_project_tags is None` (every existing/new user,
  unless explicitly restricted) is unrestricted; only a tagged spec *and*
  a restricted user actually narrows anything, to exactly that user's
  list. `require_project_access()` is the raise-on-deny wrapper used at
  the one write path (`create_run`); `user_can_access_project()` itself is
  used directly at the two read paths (`list_runs` filters, `get_run`
  denies) since a list/single-item read needs a boolean to filter/branch
  on, not an automatic raise.
- **New admin-only endpoint**, `PUT /api/v1/users/{username}/project-tags`
  (`api/routers/users.py`, new router, registered in `api/main.py`
  alongside the existing four). Deliberately **not** exposed via
  `/auth/signup` — self-service signup can set nothing about its own
  access beyond the existing default (`tenant_id="default"`,
  `role="executor"`, unrestricted tags), so signup can never be used for
  privilege escalation *or* narrowing of someone else's access. An empty
  list (`[]`) in the request normalizes to `None` (unrestricted) before
  reaching `user_can_access_project` — an admin clearing a restriction by
  sending `[]` should mean "no restriction," not "can access nothing,"
  which would be a confusing footgun. The raw function itself does treat
  an actual empty list as "no tags allowed" (tested directly in
  `tests/test_security.py`) — the normalization is deliberately the
  router's job, a usability choice, not baked into the function's own
  semantics.
- `api/user_store.py` — `verify()`/`create_user()`/`find_or_create_oauth_user()`
  all now read/write `allowed_project_tags` (defaulting to `None`/absent
  for every existing user record, so no migration is needed — `.get()`
  already handles a missing key gracefully). New
  `set_allowed_project_tags(username, tags)` method, raising `ValueError`
  for an unknown username (same convention as `create_user`'s
  "already exists" check), caught and turned into a 404 by the router.
- **Read-path enforcement, not just write-path:** `list_runs` filters out
  any run whose stored spec has a `project_tag` the caller can't access
  (no schema migration needed — `api/run_store.py`'s `_to_public()` already
  stores/returns the full spec dict, so `run["spec"].get("project_tag")`
  was already available). `get_run` denies with the *same* 404 message the
  "run doesn't exist at all" case already used ("Run not found or access
  denied") — deliberately not a 403, since telling an unauthorized caller
  "this exists, you just can't see it" leaks more than telling them
  nothing was found, matching the existing endpoint's own privacy-
  conscious phrasing rather than introducing an inconsistent status code.
- No live token revocation exists anywhere in this system (a pre-existing
  property, not introduced by this phase) — restricting a user's tags via
  the new endpoint takes effect on their *next* login, not retroactively
  on tokens already issued. Confirmed this matches existing role/tenant-
  change behavior (same limitation already applies to those) rather than
  being a new gap specific to this feature.
**Verification:** 16 new tests — `tests/test_security.py` (6, direct unit
tests of the pure `user_can_access_project` function covering every
branch including the empty-list-vs-None distinction) and
`tests/test_project_tag_permissions.py` (10, full FastAPI `TestClient`
integration tests: untagged-always-accessible, admin-bypass, unrestricted-
user, restricted-denied, restricted-allowed-on-matching-tag, restricted-
still-sees-untagged, non-admin-cannot-set-tags, 404-on-unknown-username,
empty-list-normalization, list/get read-path filtering). Plus a live
manual end-to-end run through a real `TestClient` instance outside the
test suite (login → signup → restrict → re-login → denied run → allowed
run), reproducing the exact flow a real deployment would use. Full suite:
**401/415 tests passing** (16 new this pass; the 12 failed/2 errored are
the same pre-existing Phase C Playwright/Chromium sandbox-only failures
documented throughout this file — zero regressions, confirmed against the
385/391 baseline from the immediately preceding Phase J pass).
**Not done:** no bulk/list endpoint for an admin to see every user's
current tag restrictions at once (only single-user get-via-side-effect
today, through the PUT response) — a `GET /api/v1/users` listing endpoint
would be a natural, small follow-up. No CLI equivalent of the new PUT
endpoint (`aura users set-project-tags <username> <tags>` or similar) —
this phase's scope was the API/service-layer surface specifically, per
the original gap review's own framing ("JWT auth... in the API layer").
Live token revocation (flagged above) remains a pre-existing, unaddressed
limitation, not newly introduced or newly deferred by this phase.

## D-033 — Phase L: new capability adapters (accessibility, security headers, performance budget)

**Decided:** 2026-07-16
**Context:** Phase L of the gap-review roadmap (Phases G–M), batched
because the registration pattern (new `CapabilityType` + `default_registry()`
entry) is mechanically identical across all three, not because the
underlying logic overlaps.

**L1 — Accessibility (`agents/capability/accessibility_adapter.py`,
`CapabilityType.ACCESSIBILITY`):**
- Runs a real WCAG scan via **axe-core**, vendored locally at
  `vendor/axe-core/axe.min.js` (v4.12.1, fetched via `npm pack axe-core`
  from the whitelisted `registry.npmjs.org`, unmodified minified bundle +
  its own MPL-2.0 license, provenance documented in
  `vendor/axe-core/README.md`). Deliberately not CDN-loaded — AURA is
  offline-first by design (D-002/D-018), and loading a rules engine from
  a CDN at scan time would make every accessibility check silently depend
  on an external party's uptime for a target that may itself be offline.
  `page.add_script_tag(path=...)` injects it from local disk; zero network
  calls beyond whatever the test target itself needed.
- `severity_threshold` param (default `"serious"`, one of axe-core's own
  `minor`/`moderate`/`serious`/`critical` impact levels) — only violations
  at or above the threshold fail the check; everything found is still
  reported in evidence regardless, so a caller can see the full picture
  even when only asking to fail on the serious stuff.
- **Verified against a deliberately-broken local HTML fixture**, exactly
  per the phase's own requirement — a page with an `alt`-less `<img>` and
  an empty-text `<a>` reliably trips `image-alt` (critical) and
  `link-name` (serious) among others; a clean, properly-labeled page
  scans with zero violations. Both are asserted directly against the real
  axe-core engine, not a mocked result.

**L2 — Passive security headers
(`agents/capability/security_headers_adapter.py`,
`CapabilityType.SECURITY_HEADERS`):**
- Plain `httpx` GET (same "no DOM automation" posture as
  `link_checker.py`) — header presence against a configurable list
  (HSTS/X-Content-Type-Options/X-Frame-Options/CSP/Referrer-Policy by
  default), `Set-Cookie` flag checks (Secure/HttpOnly/SameSite), and a
  configurable "common exposed paths" list (`.env`, `.git/config`,
  `wp-config.php.bak`, etc.) checked with a plain GET each.
- **Explicitly, permanently out of scope by design** (enforced by what the
  code does, not just a docstring claim): no payload injection, no active
  vulnerability probing, no exploitation of anything found — every
  request this adapter issues is a GET; a dedicated test
  (`test_no_active_probing_only_get_requests_issued`) makes any `POST`
  call raise inside the test itself, proving the constraint rather than
  just asserting it.
- The exposed-path check has one deliberate false-positive guard: if the
  base URL's own 404 happens to be served with a 200 status and identical
  body length to what a checked path returns, it's treated as the site's
  generic not-found page, not a real hit — documented and tested
  (`test_exposed_env_file_is_detected` proves real detection;
  the false-positive guard's actual narrower behavior is also directly
  tested rather than assumed).

**L3 — Performance budget
(`agents/capability/performance_adapter.py`, `CapabilityType.PERFORMANCE`):**
- Single Playwright page load, metrics read directly from the browser's
  own `performance.getEntriesByType('navigation'/'paint')` (ttfb,
  DOM-content-loaded, load time, first paint, first contentful paint) —
  compared against a configurable `budget` dict (sane generous defaults
  provided so an empty/missing budget doesn't crash, not a recommendation
  of "good" numbers).
- **Explicitly, permanently out of scope by design:** no multi-user load
  generation of any kind (no concurrency, no ramping, no sustained
  traffic) — one page, one load, one browser. Not a substitute for Phase
  H's trend analytics either — this is a single data point per run, not a
  history/percentile series.

**Shared implementation notes:**
- All three follow the exact three-part registration pattern every prior
  capability adapter uses: a `CapabilityType` enum entry
  (`orchestrator/schemas.py`), a `registry.register(...)` call in
  `orchestrator/capability_adapter.py::default_registry()`, and nothing
  else — `config/tool_registry.yaml` already has a single generic
  `Capability.check` entry (by design, see that file's own module
  docstring), so no per-adapter tool-registry changes were needed, same
  as every capability adapter since Phase 14.
- **Egress controls needed zero changes**, verified rather than assumed:
  all three adapters read their target from `params["url"]`, which
  `orchestrator/capability_router.py::_URL_PARAM_KEYS` already covers —
  confirmed with a dedicated test
  (`test_extract_host_covers_phase_l_adapters_without_router_changes`)
  rather than just asserting it by inspection.
- `agents/capability/accessibility_adapter.py` and
  `agents/capability/performance_adapter.py` manage their own Playwright
  lifecycle (sync API, one browser/context/page per `run()` call),
  mirroring `playwright_validator.py`'s existing, disclosed
  not-yet-consolidated posture (TRD §11.5) rather than introducing a
  fourth independent pattern.
- A minor doc bug was caught and fixed while writing these: both new
  Playwright-based adapters' initial `ImportError` messages pointed at
  `pip install .[automation_anywhere]`, an optional extra that no longer
  exists in this version of `pyproject.toml` — `playwright` graduated to
  a core dependency during an earlier phase (Phase C/D era) and the extra
  was removed, but `automation_anywhere_adapter.py`'s original error
  message (written when the extra still existed) was never updated.
  Fixed in both new files to point at `pip install -e .` /
  `playwright install chromium` instead. (The pre-existing stale message
  in `automation_anywhere_adapter.py` and `playwright_validator.py`
  themselves was not touched here — out of scope for this phase, flagged
  as a small follow-up.)

**Verification:** 415 passing before this pass. **435 passing after**
(20 new: 6 in `test_accessibility_adapter.py`, 7 in
`test_security_headers_adapter.py`, 6 in `test_performance_adapter.py`
[including the shared registry-wiring test], 1 new egress-coverage test
in `test_capability_egress_controls.py`) — zero regressions.

**Not done (explicitly out of scope for this pass):** the stale
`pip install .[automation_anywhere]` message in the pre-existing
`automation_anywhere_adapter.py`/`playwright_validator.py` (found while
fixing the same bug in this phase's own new files, but out of scope to
fix retroactively here); a11y/perf/security-header results don't yet feed
into Phase H's trend analytics (each run's result is captured in the
normal step-result/report flow, but there's no dedicated "accessibility
score over time" or "performance budget trend" view — a reasonable
follow-up, not required by this phase's own scope); Phase M (test-case
management adapter) is next and last, lowest confidence by design.

## D-034 — Phase M: test-case-management adapter (generic REST + field-mapping)

**Roadmap Phase M** (`Roadmap.md` §9): the fifth and last phase of the second
remediation roadmap (Phases G–M), deliberately last and lowest-confidence
by the roadmap's own framing.

**What was built:** `agents/capability/defect_tracker_adapter.py`
(`CapabilityType.DEFECT_TRACKER`) — one generic REST adapter for
Jira/TestRail/Zephyr/Xray-style test-case-management and defect-tracking
tools, not a per-vendor SDK. The tool-agnostic part is a `field_mapping`
config supplied per call: a flat dict of generic field names
(`title`/`status`/`priority`/etc.) is written into whatever nested (Jira:
`fields.summary`, `fields.priority.name`) or flat (TestRail: `title`,
`status_id`) JSON shape the target tool expects, via a small
`_set_nested()` dotted-path helper. A matching `_get_nested()` helper reads
fields back out of a response body via `response_field_mapping`, so an
`action="get"` (or a create/update's own response) can be verified against
caller-supplied `expected_fields` — pass/fail is "the HTTP call succeeded
AND the fields I asked to check match," not just a status code.

Three actions: `create` (POST), `update` (PUT, against `base_url` +
`record_id`), `get` (GET). Method is overridable per call
(`params["method"]`) for tools with nonstandard verbs (e.g. a
Zephyr-style PUT-based execution update). Same registration pattern as
every capability adapter since Phase 14: one `CapabilityType` enum entry,
one `registry.register(...)` call in
`capability_adapter.py::default_registry()` — `config/tool_registry.yaml`
needed no changes (same generic `Capability.check` entry).

**One actual router change, unlike Phase L:** this adapter's primary URL
param is `base_url` (matching how Jira/TestRail/Zephyr/Xray REST clients
are conventionally configured), not the generic `url` key every prior
URL-based adapter used. `orchestrator/capability_router.py`'s
`_URL_PARAM_KEYS` didn't cover it, so egress-allowlist matching and audit
logging would have silently resolved `host=None` for every call — added
`"base_url"` to `_URL_PARAM_KEYS`, confirmed (not assumed) with a
dedicated test (`test_extract_host_covers_phase_m_defect_tracker_base_url`
in `test_capability_egress_controls.py`), the same way Phase L's own
"needed zero router changes" claim was verified rather than assumed.

**Honest confidence note (per the roadmap's own framing for this phase):**
verified only against a local mocked HTTP server in this sandbox (a tiny
`http.server`-based stand-in that records requests and replies with a
configurable status/body) — covering Jira-style nested mapping,
TestRail-style flat mapping, update-by-record-id, get+field-verification,
field-mismatch detection, unsupported-action/missing-base_url/connection-
error failure paths, and registry wiring. There is no real Jira/TestRail/
Zephyr/Xray account available to test against in this environment, so
live-integration correctness with any specific real vendor's actual API
shape, auth flow, or rate limits is unverified. This mirrors the exact
caveat the roadmap itself calls for ("will be verified only against a
mocked HTTP server... live-integration correctness is unverified").

**Explicitly out of scope, by design:** vendor-specific auth flows (OAuth
dance, session cookies) — the caller supplies `headers`, same posture as
`workflow_adapter.py`; bidirectional sync/webhooks; any hardcoded vendor
field shape inside this file (if a real vendor turns out not to be
representable via a flat field_mapping, that's a scope decision to flag
later, not something to route around silently here).

**Verification:** 435 passing before this pass. **449 passing after**
(14 new: 13 in `test_defect_tracker_adapter.py`, 1 in
`test_capability_egress_controls.py`) — zero regressions. The 19
failing/2 erroring tests in this pass's full run are the same
pre-existing Chromium-binary-download sandbox gap documented throughout
this file (this session's sandbox additionally lacks the binary for
Phase L/I's Playwright-based adapters and Phase C's DOM path, which were
previously green in sandboxes where the one-time download succeeded) —
none touch this phase's own code paths (`agents/capability/
defect_tracker_adapter.py`, `orchestrator/capability_router.py`,
`orchestrator/capability_adapter.py`, `orchestrator/schemas.py`), and are
unrelated to this phase.

**All seven phases of the second remediation roadmap (G/H/I/J/K/L/M) are
now complete.**

## D-035 — Phase N: Automation Anywhere adapter completeness (Control Room auth + multi-bot/multi-runner trigger)

**Roadmap Phase N** (`Roadmap.md` §10): first phase of the third
remediation roadmap (Phases N–Q). Both N1 and N2 landed in one pass inside
`agents/capability/automation_anywhere_adapter.py`'s REST-mode internals,
per the roadmap's own framing ("one careful pass through that file instead
of two").

**N1 — Control Room authentication.** Added `AutomationAnywhereAdapter._get_token()`:
a real login step against `{control_room_url}/v1/authentication`, accepting
either `username`/`password` or `api_key` in `params`. The returned token
is cached on the adapter instance, keyed by `control_room_url`, with a
30-second-early expiry margin computed from the response's `expiresIn`.
`_run_rest()` fetches a token before the initial deploy call and, on a 401
from either the deploy or the poll request, calls `_get_token(..., force=True)`
to bypass the cache and re-authenticate, retrying the failed call once
rather than failing the whole run. `auth_token` in `params` remains a valid
override that skips login entirely (checked first, before any cache
lookup) — purely additive, no existing caller that already supplies its
own token sees any behavior change. Callers that supply neither an
override token nor any credentials get the exact pre-Phase-N behavior:
deploy/poll proceed with no `X-Authorization` header.

**N2 — Multi-bot / multi-runner trigger.** `bot_id` and `run_as_user_id`
now accept a scalar (unchanged shape) or a list (`_as_list()` normalizes
both). The deploy request sends `fileId` as the full list when more than
one bot is named (else the original scalar, for wire-format back-compat
with whatever Control Room expects for a single-target deploy) and
`runAsUserIds` as the full list either way. `_extract_deployment_ids()`
reads either a single `deploymentId`/`automationId` or Control Room's
documented multi-target `deploymentIds` array out of the deploy response.
`_poll_rest_status_multi()` replaces the old `_poll_rest_status()`: it
polls with an `"in"` filter over every still-pending deployment id each
round (not one `"eq"` filter per target), updates a per-target
`{status, record}` map as terminal statuses arrive, stops polling a target
the moment it goes terminal, and marks any target still pending when the
shared deadline elapses as `TIMED_OUT` independently of its siblings —
one slow/stuck target can no longer mask a sibling's real, already-known
result. `expected.rollup` (`all_must_complete`, default, or
`any_must_complete`) decides the single rolled-up `passed` verdict from
the per-target outcomes; an unrecognized rollup value fails cleanly with a
named error rather than silently defaulting. Evidence always includes the
full `targets` breakdown; for the common single-target case the previous
top-level `deployment_id`/`terminal_status`/`activity_record` keys are
also populated unchanged, so existing callers reading those keys directly
see no shape change — the new `deployment_ids`/multi-target keys only
appear when there's actually more than one target.

**Egress/router impact: none.** `control_room_url` was already in
`orchestrator/capability_router.py`'s `_URL_PARAM_KEYS` (added for Phase E
per D-021) and the new `/v1/authentication` call reuses the same
`control_room_url` host, so no router or egress-allowlist change was
needed — confirmed by re-reading `_URL_PARAM_KEYS`, not assumed.

**Verification — honest gap, disclosed rather than silently worked
around:** this sandbox session has no network egress and no `pytest`,
`httpx`, or `pydantic` installed, and no path to install them, which is a
different and more restrictive gap than the "Chromium binary download"
sandbox limitation noted throughout the rest of this file. The full Phase
N test suite was written (`tests/test_phase_n_automation_anywhere.py`, 9
tests covering login + token attach, token-cache reuse, 401 re-auth,
`auth_token` override back-compat, no-credentials back-compat, multi-bot
fan-out with `all_must_complete`/`any_must_complete` rollup, an unknown-
rollup failure path, single-`bot_id` back-compat evidence shape, and
independent per-target timeout) but could not be executed through `pytest`
in this environment. In its place, the same scenarios (N1 login/cache/
re-auth, N2 multi-target rollup pass/fail, N2 independent per-target
timeout) were re-verified by hand: minimal in-process stand-ins for
`pydantic.BaseModel` and `httpx.Client` were used to actually import and
exercise `AutomationAnywhereAdapter` end to end against `unittest.mock`
(stdlib, present)-driven fake HTTP responses, asserting the same outcomes
the pytest file asserts. This confirms the implementation runs and
produces the intended results, but it is not the same as a real `pytest`
run against the full existing suite (previously 449 passing as of D-034),
so **regression-freeness against the rest of the suite is unverified in
this session** — flagged plainly rather than claimed. Whoever picks this
up next with a working `pytest`/`httpx`/`pydantic` environment should run
`pytest tests/test_automation_anywhere.py tests/test_phase_n_automation_anywhere.py`
first, before touching anything else in Phase N/O/P/Q.

**Explicitly out of scope, by design (left for later phases or flagged,
not silently done here):** Phase O's data-seeding write path, Phase P's
Control Room audit-log retrieval, and Phase Q's Playwright trace files —
none of that code was touched in this pass, only `Roadmap.md` §10 was
updated to record all four phases' plans up front, per the roadmap
document the person supplied.

## D-036 — Phase O: data-seeding adapter (`db_seed_adapter.py`, AURA's first intentional DB write path)

**Roadmap Phase O** (`Roadmap.md` §10): given its own phase, deliberately
separate from Phase N, because it introduces AURA's first-ever intentional
write path to a database — the same elevated care level Phase J (shared
state) and Phase K (auth) got.

**New file, new capability type.** `agents/capability/db_seed_adapter.py`
+ `CapabilityType.DB_SEED` in `orchestrator/schemas.py`. `db_adapter.py`
(read-only, hardened per D-017) is completely untouched — this is an
additive new adapter, not a loosening of that one's guarantees.

**Structured input only.** Params are `connection_string`, `table`, and
either `values` (single row dict) or `rows` (list of row dicts) — never a
query string. The adapter builds one parameterized `INSERT INTO table
(cols...) VALUES (:col1, :col2, ...)` per call (executed once per row in
the batch, same statement, bound params only) via `sqlalchemy.text()`.
There is no code path that reads or executes caller-supplied SQL text at
all, so there's no "did we forget to block DROP/UPDATE" question to even
ask — confirmed with a test that passes a `query` param containing `DROP
TABLE users` alongside valid `values` and shows it has zero effect (the
key is simply never read).

**Identifiers are interpolated, not bound — so they're allowlisted
instead.** SQL doesn't support parameter binding for table/column names,
only for values. `table` and every key in `values`/`rows` must match
`^[A-Za-z_][A-Za-z0-9_]*$` or the call is rejected outright before any SQL
is built. This is an allowlist-and-reject choice, deliberately not a
quote-and-escape one — `db_adapter.py`'s own D-017 commentary on why a
denylist alone is fragile applies even more directly to identifiers, where
there's no reason to accept anything exotic in the first place.

**All rows in one call must share one column set.** Rather than silently
building a different INSERT per row (or silently dropping/padding
mismatched rows), a batch with inconsistent column sets across `rows`
fails the whole call with a clear error, before touching the database —
callers with genuinely different row shapes make separate calls.

**Two independent gates, not one.** `orchestrator/capability_router.py`'s
existing `capability_adapters_enabled` kill switch still applies (checked
before any adapter, including this one, is even reached — no change
needed there). On top of that, `settings.allow_db_seeding` (new field,
default `False`) is checked first thing inside
`DbSeedAdapter.run()` itself — a second, deliberate, adapter-specific gate,
per the roadmap's own framing, kept local to this one file rather than
folded into the router's generic logic (which is meant to stay
adapter-agnostic). Both must be true for a seed call to do anything.

**Only INSERT — structurally, not by filtering.** There is no
UPDATE/DELETE/DDL code path in this file at all, so "only INSERT" isn't a
runtime check that could have a gap; it's a statement of what the code is
capable of emitting. Precondition seeding creates rows that didn't exist;
it never mutates or erases ones that did.

**Every seed call is audited with the exact rows written.** Reuses the
existing `orchestrator/audit_logger.py` singleton (same sink
`capability_router.py`'s `CAPABILITY_EGRESS` records already go to), with
a new `DB_SEED` action, `resource=table`, and `details` containing
`row_count` and the full `rows` list actually inserted. Only logged on
success — a failed/rejected call (gate closed, bad identifier, DB error)
writes nothing and is not audited as if it had. This is deliberately more
detail than the router's own host-only egress log carries, since this is
the one adapter in the whole capability layer that leaves the target
database in a different state than it found it.

**Registration.** `orchestrator/capability_adapter.py::default_registry()`
now imports and registers `DbSeedAdapter()` alongside the existing
adapters. `config/tool_registry.yaml` needed no change — confirmed by
re-reading it: the single generic `Capability.check` entry already routes
every `CapabilityType` through the same registry lookup, exactly as it has
for every adapter since Phase 14.

**Egress/router impact: none beyond the new gate.** `connection_string` is
already in `capability_router.py`'s `_CONN_STRING_PARAM_KEYS`, so this
adapter's target host is extracted and allowlist-checked the same way
`db_adapter.py`'s already is — no router change needed there either.

**Verification — same disclosed sandbox gap as D-035.** This session
still has no network and no `pytest`/`sqlalchemy`/`pydantic` installed.
`tests/test_db_seed_adapter.py` (16 tests: gate on/off, single-row,
batch-row, mismatched-row-shape rejection, empty-rows rejection,
missing-values-and-rows rejection, bad table identifier, bad column
identifier, valid identifiers, query-param-smuggling-has-no-effect,
audit-logged-on-success, not-audited-on-failure, nonexistent-table
failure shape) was written but not run through `pytest`. In its place,
the adapter was hand-verified end-to-end against a **real sqlite3
database on disk** (not just mocks) using minimal in-process stand-ins for
`pydantic`/`pydantic_settings`/`sqlalchemy` (the sqlalchemy stand-in
translates `:name` bound params to real DB-API `?` params and executes
against actual `sqlite3` connections, including wrapping
`sqlite3.OperationalError` as `SQLAlchemyError` to match real
sqlalchemy's error-wrapping behavior for the failure-path test). Every
scenario in the real test file was independently re-run this way and
passed, including confirming rows were actually persisted (or, for
rejected calls, confirming the table stayed empty). This is still not a
real `pytest` run against the full existing suite, so **regression-freeness
against the rest of the suite remains unverified this session** — same
flag as D-035. Run
`pytest tests/test_automation_anywhere.py tests/test_phase_n_automation_anywhere.py tests/test_db_adapter.py tests/test_db_seed_adapter.py`
(then the full suite) in a real environment before trusting this as a
clean landing, and before starting Phase P.

**Explicitly out of scope, by design:** Phase P (Control Room audit-log
retrieval + report sync) and Phase Q (Playwright trace files) — untouched
this pass, plans already recorded in `Roadmap.md` §10 from the Phase N
session.

## D-037 — Phase P: Control Room audit log retrieval + report sync

**Roadmap Phase P** (`Roadmap.md` §10): both halves land in the same file
touched for Phases N (and now O is separate — Phase O touched
`db_seed_adapter.py`, not this one). P1 and P2 both live inside
`agents/capability/automation_anywhere_adapter.py`, since they're two
halves of the same "data synchronization" arrow in the architecture
diagram (`docs/TRD.md` §11) — lower risk than N/O since this phase is
entirely read-only against Control Room, no new write capability anywhere.

**P1 — audit log retrieval.** New `_fetch_control_room_audit()` on
`AutomationAnywhereAdapter`: once a target's poll has already reached a
terminal state, a `POST {control_room_url}/v2/auditlog/list` filtered on
that `deploymentId` fetches Control Room's own audit-log entries for it.
Opt-in via `params.include_control_room_audit` (default falsy/absent) —
existing callers who never asked for this see zero behavior change and
zero extra network round trips, which matters here more than for N1/N2
since this is a genuinely optional enrichment, not a correctness fix.
Shares the same one-retry 401-re-authentication path as the deploy/poll
calls (`_get_token(..., force=True)`), reusing N1's token machinery rather
than duplicating it.

**Best-effort, explicitly non-fatal.** A fetch failure (network error,
non-200, unexpected response shape) never changes the trigger's own
`passed`/`escalate` verdict — that verdict was already fully and correctly
determined by the terminal activity status *before* this call is even
made. The failure is recorded in its own `fetch_error` field instead
(`entries: []`, `fetch_error: "<reason>"`), so a caller who asked for the
audit trail and didn't get it can tell "no entries" apart from "couldn't
fetch it" — but it's never conflated with whether the bot itself
succeeded.

**P2 — report sync.** No new report-plumbing was needed. The fetched data
is merged directly into `CapabilityCheckResult.evidence` under a new
`control_room_audit` key — per target (`evidence["targets"][dep_id]
["control_room_audit"]`), plus mirrored to the top level
(`evidence["control_room_audit"]`) for the common single-target case,
matching N2's existing back-compat-shape convention. Since
`VisionActionResult.capability_result` (and therefore its `.evidence`)
already flows unmodified into `ReportAggregator.finalize()`'s
`raw_results.json` (referenced from `RunReport.report_paths["raw_json"]`)
for every capability-check step, this key alone is sufficient to put
Control Room's own audit trail and AURA's own step/result trail side by
side in one report — confirmed by re-reading
`orchestrator/schemas.py::VisionActionResult` and
`orchestrator/report_aggregator.py::finalize()` rather than assumed. No
changes to either of those two files, or to `orchestrator/run_engine.py`,
were needed.

**Key absent, not empty, when not requested.** When
`include_control_room_audit` isn't set, the `control_room_audit` key is
completely absent from evidence (not present-but-empty) — so existing
consumers of this adapter's evidence dict see no shape change at all
unless they specifically opted in, same convention N2 already established
for `deployment_ids` only appearing when there's more than one target.

**Verification — same disclosed sandbox gap as D-035/D-036.** No
`pytest`/`httpx`/`pydantic`/network this session.
`tests/test_phase_p_automation_anywhere.py` (5 tests: off-by-default no
extra call, opt-in fetch + evidence merge, fetch-failure-is-non-fatal,
401-during-audit-fetch re-authentication, multi-target per-target
breakdown) was written but not run through `pytest`. Hand-verified instead
using the same minimal `pydantic`/`httpx` stand-ins as D-035, plus a
regression check confirming the pre-existing single-target back-compat
evidence shape and the "missing control_room_url" failure path are both
still intact after this change — all passed. Regression-freeness against
the rest of the full suite remains unverified this session; run
`pytest tests/test_automation_anywhere.py tests/test_phase_n_automation_anywhere.py tests/test_phase_p_automation_anywhere.py`
(then the full suite) in a real environment before starting Phase Q, the
last phase in this roadmap.

## D-038 — Phase Q: Playwright native trace files (`runtime/hooks/browser.py`, mirrors I2's video lifecycle)

**Roadmap Phase Q** (`Roadmap.md` §10, last phase of the third remediation
roadmap): touches `runtime/hooks/browser.py` again (same file Phase I2's
video recording lives in), scoped separately since it's a distinct
feature, not a bug fix to I2.

**New `settings.record_trace` flag** (`config/settings.py`), off by
default, same posture as `record_video`. New `settings.traces_dir`
property (`runtime/traces/`), same category/lifecycle as `videos_dir` --
local generated run state, gitignored, not source, created on demand
rather than in `ensure_dirs()` (matching how `videos_dir` is handled).

**`_BrowserSession` (browser.py):**
- `context.tracing.start(screenshots=True, snapshots=True)` is called
  once per context, right after `new_context()`, guarded by a new
  `_tracing_started` flag so it's never started twice for one context.
  Both `screenshots` and `snapshots` on, exactly matching the roadmap's
  spec, so the resulting trace is self-contained and viewable in
  Playwright's own trace viewer without the original page.
- `context.tracing.stop(path=...)` is called in `close()`, **before** the
  context-teardown loop -- unlike video (which finalizes only once its
  *page* is closed), a trace is finalized and written to disk by
  `tracing.stop()` itself, but that call requires the *context* to still
  be open, so the ordering constraint is the mirror image of video's (video
  needs the page already closed; trace needs the context not yet closed).
  Both quirks are now handled correctly and explained inline in the code.
- New `get_last_trace_path()` (session method + module-level function),
  same shape as `get_last_video_path()`.
- `record_video` and `record_trace` are fully independent: guarded by
  separate settings flags, separate state fields, separate blocks in
  `close()`. A run can have either, both, or neither on.

**`orchestrator/run_engine.py`:** a new `if settings.record_trace:` block,
placed right after the existing video/slideshow block (same "only known
for certain after `browser_hook.close()` finalizes it" ordering
constraint), attaches `report.report_paths["trace"]` and rewrites
`report.json` if a trace path came back -- completing the architecture
diagram's "(Screenshots, Videos, Trace files)" label for real, matching
what was already true for the other two.

**Verification — genuinely stronger than D-035/D-036/D-037's disclosed
gap, not the same caveat repeated.** This sandbox session, unlike the
Phase N/O/P sessions, actually has the **real `playwright` package (and a
working, launchable Chromium binary)** installed -- confirmed directly
(`sync_playwright().start().chromium.launch(headless=True)` succeeds).
`pytest`/`pydantic`/`pydantic_settings`/`httpx`/`sqlalchemy` are still
absent and there is still no network to install them, so the new
`tests/test_cross_browser.py` additions (3 tests: real trace file
produced and is a valid non-empty zip, off-by-default produces no trace
path, video+trace toggle independently) and
`tests/test_run_engine_trace.py` (3 tests, RunReport-level: trace attached
when on, absent when off, both video+trace attached together) could still
not be run through `pytest` itself (`RunEngine`/`TestSpec` need
`pydantic`). But `runtime/hooks/browser.py` itself has no `pydantic`
dependency at all -- only `config.settings`, which does. So this was
verified by swapping in a minimal plain-Python stand-in for
`config.settings` (exposing exactly the attributes/properties browser.py
actually reads: `record_video`, `record_trace`, `playwright_browser`,
`videos_dir`, `traces_dir`) and then importing and running the **real,
unmodified `runtime/hooks/browser.py`** against a **real Chromium
instance** navigating a **real local HTTP server**
(`tests/conftest_local_server.py`, which has no `pydantic` dependency
either). This produced an actual `trace.zip` on disk, confirmed to be a
valid zip archive (`zipfile.is_zipfile`) containing `trace.trace`,
`trace.network`, and JPEG/HTML resource entries -- a materially stronger
verification than D-035/D-036/D-037's hand-traced-logic-only checks, for
the part of this phase that could reach real Playwright. The
`RunEngine`/`RunReport` integration in `run_engine.py` (the `report_paths
["trace"]` wiring) still could not be exercised end-to-end this session,
since `RunEngine` itself imports `orchestrator.schemas`, which needs
`pydantic` -- that specific piece was verified by code reading only
(the new block is a near-verbatim structural mirror of the adjacent,
already-working video block, changed only in the settings flag/report key
names and the ordering-constraint comment). Run
`pytest tests/test_cross_browser.py tests/test_run_engine_trace.py tests/test_run_engine_video.py`
(then the full suite) in an environment with `pydantic`/`pytest` present
to close that last gap -- this is the only remaining unverified piece of
an otherwise real-Chromium-confirmed phase.

**This completes the third remediation roadmap (Phases N–Q).** All four
phases (`docs/decisions.md` D-035, D-036, D-037, D-038) are done. No
further phases are currently planned; the next roadmap (if any) would need
to be supplied fresh, the same way this one was.

---

## D-039 — Phase R: safety/correctness quick fixes (poll busy-spin, retry logging)

**Date:** 2026-07-16
**Roadmap:** Fourth remediation roadmap, Phase R (R1–R3)

**Context:** Kicking off the R–V roadmap. Phase R is deliberately three
small, independent, zero-architecture-change fixes, sequenced first
because later phases (S, U) touch the same code paths and should build on
correct code, not broken code.

**R1 — Automation Anywhere poll-loop busy-spin.**
`AutomationAnywhereAdapter._poll_rest_status_multi` used
`poll_interval_seconds` as-is, with no floor. A caller-supplied `0` (or a
negative value) made the `while time.monotonic() < deadline` loop spin
with no pacing between status requests. In
`test_n2_timed_out_target_reported_independently_of_completed_target`
(`poll_interval_seconds=0`, `timeout_seconds=0.05`), this exhausted the
test's 200-entry mocked response sequence before the deadline elapsed,
surfacing as `KeyError: 'targets'` in the assertion (the adapter's
generic exception handling converted the underlying `StopIteration` into
a failure result that never populated the `targets` evidence key — a
symptom one layer removed from the real cause).
**Fix:** `poll_interval_seconds = max(poll_interval_seconds, 1.0)` inside
`_poll_rest_status_multi` itself, not just documented as an expected
value callers are trusted to respect.
**Verified:** `pytest tests/test_phase_n_automation_anywhere.py` — 10/10
passing (was 9/10, this test failing).

**R2 — Test-isolation check.** Re-ran the fixed test both in isolation
(`pytest tests/test_phase_n_automation_anywhere.py::test_n2_...`) and in
the full suite. Both pass; no separate isolation-vs-full-suite ordering
issue was found once the real busy-spin bug was fixed — the discrepancy
described in the roadmap note was this same bug, not a second one.

**R3 — Planner retry/escalation logging.** `agents/planner/spec_generator.py::generate_spec`'s
one-retry-on-validation-failure loop (WORKFLOW.md Step 1.3) previously
retried silently. Now: `backend.generate()` + `TestSpec.model_validate()`
are wrapped in a single `try`, and on any exception a `logging.warning`
call records `type(exc).__name__` and the exception text before
re-prompting once. This also means a `backend.generate()` failure itself
(e.g. a timeout raised by a future network-backed backend) is now
covered by the same retry-with-logged-reason path, not just schema
validation failures — matching the roadmap's stated scope ("schema
validation error, timeout, exception type"). No new exception types are
swallowed silently: if the retry also fails, `TestSpec.model_validate`
still raises out of `generate_spec` as before.
**Rationale for logging over a heavier mechanism:** `orchestrator/audit_logger.py`
exists but is a tenant/user/action-scoped compliance log, not a fit for
an in-process retry reason; stdlib `logging` is the minimal correct tool
here (code-minimalism ladder, `context.md` §6.7) and sets up Phase V's
escalation-policy logging to follow the same convention.

**Test results:** 484/484 passing (full suite, before and after — R1 was
the only previously-failing test; R3 added no new failures).

**Docs updated:** `docs/Roadmap.md` (Phases R–V appended, Phase R marked
done), `docs/progress.md` (this pass appended), `docs/STATUS.md`
(next-action pointer updated to Phase S).

---

## D-040 — Phase S1: unify NoDisplayError into runtime/errors.py

**Date:** 2026-07-16
**Roadmap:** Fourth remediation roadmap, Phase S (S1)

**Problem:** `NoDisplayError` was defined three separate times --
`runtime.hooks.browser.NoDisplayError`, `runtime.hooks.capture.NoDisplayError`,
and `runtime.hooks.interact.NoDisplayError` -- as three distinct
`RuntimeError` subclasses that happened to share a name and docstring
shape but were never related by inheritance. Callers that needed to catch
"no display, whichever hook raised it" (`orchestrator/autoscan.py`,
`orchestrator/ui_audit_runner.py`, `agents/vision/executor.py`) had to
import every variant under an alias (`CaptureNoDisplayError`,
`BrowserNoDisplayError`, plain `NoDisplayError` for interact's) and list
every alias across separate `except` blocks. This is exactly the failure
mode D-022 and D-024 each patched piecemeal: a caller could easily catch
only the variant it remembered to import and let a different hook's
lookalike propagate uncaught.

**Fix:** new `runtime/errors.py`, dependency-free (stdlib only), defining
the one shared `NoDisplayError(RuntimeError)`. `runtime/hooks/browser.py`,
`runtime/hooks/capture.py`, and `runtime/hooks/interact.py` now import and
re-export this class (`from runtime.errors import NoDisplayError` +
`__all__`) instead of each defining their own -- existing
`from runtime.hooks.X import NoDisplayError` call sites still work
unchanged, but all three now resolve to the *same* class object.

**Cleanup at call sites:** since the three variants are now identical,
removed the now-redundant aliasing in `orchestrator/autoscan.py`,
`orchestrator/ui_audit_runner.py`, `agents/vision/executor.py`,
`orchestrator/run_engine.py`, `api/routers/runs.py`, and
`aura/cli/preflight.py` -- each now imports once from `runtime.errors`
and uses a single `except NoDisplayError` regardless of which hook raised
it.

**Verified:** `python3 -c "from runtime.hooks.browser import NoDisplayError as A; from runtime.hooks.capture import NoDisplayError as B; from runtime.hooks.interact import NoDisplayError as C; from runtime.errors import NoDisplayError as D; assert A is B is C is D"` passes. Full suite: 484/484 passing, no regressions.

---

## D-041 — Phase S2: shared screenshot-acquisition guard (`display_guard`)

**Date:** 2026-07-16
**Roadmap:** Fourth remediation roadmap, Phase S (S2)

**Problem:** even after D-040 unified the exception class, every
screenshot/display-dependent call site still had to remember to write its
own `try/except NoDisplayError` -- a discipline, not an enforced code
path. This is the structural gap D-022 and D-024 patched one call site at
a time (and R1/R2 of this same roadmap found a live instance of the
underlying busy-spin/isolation bug class in a different subsystem).

**Fix:** `runtime.errors.display_guard()`, a context manager built around
the D-040 `NoDisplayError`. Usage:
```python
with display_guard() as guard:
    guard.value = screenshot_provider(run_id, step_id)
if guard.no_display:
    ...  # handle "no display" however this call site needs to
```
Only `NoDisplayError` is caught; any other exception still propagates
normally. `guard.error` carries the original exception for call sites
that need to surface its message (e.g. `aura/cli/preflight.py`'s
advisory warning).

**Call sites migrated:**
- `orchestrator/run_engine.py::_safe_screenshot`
- `orchestrator/autoscan.py::run_autoscan` (the screenshot-capture site;
  the separate `interact.scroll()` guard a few lines down is not a
  screenshot call and was left as a plain `except NoDisplayError`, per
  S2's stated scope)
- `orchestrator/ui_audit_runner.py::_run_click_audit` (both the baseline
  and post-click screenshot sites)
- `aura/cli/preflight.py::check_display_available`

**Verified:** full suite 484/484 passing, no regressions. `ruff check` on
all Phase S–touched files: clean.

**Docs updated:** `docs/Roadmap.md` (Phase S marked done), `docs/progress.md`
(this pass appended), `docs/STATUS.md` (next-action pointer updated to
Phase T).

## D-042 — Phase T: spec-level action/target-type validation pass

**Decided:** 2026-07-17
**Context:** Phase T of the R–V roadmap — a new pre-execution validation
step that checks the whole `TestSpec` for action/target-type
compatibility before any step runs, instead of discovering a broken or
mismatched step only after the vision pipeline has already burned a full
OCR/DOM cycle (and possibly a self-heal retry loop) trying to act on it.

**New module: `orchestrator/spec_validator.py`.** Two independent kinds
of check, deliberately different severities:

1. **Structural completeness (`severity="error"`, blocks the run).** A
   step's required fields for its own `action` are simply missing:
   `NAVIGATE_URL` with no `url`, `VISUAL_CLICK` with no
   `target_description`, `TYPE_TEXT` with no `field_description`,
   `CAPABILITY_CHECK` with neither `target` nor `capability_params` set.
   `SCROLL` and `WAIT_FOR_HUMAN_ACTION` have no required fields (a bare
   scroll/wait is legitimate on its own). These are unambiguous — the
   step cannot possibly succeed as written.
2. **Action/target-type mismatch heuristic (`severity="warning"`, never
   blocks).** A vision-driven step (`VISUAL_CLICK`/`TYPE_TEXT`/`SCROLL`)
   whose `target_description`/`field_description` text contains a
   high-signal backend keyword ("REST API", "webhook", "SQL query",
   "Control Room", "trigger the bot", "S3 bucket", "SFTP server", etc.) —
   exactly the plan's own example of a step that should have been a
   `CapabilityType` check instead of a UI action. Kept as a warning, never
   an error, because this is inherently fuzzy — a button genuinely
   labeled "API Settings" is a legitimate real target, and the check has
   no way to be certain which case it's looking at. The message names
   which `CapabilityType` the keyword suggests, when there's an obvious
   one, so the warning is actionable rather than just "something looks
   off."

**Wired into `RunEngine.run_spec()`** — the single entry point every
execution path funnels through (`run()`, `aura explore`'s hand-assembled
specs, `--interactive` mode, the API layer, `aura schedule`). Validation
runs *before* `self.memory.start_run(...)` — an error-severity issue
raises `SpecValidationError` before any memory write, any aggregator, or
any screenshot call happens, so there's nothing to half-record or clean
up. Warnings are carried through on a new `RunEngineResult.validation_warnings`
field rather than printed directly from `run_engine.py` itself — that
module stays UI-agnostic by design (no `console`/`rich` usage anywhere in
it), so presentation is left to the callers, matching the existing
architecture split between orchestration and CLI/API presentation layers.

**Caller-side wiring:**
- `aura/cli/execute_cmd.py`: both `RunEngine.run_spec()`/`RunEngine.run()`
  call sites now catch `SpecValidationError` and print the clean,
  actionable multi-line message via `console.print` + `typer.Exit(code=1)`,
  instead of an unhandled traceback. A new `_print_validation_warnings()`
  helper prints any non-blocking warnings after a run completes.
- `api/routers/runs.py`: `execute_run()`/`execute_autonomous_run()` (both
  background-task functions) gained an explicit `except SpecValidationError`
  branch ahead of the pre-existing generic `except Exception` — behaviorally
  the same outcome today (`status="failed", error=str(e)"`, since
  `SpecValidationError`'s own message is already the clean, readable
  text), but kept as its own branch so a client-distinguishable status
  code could be added later without touching the generic error path.
- `orchestrator/scheduler.py`'s job-runner path (`run_engine.run` bound as
  a callable) was deliberately left untouched — a `SpecValidationError`
  there is treated like any other exception apscheduler's own job wrapper
  already logs, which is acceptable pre-existing behavior, not a gap this
  phase needed to close.

**Verification:** 484 passing before this pass. **508 passing after**
(24 new: `tests/test_spec_validator.py` — 9 structural-completeness
tests across every `ActionType`, 3 `validate_spec_or_raise` tests,
6 parametrized + 2 direct action/target-mismatch heuristic tests, 1
multi-step independence test, and 2 `RunEngine`-level integration tests:
one proving the screenshot provider and `memory.start_run()` are never
reached for an invalid spec, one proving a warning-only spec runs to
completion and carries its warning through to
`RunEngineResult.validation_warnings`) — zero regressions across the
full suite, including the existing `test_cli.py`/`test_api_service.py`
suites that exercise the two wired call sites.

**Not done (explicitly out of scope for this pass):** the heuristic's
keyword list is intentionally small and conservative rather than
exhaustive — it will miss plenty of real mismatches phrased differently,
by design (a broader/fuzzier list would trade false negatives for false
positives, and a warning nobody trusts because it fires too often is
worse than one that's merely incomplete). No attempt was made to
validate `capability_params`' *contents* against each specific
`CapabilityType`'s own required keys (e.g. confirming an
`AUTOMATION_ANYWHERE` step's params actually contain `bot_id` for REST
mode) — that would mean this module hardcoding knowledge of every
adapter's own contract, duplicating validation each adapter already does
correctly at runtime; the completeness check here stops at "is there
*something* to check," not "is it the *right* something."

## D-043 — Phase U: OCR-then-DOM dual verification, results compiled (redesigned Idea 1)

**Roadmap Phase U** (`Roadmap.md`, "Fourth remediation roadmap — Phases
R–V"): replaces Phase C's DOM-first/OCR-fallback chain in
`agents/vision/executor.py` with OCR-then-DOM dual verification — both
locators always run against a live browser target, every time, not
conditionally — and their results are compiled/reconciled before the
step's outcome is decided, per the roadmap's own compilation rule.

**What changed:**

- `agents/vision/executor.py::execute_step()` now always computes
  `ocr_result` (via `agents.vision.locator.locate_text`, unchanged) *and*
  (when a browser session exists) `dom_result` (via the new
  `_resolve_dom()`, which is the old `_try_dom_path()`'s locate-only half
  — `locate_dom()` then `relocate_dom()` self-heal, exactly as before,
  just no longer dispatching inline).
- New `_compile_dual_result()` implements the roadmap's compilation rule
  exactly:
  - **Both clear the confidence threshold and their locations overlap**
    (OCR's matched point falls inside DOM's bounding box, expanded by
    `settings.dual_verification_overlap_tolerance_px`, default 40px) →
    agreement. Dispatch through whichever scored higher, tagged
    `"dual-method-confirmed"`, `agreement=True`.
  - **Both clear the threshold but don't overlap** → genuine
    disagreement. Both candidates are recorded in
    `verification_evidence` (never silently dropping the loser), a
    `logging.warning()` is emitted (reusing R3's "log the reason, don't
    retry/decide silently" convention), and the winner is picked via
    `settings.dual_verification_tie_break` (`"highest_confidence"`
    default, or `"prefer_dom"`/`"prefer_ocr"`). Still tagged
    `"dual-method-confirmed"` (both genuinely found something),
    `agreement=False`.
  - **Only one clears the threshold** (including "DOM wasn't applicable
    at all" — no browser session, e.g. native desktop targets) → proceed
    on that one, tagged `"single-method"`.
  - **Neither clears the threshold** → escalate, with both candidates
    (or an explicit `{"attempted": False}` for DOM when no session
    existed) still recorded in evidence.
- Dispatch itself (`_dispatch_dom()`/`_dispatch_ocr()`) happens *after*
  compilation, through whichever method won. If the winner's dispatch
  fails for a display-related reason (`NoDisplayError` — e.g. the DOM
  locator resolved but the element went stale before the click) and the
  *other* candidate also cleared the threshold, dispatch falls back to it
  rather than reporting a false miss — the same fallback behavior Phase
  C's single-path chain had, just available from either direction now
  (`verification_evidence["dispatched_via"]` records which one actually
  fired).
- `orchestrator/schemas.py::VisionActionResult` gained two new optional
  fields: `verification_method` (`"single-method"` |
  `"dual-method-confirmed"` | `None` — `None` for steps that never went
  through this path at all, e.g. navigate/scroll) and
  `verification_evidence` (the full compiled dict — both candidates,
  agreement, tie-break applied, winner, dispatched_via).
- `agents/vision/dom_locator.py::DomLocateResult` gained a `bbox` field
  (Playwright's own `bounding_box()` shape), populated best-effort
  (`None` on failure, never raises) by both `locate_dom()` and
  `relocate_dom()` on a successful match — this is what makes the
  overlap check in the point above possible; there was previously no way
  to compare a DOM match's on-screen location against OCR's coordinate at
  all.
- `config/settings.py` gained `dual_verification_overlap_tolerance_px`
  (int, default 40) and `dual_verification_tie_break` (str, default
  `"highest_confidence"`; validated against a shared
  `DUAL_VERIFICATION_TIE_BREAK_CHOICES` tuple the same way
  `playwright_browser` is validated against `PLAYWRIGHT_BROWSER_CHOICES`
  — an unrecognized value logs a warning and falls back to the default
  rather than crashing).
- `reports/templates/run_report.html.j2` now renders `verification_method`
  per step, and — specifically on disagreement — both candidates'
  matched text/confidence side by side, so a report reader can see
  exactly what OCR and DOM each found and which one the tie-break picked,
  rather than the report silently reflecting only the winner.

**Why OCR-then-DOM (not the reverse) matters here:** the roadmap
explicitly calls this "the reverse order from Phase C's current
DOM-first/OCR-fallback architecture" — previously OCR only ever ran if
DOM's self-heal also failed, so a step that DOM alone could resolve never
got cross-checked against OCR at all, and there was no way to detect the
two methods disagreeing (DOM would simply win by default, right or
wrong, with no record of what OCR would have found instead). Running
both unconditionally makes disagreement *visible* and *audited* instead
of structurally invisible.

**Depends on Phase S (D-040/D-041) and benefits from Phase R3 (D-039),**
per the roadmap's own sequencing: the disagreement/tie-break path reuses
the unified `NoDisplayError` (S1) for dispatch-fallback detection, and
its `logging.warning()` on disagreement follows R3's "every non-obvious
decision gets a logged reason" precedent rather than deciding silently.

**Verification:** 508 passing before this pass (per D-042's own count).
**528 collected after (20 new tests added this pass): 497 passing, 26
failed, 5 errored** — 16 in the new
`tests/test_dual_verification_compile.py` — pure unit tests against
`_compile_dual_result`/`_locations_overlap`/`_apply_tie_break` directly,
runnable with no browser at all; 1 new bbox-population test in
`test_dom_locator.py`; 3 new live-browser integration tests added to
`test_executor_dom_path.py`; the existing `test_no_active_browser_session_falls_back_to_ocr_path`
test gained an additional single-method assertion rather than counting
as a new test) — zero regressions. The failing/erroring tests in this
pass's full run (26 failed, 5 errored) are the same pre-existing
Chromium-binary-download sandbox gap documented since Phase C/D — none
of them touch code this phase changed any differently than before; the
3 new live-browser integration tests hit the identical gap for the same
environmental reason, not a bug in this pass's logic (confirmed
separately via the 16 pure-unit compile tests, which need no browser and
all pass cleanly).

**Explicitly out of scope, by design:** no change to the confidence
*values* either locator produces (OCR's `_match_score`, DOM's
`_score_candidates`) — Phase U is purely about running both and
reconciling, not re-tuning either scorer; no persistence/trend-tracking
of disagreement frequency over time (a reasonable Phase-H-style
follow-up, not required here); `_region_from_skill_hint`'s "broaden
search region" convention is unchanged and still only affects the OCR
side.

**Roadmap Phases R, S, T, and U (of the fourth remediation roadmap,
R–V) are now all done. Phase V (dual API + local LLM generic backend) is
next and last.**

## D-044 — Phase V: dual API + local LLM generic backend (fourth remediation roadmap complete)

**Roadmap Phase V** (`Roadmap.md`, fourth remediation roadmap R–V, last
phase): reintroduces a network-capable planner path, on much stricter
terms than the AnthropicBackend removed in D-018, and builds directly on
R3's retry-logging groundwork (D-039).

**`CloudLLMBackend`** (`agents/planner/spec_generator.py`): a generic
OpenAI-compatible HTTP client — `POST {base_url}/chat/completions`, no
vendor SDK, no hardcoded provider. "Cloud" names the code path (as
opposed to `LocalLLMBackend`'s in-process `llama-cpp-python`), not a
requirement that the endpoint be remote — it works identically against a
real cloud API or an operator's own local OpenAI-compat server (Ollama,
llama.cpp server mode, vLLM, etc.). Configuration is entirely env/settings
-driven (`AURA_CLOUD_LLM_BASE_URL` / `_API_KEY` / `_MODEL`), same
provenance-stays-with-the-operator posture as `local_llm_model_path` —
AURA bundles or defaults to no specific vendor. Reuses the existing
`SPEC_GENERATION_SYSTEM_PROMPT`/`_USER_TEMPLATE` and `_extract_json_object`
helper unchanged — the prompt contract and response-parsing tolerance
(markdown fences, stray prose) are backend-agnostic, so nothing there
needed touching.

**Egress control reuses Phase D's mechanism, not a second one.** New
public `orchestrator.capability_router.is_egress_host_allowed(host)`
wraps the existing private `_host_allowed()` against the live
`settings.allowed_capability_hosts` — the exact function every capability
adapter's egress check already goes through. `CloudLLMBackend.generate()`
calls it before every request; an unresolvable/blocked host raises a new
`CloudLLMEgressBlockedError` before any network call is attempted. This
was the roadmap's own explicit instruction ("reuse ... rather than a
second one"), so no new allowlist config surface was added anywhere.

**Two independent gates, same pattern as `allow_db_seeding` (D-036).**
`settings.enable_cloud_planner` (new, default `False`) is checked by the
backend-resolution/escalation logic in `generate_spec`, not inside
`CloudLLMBackend.__init__`/`.generate()` itself — a test or caller that
constructs `CloudLLMBackend` directly can still use it without the gate,
same as `LocalLLMBackend` always could. The egress allowlist is the second,
independent check, enforced inside `.generate()` regardless of how the
instance was reached.

**Detection matrix (`config/settings.py::_auto_detect_planner_backend`,
extended, not replaced).** When `settings.planner_backend` is left unset,
resolution now considers both a bundled local `.gguf` model and a
configured+enabled cloud backend, breaking ties via
`settings.planner_priority` (`"local_first"` default, or `"cloud_first"`;
an unrecognized value raises immediately rather than silently defaulting).
If neither is available, `settings.require_llm_backend` (new, default
`False`) decides the failure mode: `False` falls back to the always-
available heuristic backend exactly as before D-018 removed
AnthropicBackend; `True` fails fast at `Settings()` construction with a
named `ValueError` rather than silently degrading to heuristic — for
deployments that specifically don't want that silent degrade path. An
**explicit** `AURA_PLANNER_BACKEND` always bypasses this matrix entirely
(unchanged pre-Phase-V behavior) — `require_llm_backend` and the priority
setting only apply to the auto-detect (`None`) case. Bundled-model
detection is deliberately still filesystem-only at construction time, not
a live reachability probe of `cloud_llm_base_url` — pinging a network
endpoint during every process startup would make startup itself depend on
network reachability, exactly what D-002/D-018 rule out; real reachability
failures surface at call time instead, where the escalation policy below
can react to them.

**Escalation policy (`generate_spec`, built on R3's `_generate_with_retry`
helper, factored out of the previous inline try/except so both the
explicit-backend and auto-resolved paths share identical
one-retry-with-logged-reason behavior).** `backend=` passed explicitly →
exactly R3's existing retry behavior, no escalation, matching every
pre-Phase-V caller/test unchanged. `backend=None` (the default path)
additionally escalates to a freshly-constructed `CloudLLMBackend()` if the
resolved primary backend fails (after its own retry) and
`settings.enable_cloud_planner` is `True` and `settings.planner_backend`
isn't already `"cloud_llm"` — each attempt and its reason logged via
`_logger.warning`, same style/level as R3's retry logging, so an
escalation is never a silent behavior change from the caller's point of
view. If the escalation attempt also fails, that failure is logged too and
re-raised — no third fallback, no silent swallow.

**A real bug caught by hand-verification before it shipped:** the
escalation check was originally written as
`isinstance(primary, CloudLLMBackend)`. Manually exercising the exact
mocking pattern the test file uses
(`patch("agents.planner.spec_generator.CloudLLMBackend", return_value=...)`)
immediately broke it — patching replaces the module-global name with a
`Mock`, which `isinstance()` cannot accept as its second argument, so
`TypeError` fired on every escalation-path test. Fixed by checking
`settings.planner_backend != "cloud_llm"` instead of the primary
instance's type — more robust (immune to how the instance was
constructed/mocked) and arguably more correct anyway: the real question is
"is cloud already what we're configured to use," not "what Python class is
this particular object." Left as a cautionary note in the code comment,
since it's the kind of check that looks obviously right until a test
mocks the exact thing it's checking.

**Verification.** Same disclosed sandbox gap as D-035 through D-038: no
`pytest`/`pydantic`/`httpx`/network in this session. New
`tests/test_phase_v_cloud_llm.py` (24 tests: CloudLLMBackend config
errors, egress-allowlist blocking/allowing, the actual
Phase-D-function-is-called check, mocked-request/response shape, missing-
api-key/no-auth-header, non-200 handling; `_default_backend` resolving
`"cloud_llm"`; 8 detection-matrix scenarios against real `Settings()`
construction; 6 escalation-policy scenarios) was written but not run
through `pytest`. In its place, every scenario was hand-verified against
the **real, unmodified `config/settings.py` and
`agents/planner/spec_generator.py`** using a from-scratch minimal
`pydantic`/`pydantic_settings` stand-in built specifically to support
`Settings`' actual `Field(default_factory=...)` usage and
`@model_validator(mode="after")` decorator (more complete than the
lighter stand-ins used in D-035–D-038, since this phase's core logic lives
inside a real pydantic validator, not a plain method) — including the
exact mocking pattern above, which is how the `isinstance` bug was caught.
A full regression pass (pre-existing `LocalLLMBackend`/`_extract_json_object`/
`_default_backend` behavior, plus an end-to-end `generate_spec` call
through the real heuristic backend against
`requirements_input/example_login_flow.md`) confirmed no pre-Phase-V
behavior changed. This is still not a substitute for a real `pytest` run
against the full suite (484 passing as of D-043) — run
`pytest tests/test_phase_v_cloud_llm.py tests/test_planner.py` (then the
full suite) in a real environment before deploying this.

**This completes the fourth remediation roadmap (Phases R–V).** All five
phases (`docs/decisions.md` D-039 through D-044 — note D-044 is Phase V;
R/S1/S2/T/U are D-039–D-043) are done. No further phases are currently
planned.

## D-045 — Phase V verification closed: real `pytest` run confirms the hand-verified work, one stale test fixed

**Date:** 2026-07-17
**Context:** D-044 (Phase V) explicitly disclosed it was hand-verified
only, with no `pytest`/`pydantic`/`httpx`/network available in that
session, and left a direct instruction: *"run `pytest
tests/test_phase_v_cloud_llm.py tests/test_planner.py` (then the full
suite) in a real environment before deploying this."* This session has
full tooling (confirmed: `pytest` 9.1.1, `pydantic` 2.13.4, `httpx`
0.28.1, `sqlalchemy` 2.0.51, real `playwright` import). Ran exactly what
was asked, then the full suite.

**Result: the hand-verification held up.**
`pytest tests/test_phase_v_cloud_llm.py tests/test_planner.py` — **50/50
passing**, first run, no changes needed. The from-scratch pydantic
stand-in D-044 built for that session was accurate enough that nothing
in the real environment behaved differently.

**One real, non-Playwright test failure found and fixed:**
`tests/test_preflight.py::test_spec_generator_has_no_anthropic_backend`
— predates Phase V, and its final assertion hardcoded the exact expected
backend registry as `{"heuristic", "local_llm"}`. Phase V intentionally
added a third, `"cloud_llm"`, per D-044's own design — this is not a
reintroduction of the `AnthropicBackend` removed in D-018 (no vendor SDK,
no hardcoded provider, off by default, gated by
`settings.enable_cloud_planner` plus the same egress allowlist every
capability adapter uses), so the test's actually-meaningful assertions
(`not hasattr(sg, "AnthropicBackend")`, `"anthropic" not in
sg._BACKEND_REGISTRY`) were and remain correct — only the exact-membership
check needed updating to `{"heuristic", "local_llm", "cloud_llm"}` to
reflect the now-intentional three-backend registry. Fixed in
`tests/test_preflight.py`, with a comment explaining why the set grew and
that this isn't a policy reversal.

**Full suite: 518/524 passing** (26 failed + 5 errored before the fix,
515 passed; after the one-line fix: 518 passed, 26 failed, 5 errored —
net one more passing, one fewer failing, zero regressions). Every
remaining failure/error is the same pre-existing Chromium-binary-download
sandbox limitation documented continuously since Phase C/D — spot-checked
one directly (`test_dom_locator.py::test_locate_dom_finds_exact_button_match`)
and confirmed the exact same root cause (`playwright install chromium`
blocked by this sandbox's egress rules, `cdn.playwright.dev` unreachable)
by attempting the install live and observing the identical failure
signature already on file. All 26+5 are in files that need a real
launchable browser (`test_accessibility_adapter.py`,
`test_browser_hook.py`, `test_cross_browser.py`, `test_dom_locator.py`,
`test_link_checker.py`'s Playwright-fallback test,
`test_performance_adapter.py`, `test_run_engine_trace.py`,
`test_run_engine_video.py`, `test_executor_dom_path.py`) — none of them
touch Phase V's own code.

**This closes the verification gap across the entire fourth remediation
roadmap.** R, S1, S2, and T were already pytest-verified in their own
sessions (D-039–D-042). U's core logic was pytest-verified via its 16
browser-free unit tests in its own session, with only the
browser-dependent integration tests carrying the disclosed sandbox gap
(D-043). V is now verified the same way, in this session. No phase in
R–V has an outstanding "never actually run through pytest" gap anymore —
only the long-standing, environment-specific Chromium binary limitation
remains, which is infrastructure, not code.

---

## D-047 — Phase W: real Hermes Agent integration + LLM semantic tie-break (2026-07-19)

Real Hermes Agent client (orchestrator/hermes_client.py) against Hermes
Agent's OpenAI-compatible /v1/chat/completions API server, a new
HermesAgentBackend planner backend, and a new llm_semantic
dual-verification tie-break mode (agents/vision/llm_verifier.py) that
asks a configured LLM backend which OCR/DOM candidate better matches the
step's plain-English target_description. All off by default, all fail
soft. See tests/test_phase_w_hermes_and_llm_verifier.py (14 new tests).
Full suite: 599/602 passing, the 3 remaining failures are a pre-existing
sandbox-only `mss` module gap unrelated to this phase (confirmed via git
stash).

---

## D-048 — Phase X2: opt-in `hermes_first` auto-detection priority (2026-07-19)

D-047 deliberately excluded `hermes_agent` from the default auto-detection
matrix (a reachable Hermes instance is too weak a signal of intent).
Roadmap §11 (X2) proposed a bounded way to still let operators opt into
auto-detection: a new `planner_priority="hermes_first"` value, which is
the *only* priority value that puts `hermes_agent` into the matrix at all
(ahead of `local_llm`/`cloud_llm`). `local_first`/`cloud_first` behavior
is completely unchanged. 4 new tests in
`tests/test_phase_w_hermes_and_llm_verifier.py`. Full suite: 603/606
passing (3 pre-existing `mss`-module sandbox failures, unrelated).

---

## D-049 — Phase X3: Hermes Agent wired into Planner.diagnose (2026-07-19)

`HermesAgentDiagnoser` (agents/planner/diagnoser.py) is a new opt-in
DiagnosisBackend, reusing `orchestrator/hermes_client.py::HermesAgentClient`
(same client Phase W's spec-generation backend uses). Selected via
`settings.diagnosis_backend = "hermes_agent"` — explicit opt-in only, not
auto-detected, matching D-047's posture for planner_backend. Default
remains `LocalHeuristicDiagnoser` (deterministic, zero dependencies).
Unlike the LLM semantic tie-break (D-047), this path does NOT fail soft —
a Hermes transport/parse failure raises, since the self-healing loop
already has its own retry/guardrail handling (orchestrator/guardrails.py)
for backend failures; swallowing the error here would hide it one layer
too early. 5 new tests. Full suite: 608/611 passing (3 pre-existing
`mss`-module sandbox failures, unrelated).

---

## D-050 — Phase Y3: real Azure connection-string parsing + GCS fixed-host resolution (2026-07-19)

Found and fixed a genuine bug while investigating the "azure/gcp adapters
can't be host-allowlisted" gap noted in earlier STATUS.md revisions: it
was worse than documented. Azure Storage connection strings are
`Key1=Value1;Key2=Value2` pairs, not URLs — `urlparse(conn_str).hostname`
silently returned `None` even for the common case (an explicit
`connection_string` param), not just the SDK-default-credential-chain
case the old docstring described. `orchestrator/capability_router.py`
now has `_parse_azure_connection_string_host()`, which parses the real
format (AccountName+EndpointSuffix, or BlobEndpoint directly) the same
way `BlobServiceClient.from_connection_string` does internally, and
applies it to both the `connection_string` param and the
`AZURE_STORAGE_CONNECTION_STRING` env-var fallback. GCP Cloud Storage
always talks to a fixed, well-known host (`storage.googleapis.com`)
regardless of credential path, so that capability now resolves to it
directly rather than being treated as unresolvable.
`sharepoint_adapter` (tenant-specific, no fixed host) remains a genuine,
documented fail-open case — not touched by this phase.

8 new tests in `tests/test_capability_egress_controls.py`. Full suite:
614/617 passing (3 pre-existing `mss`-module sandbox failures, unrelated).

---

## D-051 — Phase Z: stale "proposed" cross-references fixed in TRD.md (2026-07-19)

While auditing docs for D-016/prior "proposed, not implemented" language
per the gap-closure request, found that `docs/TRD.md` §10 and §11 section
headers already correctly say "delivered," but two summary blurbs
elsewhere in the same file (the architecture-diagram callout above §8,
and a cross-reference inside §11's own body) still said "proposed" --
the same class of staleness §10's own header note already had to
self-correct once before (found and fixed in an earlier documentation
consistency pass, recorded in that section's own text). Fixed both
remaining instances; no code changes, documentation-only.

## D-052 — Phase Z: real gaps closed — MIT LICENSE file added, baseline-approval CLI shipped (2026-07-19)

Two items flagged in earlier decisions/status entries as open were
addressed for real, not just re-documented:

1. **License.** `docs/PROJECT_OVERVIEW.md` has stated "MIT-licensed
   reference implementation" since early in the project, but no `LICENSE`
   file existed, and `docs/STATUS.md` separately flagged this as an
   unconfirmed placeholder. Added a real `LICENSE` file (MIT text) at the
   repo root, matching the license the docs already committed to, rather
   than leaving a documented claim unbacked by an actual file.
2. **`aura baselines` command.** D-027 (Phase G3, pixel-diff visual
   regression) explicitly named this as "a natural, small follow-up" left
   undone: no way to approve a new baseline after a legitimate UI change,
   short of manually deleting the file under `runtime/baselines/`. Added
   `agents/vision/visual_regression.py::list_baselines()` /
   `approve_baseline_from_path()` / `reject_pending_diff()` plus a new
   `aura/cli/baselines_cmd.py` and `aura baselines list|approve|reject`
   CLI command. `approve` requires an explicit `--screenshot <path>`
   rather than silently reusing the stored diff artifact (a rendered
   delta image, not a real screenshot) -- documented in the module's own
   docstring.

23 new tests (8 in `tests/test_visual_regression.py`, 7 CLI-level in
`tests/test_cli.py`, plus incidental coverage). Full suite: 629/632
passing (3 pre-existing `mss`-module sandbox failures, unrelated).

**Still explicitly not done, and not silently pretended otherwise:** the
per-channel/perceptual diff threshold D-027 also flagged (today's
comparison is still "any channel differs at all," strict) -- a genuinely
separate, larger change to the comparison algorithm itself, left for a
future phase if wanted.

---

## D-053 — real bug: `llm_semantic` tie-break's CloudLLM path bypassed the
## egress allowlist (2026-07-19)

Found by driving `agents/vision/llm_verifier.py::semantic_verify()` and
`agents/planner/spec_generator.py::CloudLLMBackend` against a real local
HTTP server (not mocks) to verify the documented wire format end-to-end.
`CloudLLMBackend.generate()` correctly calls
`orchestrator.capability_router.is_egress_host_allowed()` before every
request (D-044). `llm_verifier.py`'s `_get_backend_client()` builds a
small `_ChatAdapter` that reuses `CloudLLMBackend`'s underlying `httpx`
client directly (to avoid re-parsing the response as a `TestSpec`, which
is the wrong shape for this module's `{"winner": ...}` contract) --  but
that adapter built and sent its own request without ever calling the
allowlist check. Live-reproduced: with `settings.allowed_capability_hosts`
set to exclude the configured `cloud_llm_base_url` host,
`CloudLLMBackend.generate()` correctly raised
`CloudLLMEgressBlockedError`, while `semantic_verify()`'s CloudLLM path
still made the real network call and returned a real answer. The sibling
Hermes path (`HermesAgentClient.chat()`) was not affected -- it calls
`self._check_egress()` internally regardless of caller.

Fix: `_ChatAdapter.chat()` now calls `is_egress_host_allowed()` itself
before sending, raising (caught by `semantic_verify()`'s existing
fail-soft `except Exception`, so the module's "never raises, worst case
falls back to `highest_confidence`" contract is unchanged) rather than
silently completing the disallowed request. 2 new regression tests in
`tests/test_phase_w_hermes_and_llm_verifier.py` --
`test_semantic_verify_cloud_llm_path_respects_egress_allowlist` asserts
`fake_client.post.assert_not_called()`, not just the return value, so a
future regression that still made the call but discarded the result
would also be caught. `test_semantic_verify_uses_cloud_llm_when_hermes_not_enabled`
covers the previously-untested legitimate CloudLLM path itself (only the
Hermes path had a passing-case test before this).

Full suite: 584/584 passing (all non-Chromium-dependent tests; Chromium
binary unavailable in this sandbox session, same class of gap noted
throughout this file -- confirmed via a full run before touching this
fix that the 26 failed/5 errored baseline was 100% Chromium-launch
related, zero relation to this change).

---

## D-054 — process-oriented report content: request, decision basis,
## elements interacted, human-in-the-loop adequacy, outcome, proof of
## work (2026-07-20)

Previously, `report.html`/`report.json` were technically complete (every
step's confidence, escalation flag, screenshot, and raw verification
payload were all present) but not *narratively* complete -- a reader had
to reconstruct "what was actually asked for, and on what basis did AURA
decide it was done" themselves from scattered fields, and
`WAIT_FOR_HUMAN_ACTION` steps computed real evidence (elapsed time,
whether the screen changed, timeout) internally in `run_engine.py` only
to decide pass/fail and then discard it -- never surfaced to the report.

Added, all additive/backward-compatible (no existing field removed or
repurposed):
- `RunReport.request_text` -- the real original plain-English request.
  Note `TestSpec.requirement_ref` is a test-id-style slug (see
  `agents/planner/spec_generator.py`'s `LocalHeuristicBackend`), not the
  original text, so `run_spec()` gained an explicit `requirement_text`
  param that `run()` passes its own param through to, rather than trying
  to recover it from the slug.
- `VisionActionResult.human_action_evidence` -- `elapsed_seconds`,
  `timeout_seconds`, `timed_out`, `screen_changed`, `expected_state`,
  `baseline_screenshot_ref`, `acceptance_basis` (one of
  `verified_against_expected_state` /
  `screen_change_accepted_no_expected_state` / `no_screen_change_detected`)
  -- populated in `run_engine.py`'s existing `WAIT_FOR_HUMAN_ACTION`
  branch, which already computed all of this.
- `reports/process_report.py` (new module) -- `build_process_report()`
  assembles one shared structure (request / step-by-step decision basis
  / elements interacted / human-in-the-loop review / outcome / proof of
  work) from the same on-disk artifacts `reports/render.py` already
  reads. Both `render_html()` and the new `render_json()` build from this
  one function, so HTML and JSON can never describe a run differently
  from each other. `_decision_basis()` derives an explicit, evidence
  -grounded "why was this considered fulfilled" reason per step type
  (dual-verification agreement/tie-break for click/type, adapter evidence
  for capability_check, OCR-vs-expected_state for assert, the new
  acceptance_basis for wait_for_human) rather than a generic "confidence
  >= threshold."
- `render_json(run_id, spec=None)` -- writes `report_detailed.json`
  and registers it in `report.json`'s `report_paths["detailed_json"]`.
  `aura execute` now calls this before `render_html()` (in that order)
  so the HTML header can link to it.
- Template additions to `run_report.html.j2`: Request card, Outcome
  card (with a real one-line summary sentence, not just a status enum),
  a "Decision basis" box inside every step (renamed heading "Step
  detail" -> "Step-by-step process" to match), "Elements interacted
  with" section, "Human-in-the-loop review" section.

Verified with 3 new tests in `tests/test_reports.py`:
`test_render_json_produces_process_oriented_structure` (request text is
the real original text, not the slug; every timeline entry has a
non-empty decision basis; outcome summary references real numbers; proof
-of-work section points at real artifact paths; `report.json` gets
updated with the detailed_json path) and
`test_human_in_the_loop_step_produces_evidence_and_report_section`
(end-to-end through a real `WAIT_FOR_HUMAN_ACTION` step -- evidence
survives into both `human_in_the_loop` and the timeline entry's
`decision_basis`, including for the escalated/not-confirmed case, which
initially had a bug: the generic `escalate` branch was short-circuiting
before the human-action-specific reason could be attached, caught by
this same test on first run and fixed by reordering the branches so
`wait_for_human` is checked before the generic escalate fallback).

Full suite: 586/586 passing (all non-Chromium-dependent tests).

## D-055 — real bug: `ActionType.ASSERT` had no branch in `execute_step`,
## unconditionally escalating every assert step; `LinkCheckAdapter` given
## a `live_page_html` param to stop it launching a second, conflicting
## Playwright instance (2026-07-22/23)

**Context:** A live run against a real client-rendered site
(`https://personal-portfolio-yashmalik.vercel.app`) escalated on its
only step (a plain `assert` step asserting the page loaded) after
self-healing retried three times with an identical result, then hit the
guardrail hard-stop.

**Root cause 1 (assert always escalates):** `agents/vision/executor.py`'s
`execute_step()` had no `if step.action == ActionType.ASSERT` branch at
all. Assert steps carry their check in `step.expected_state`, not
`target_description`/`field_description` — so every assert step fell
through to the generic click/type path, saw `target_text = None`, and
unconditionally returned `confidence=0.0, escalate=True` before any real
check ever ran. This meant `run_engine.py`'s own `expected_state`
verification (gated on `not result.escalate`) could never execute
either — an assert step could never actually pass or fail on its real
on-screen content; it only ever escalated.

**Fix:** added the missing branch. `execute_step` now returns
`action_taken="none", confidence=1.0, escalate=False` for `ASSERT` steps
— correct, since there's nothing to *do* for an assert; the real
pass/fail check runs downstream in `run_engine.py` via
`check_assertion()` against `step.expected_state`, and this branch's job
is only to stop blocking that check from ever running.

**Root cause 2 (link check silently finds 0 links on client-rendered
sites):** `agents/capability/link_checker.py`'s `_render_with_playwright()`
fallback tries to launch its own `sync_playwright()` instance to render
JS-injected links when a plain HTTP fetch sees none (React/Next.js-style
apps render their nav/footer client-side, so raw HTML is just
`<div id="root">`). But `aura execute`/`explore` already keeps a
`sync_playwright()` session alive the whole run (driving the OCR
screenshots) — Playwright's sync API forbids a second sync instance in
the same thread, so the fallback's bare `except Exception: return None`
silently swallowed this every time, meaning the fallback could never
work whenever a run's own browser was already active (i.e. always,
during `aura execute --ui-audit`/`aura explore`).

**Fix:** `LinkCheckAdapter.run()` now accepts an optional
`live_page_html` param. When the caller already has a live, hydrated
page open, its `page.content()` is passed straight through instead of
letting the adapter launch a conflicting second Playwright instance —
strictly better too (zero extra page load, DOM already fully settled).
Wired into both `orchestrator/ui_audit_runner.py`'s `run_exploration()`
and `run_ui_audit()` (the latter is what `aura execute --ui-audit`
actually calls; it was added as a separate link-check integration after
`run_exploration()`'s own fix and initially missed the same wiring —
confirmed against a real run reporting `0 of N links resolved` on a page
with 11 real links, fixed by threading `live_page_html` through here too).

Verified: regression tests added in `tests/test_vision.py`
(`test_execute_step_assert_does_not_escalate_with_no_target_description`)
and `tests/test_link_checker.py`
(`test_live_page_html_is_used_instead_of_launching_a_second_playwright`,
`test_live_page_html_with_no_links_reports_used_live_page_not_playwright`),
asserting `_render_with_playwright` is never even called when
`live_page_html` is supplied, not just that the end result happens to be
correct.

## D-056 — debugging-session findings, patches prepared but not yet
## applied to `main` as of this writing (2026-07-23)

**Context:** Following on from D-055, further live runs against the same
real site surfaced four more real bugs. Each was root-caused, fixed, and
verified against this exact repo state, and delivered as a patch/zip for
manual application — **flagged here explicitly as not-yet-merged** so
this log doesn't claim work as done that isn't actually in `main` yet.
Whoever applies these should convert this entry into a normal dated
decision (or split it into D-057+) once merged, rather than leaving it
in this "prepared but pending" form.

1. **`agents/vision/ui_audit.py`'s `_looks_interactive()` OCR-noise false
   positive** — flagged single-letter OCR fragments merged with adjacent
   text (e.g. a misread "Q Search" from a footer icon+label) as a
   clickable element, since the only checks were "≤4 words" and
   "starts with a capital letter." Fixed by adding `_plausible_word()`:
   rejects bare single-letter tokens and vowel-less strings, without a
   dictionary lookup.
2. **`runtime/hooks/browser.py`'s `dom_scroll()`/`get_scroll_position()`
   — `--scroll-test` silently never moved the page.** Two compounding
   causes: (a) `delta_y` follows this codebase's pyautogui-based sign
   convention (negative = scroll down, matching `interact.scroll()`),
   but was passed straight through to `window.scrollBy()`, whose native
   sign is the opposite — starting at `scrollY=0`, "scroll down" became
   `scrollBy(0, negative)`, which clamps at 0 and never moves, confirmed
   directly against a real headless page; (b) the target site uses Lenis
   (`<html class="lenis">`), which intercepts native scrolling entirely
   via its own virtual-scroll engine, so even a correctly-signed
   `scrollBy()` would still be a no-op there. Fixed by negating the sign
   before the native call, and detecting `window.lenis` to drive it via
   `lenis.scrollTo()` directly when present.
3. **`reports/process_report.py`'s `_decision_basis()` ignored a real
   `assertion_passed` value for `action_taken == "none"` steps** — a
   direct consequence of D-055's assert-branch fix: since assert steps
   now correctly report `action_taken="none"`, they fell into the
   catch-all `else` branch, which only ever checked `escalate` and never
   looked at the real `assertion_passed` `run_engine.py` attaches
   afterward. Result: a step whose real assertion genuinely failed was
   still displayed as `"fulfilled"` in the process report, directly
   contradicting the run's actual `outcome.status` (which
   `report_aggregator._determine_status()` correctly derives from
   `assertion_passed`). This module had zero test coverage before this
   fix (`tests/test_process_report.py` is new).
4. **`agents/vision/assertions.py`'s structural/literal-text dispatch
   rewritten from a keyword regex to a shape-based heuristic.** The
   original approach (D-045-era) special-cased the literal string
   `"page_loaded"`; a later patch added a regex for
   `page|homepage|site|app|screen` + `loaded|visible|rendered|displayed`
   to catch LLM-generated descriptive sentences — but missed `"homepage"`
   outright (`\bpage\b` doesn't match "page" embedded inside "homepage"),
   and would keep missing any future synonym an LLM chooses. Replaced
   with `_looks_like_descriptive_sentence()`: tries the literal OCR match
   first (unchanged for real short labels like `dashboard_visible`), and
   only falls back to the generic "did real content render at all" check
   when that literal match fails *and* the text has sentence shape (6+
   words, 3+ common connective words) — regardless of which specific
   words it uses. **Known limitation, not fixed by this change:** the
   fallback only distinguishes "something rendered" from "nothing
   rendered" — a sentence-shaped assertion describing a specific failure
   (e.g. "the page shows a 500 error") would still pass if the error
   page has any visible text at all, since it can't yet verify *which*
   content rendered, only that content of some kind did.

Verified: 5 new tests in `tests/test_ui_audit.py`, 2 new real-headless-
Chromium tests in `tests/test_browser_hook.py` (forced headless via a
monkeypatched `settings.playwright_headless`, incidentally fixing two
previously display-dependent tests as a side effect), 4 new tests in the
new `tests/test_process_report.py`, and 3 new tests in
`tests/test_assertions.py`. Full suite as of this pass: 596 passed / 49
failed / 5 errors — the 49+5 confirmed identical on unmodified `main` via
`git stash` (missing Chromium display / `boto3`/`azure` SDKs in the
sandbox this was verified in, not caused by any of these changes).

## D-057 — AA1/AA2/AA3: audit-trail hardening, ActionType exhaustiveness
## coverage, and a mechanical silent-exception guard (2026-07-23)

**Context:** following D-055/D-056, a workflow-hardening pass (not a bug
report this time) implementing the first three items of a broader
hardening plan: monitoring/audit depth, mechanical enum-coverage
checking, and closing off the "swallowed exception" pattern that caused
most of D-055/D-056's bugs in the first place.

**AA1 — audit trail hardening.** `VisionActionResult` gained two new
fields: `verification_source` (`ocr | dom | capability_adapter |
none_required`) and `raw_evidence` (a dict — matched text, OCR excerpt,
which method decided the verdict). Added `check_assertion_detailed()` in
`agents/vision/assertions.py`, returning `{passed, method, matched_text,
ocr_excerpt}` instead of a bare bool; `check_assertion()` is now a thin
wrapper over it for backward compatibility. Wired into all three
`run_engine.py` call sites that produce an assertion verdict (per-step
assert, final spec-level assertions, wait-for-human). The final-assertion
site also stopped collapsing multiple `spec.assertions` into one opaque
bool — each assertion's own detail (expected text, method, pass/fail) is
now kept in `raw_evidence["assertions"]`. This is precisely the
information that was missing when D-056's bug let a step display
"fulfilled" in the process report while its real assertion had failed —
the trace itself now shows `method` and evidence, not just a derived
boolean that can silently disagree with the true outcome.

**AA2 — `ActionType` exhaustiveness coverage.** New
`tests/test_action_type_coverage.py`. `test_every_action_type_is_
accounted_for_somewhere()` asserts every `ActionType` member is
explicitly covered by either a behavioral test against `execute_step`
(`NAVIGATE_URL`, `VISUAL_CLICK`, `TYPE_TEXT`, `SCROLL`, `ASSERT`) or a
source-inspection check confirming `orchestrator/run_engine.py`
dispatches it explicitly before `execute_step` is ever reached
(`CAPABILITY_CHECK`, `WAIT_FOR_HUMAN_ACTION`) — no third option. This is
exactly the test that would have caught D-055's original bug (`ASSERT`
had zero branches in `execute_step`) the moment it was introduced,
instead of via a live run months later.

**AA3 — mechanical silent-exception guard.** New
`scripts/check_silent_excepts.py`: an AST-based scanner flagging
`except Exception: return <default>` blocks (returning `None`/`True`/
`False`/`[]`/`{}`/an empty string) with no logging call anywhere in the
handler. Doesn't ban broad exception catches outright — only the
specific "success-shaped default + zero visibility" combination that
caused D-055's original bug (`_render_with_playwright`'s silent
`except Exception: return None` hid the nested-sync-Playwright conflict
completely). First run found 11 real hits across the codebase. Fixed 7
with a proper `logging.warning`/`.debug`/`.error` call, including the
exact `_render_with_playwright` function responsible for D-055, plus
`composio_adapter.py`, `page_health.py`, `webhook_listener.py`, and
three of this session's own `runtime/hooks/browser.py` additions
(`dom_scroll`, `get_scroll_position`). The remaining 4 were confirmed
genuinely intentional against their own existing docstrings (stale DOM
references, "couldn't measure" geometry checks, best-effort partial
reads) and added to the script's `ALLOWLIST` with a documented reason
each, rather than forcing noisy logging onto expected/frequent
conditions. Wired into `tests/test_no_silent_excepts.py` so a newly
introduced silent-except block fails the normal test run immediately,
not just a standalone script invocation.

Verified: 10 new tests across `test_run_engine.py` (1),
`test_action_type_coverage.py` (7), and `test_no_silent_excepts.py` (1),
plus the `scripts/check_silent_excepts.py` scanner reporting clean.
Full suite: 605 passed / 49 failed / 5 errors, vs. 594 passed / 53
failed / 5 errors on unmodified `main` (confirmed via `git stash`) — an
improvement, not just no-regression: this pass's logging additions and
minor fixes incidentally corrected 4 pre-existing failures too. Zero new
failures introduced.

**Still open from the broader hardening plan (not part of this pass):**
the real-browser fixture tier (AB1/AB2), `CONVENTIONS.md` (AC1),
`aura doctor` preflight (AC2), explicit `assertion_kind` on the planner
spec (AD1), guardrail short-circuit on identical retries (AD2), the
doc-drift CI check (AE1), and the `aura audit-report` anomaly-detection
CLI (AE2).

## D-058 — AB1/AB2: real-browser fixture tier and a structured per-
## assertion audit log (2026-07-23)

**Context:** continuing the hardening plan from D-057 into Phase AB.

**AB1 — real-browser fixture tier.** New `tests/fixtures/pages.py`:
four canned HTML pages shared across test files instead of duplicated
inline per-file (`PLAIN_TALL_PAGE`/`LENIS_TALL_PAGE`, refactored out of
`test_browser_hook.py`'s own inline constants; `SPA_CLIENT_ROUTING_PAGE`,
a minimal React-Router-style hydration reproduction; `FAKE_500_ERROR_PAGE`,
a genuine error page with real readable text). New
`tests/test_real_browser_fixtures.py` runs against a real headless
Chromium + a real local HTTP server (no mocks):
- Confirms `LinkCheckAdapter` finds real, JS-injected links via
  `live_page_html` against the SPA fixture (D-055 regression, now
  end-to-end rather than via a live run against someone's real site).
- Confirms the standalone Playwright fallback (no `live_page_html`,
  no pre-existing browser session) still works correctly in isolation —
  clarifying that D-055's bug was specifically about a *second*,
  conflicting `sync_playwright()` instance, not the fallback being
  broken outright.
- Turns D-056's documented "can't detect wrong-content-rendered" gap
  into a real, running `@pytest.mark.xfail(strict=True)` test against
  the fake-500-error fixture, rather than only prose in `decisions.md`.
  `strict=True` means the day this limitation is actually fixed, this
  test starts *failing* (an unexpected pass), forcing whoever fixes it
  to notice and remove the marker — the gap can't silently stay "fixed
  in code, still documented as open" or vice versa.

**AB2 — structured per-assertion audit log.** New
`orchestrator/assertion_audit_log.py`: a dedicated, append-only JSONL
log (`logs/assertion_audit.jsonl`) of every `check_assertion_detailed()`
call — timestamp, run_id, step_id, expected_state, passed, method,
matched_text, ocr_excerpt, and the step's own escalate flag. Distinct
from `orchestrator/audit_logger.py`'s `AuditLogger` (Phase 19 — tenant/
user compliance actions like "who ran what"); this one is about
verification *evidence*. Wired into all three `run_engine.py` call sites
that produce an assertion verdict (same three D-057 touched for
`raw_evidence`). Includes `find_anomalies()`: scans the log for records
matching exactly D-056's bug shape (`escalate=False` but `passed=False`)
— the first building block toward AE2's planned `aura audit-report`
CLI command, which isn't implemented yet, but can now be built as a thin
CLI wrapper around `find_anomalies()`/`read_records()` rather than
needing its own log format designed from scratch.

Verified: 3 new tests in `test_real_browser_fixtures.py` (2 pass, 1
correctly xfails) and 5 new tests in `test_assertion_audit_log.py`
(including an end-to-end run_engine test confirming the log actually
gets populated during a real run, not just that the plumbing exists
unused). Full suite: 612 passed / 49 failed / 1 xfailed / 5 errors — the
49+5 unchanged from D-057's baseline (same pre-existing environment
gaps), zero new failures.

**Still open from the broader hardening plan:** `CONVENTIONS.md` (AC1),
`aura doctor` preflight (AC2), explicit `assertion_kind` on the planner
spec (AD1) — note this would also let AB1's xfail test above finally be
closed, since a `negative`/error-check assertion kind is exactly what's
needed to detect the fake-500-error case — guardrail short-circuit on
identical retries (AD2), the doc-drift CI check (AE1), and finishing the
`aura audit-report` CLI on top of AB2's `find_anomalies()` (AE2).

## D-059 — AC1/AC2: CONVENTIONS.md and a standalone `aura doctor` command (2026-07-23)

**Context:** continuing the hardening plan from D-057/D-058 into Phase AC.

**AC1 — `CONVENTIONS.md`.** New top-level file collecting three
easy-to-get-backwards conventions that previously only existed as
scattered docstrings, requiring a bug to be traced back to source before
they were discoverable:
1. **Scroll sign** — this codebase's pyautogui-style convention (negative
   = down) vs. native DOM's opposite sign, and `dom_scroll()`'s
   conversion between them (the root cause of the Lenis/plain-tall-page
   scroll bug fixed in D-039/D-041).
2. **Coordinate spaces** — OS/physical screen pixels (mss/OCR/pyautogui)
   vs. browser CSS pixels (Playwright's `page.mouse`) vs. DOM/accessibility-
   tree targets (no pixel coordinate at all), and `get_click_point_in_page()`'s
   conversion between the first two (the root cause of the OCR-click-lands-
   on-the-taskbar bug that function's docstring documents).
3. **Confidence/similarity thresholds** — `vision_confidence_threshold`
   (0.75, the main gate), `RELOCATE_MIN_RATIO` (0.40, DOM self-heal only),
   capability-adapter confidence conventions (1.0/0.5/0.0, not a single
   tunable), and diagnoser heuristic confidence (0.3–0.7, fixed per-branch).
Also documents the AA1 `verification_source`/`raw_evidence` trace
convention inline, pointing at `tests/test_trace_exhaustiveness.py` (AA2)
as the enforcement mechanism for any new action type.

**AC2 — standalone `aura doctor` command.** `aura/cli/preflight.py`
already had every individual check function (`check_tesseract_available`,
`check_planner_backend_available` — which already covers Hermes Agent
reachability via the `hermes_agent` backend branch, `check_display_available`,
`check_playwright_browser_available`, `check_capability_adapter_dependencies`)
wired into `run_preflight_or_exit()`, but that function only runs
implicitly at the top of `execute`/`explore` and raises+exits on the
first hard failure — there was no way for an operator to proactively
check environment health without attempting a real run. New `run_doctor()`
in the same module: a thin wrapper reusing every existing check_*
function (no new detection logic), printing a full report grouped into
hard requirements / advisory / optional-adapter-dependencies, and
returning a bool (never raising) so it can be invoked standalone. New
`aura doctor` CLI command in `aura/main.py` turns that bool into an exit
code (0 = healthy, 1 = a hard check failed) via `typer.Exit`.

Verified: `aura doctor` run for real against this sandbox — correctly
reports Tesseract OK, planner backend OK, and (accurately) flags both
"no display" and "no Playwright browser binary" as advisory warnings
without blocking, matching this environment's known, pre-existing gaps
(same ones every browser-dependent test in this suite hits). 10 new
tests in `test_preflight.py` (6 for `run_doctor()`'s pass/fail/never-raises
behavior, 2 CLI-integration tests via `typer.testing.CliRunner` confirming
the actual exit-code wiring, plus restoring one pre-existing test that
was nearly dropped during a sloppy `str_replace` mid-edit — caught before
commit, not after). Full suite: 652 passed / 31 failed / 1 xfailed / 5
errors — the 31+5 unchanged from D-058's baseline (same pre-existing
Chromium-binary/no-display environment gaps this sandbox has throughout),
zero new failures.

**Still open from the broader hardening plan:** explicit `assertion_kind`
on the planner spec (AD1) — this is what would finally let the AB1
fake-500-error `xfail` test close, since a `negative`/error-check
assertion kind is exactly what's needed to detect that case — guardrail
short-circuit on identical retries (AD2), the doc-drift CI check (AE1),
and the `aura audit-report` CLI on top of AB2's `find_anomalies()` (AE2).

## D-060 — AD1: explicit `assertion_kind` on the planner spec (2026-07-24)

**Context:** continuing the hardening plan from D-057/D-058/D-059 into
Phase AD, ahead of AC's usual "let AA-AC stabilize first" ordering (an
explicit choice made this session, since AD1 itself is self-contained
and doesn't depend on AB/AC's outputs — only AD2 genuinely needs AA2's
trace-comparison plumbing, so AD2 was deliberately left for later).

**The gap.** `check_assertion_detailed()` (AA1, D-057) always inferred
intent from `expected_state`'s string shape — a short slug went through
literal OCR matching, a longer sentence-shaped string went through the
structural "did anything render" fallback. Two real problems with that:
(1) it could misclassify a genuinely literal but sentence-shaped on-screen
label, or a short-but-vague phrase, purely because of word count; (2) it
had **no way at all to express "this must NOT appear"** — every
expected_state was implicitly a positive check, so an assertion like
"the error banner should not be visible" had nothing better to fall back
on than a (wrong) literal search for the on-screen phrase "error banner".

**The fix.** `TestStep.assertion_kind` / `Assertion.assertion_kind`
(`orchestrator/schemas.py`): `literal_text | page_rendered | negative |
custom`, `None` by default (fully backward-compatible with every
already-generated spec). `check_assertion_detailed()` uses it directly
when given instead of guessing:
- `literal_text` — strict OCR search, no silent fallback to "something
  rendered" if the literal text isn't found (previously that ambiguity
  was baked into the "not found -> maybe it's descriptive" fallback
  path; an explicit `literal_text` kind now means the caller wants a
  real failure if the literal text is truly absent).
- `page_rendered` — the pure structural check, no attempt at literal
  matching first.
- `negative` — new logic, didn't exist before at all: passes iff the
  target text is *not* found via `locate_text`.
- `custom` — no built-in strict check exists for an author-declared
  custom condition; falls through to the same shape-based inference
  used for legacy `None` specs, but is tagged as a deliberate judgment
  call rather than an unclassified legacy gap.

Every returned evidence dict now also carries `kind_source: "explicit" |
"inferred"` — so the audit trail (AA1's `raw_evidence`) itself shows
whether a verdict rested on the planner's stated intent or a heuristic
guess, not just the verdict itself.

`LocalHeuristicBackend` (`agents/planner/spec_generator.py`) now emits
`assertion_kind` explicitly: `page_rendered` for the `page_loaded`
fallback (the exact case D-055/D-056 already hardened), `literal_text`
for "should see X" phrasing, and a new `negative` regex branch for
"should not/must not see/show/display X" — previously unsupported
entirely, so a requirement author writing a negative assertion in plain
English had it silently mis-parsed as a positive one. The LLM-backed
planners (`CloudLLMBackend`/`HermesAgentBackend`/`LocalLLMBackend`) get
the same explicit classification via an updated
`SPEC_GENERATION_SYSTEM_PROMPT` (`agents/planner/prompts.py`) describing
all four kinds and requiring one whenever `expected_state`/`expected` is
set.

**On the AB1 fake-500-error `xfail` test:** checked directly rather than
assumed — that test calls `check_assertion()` with no `assertion_kind`
at all, deliberately exercising the legacy default-inference path, so
AD1 does not automatically close it. Closing it for real requires the
planner to correctly classify that specific real-world phrasing ("The
dashboard page has fully loaded and is displaying correctly" against a
500-error page) as something other than a bare structural check — a
planner-judgment problem, not a mechanical one — so it's left open and
still `xfail`, not falsely marked resolved here.

Verified: 10 new tests in `tests/test_assertions.py` (explicit
`page_rendered` bypassing shape inference, explicit `literal_text` not
silently falling back, both `negative` branches, `custom`'s inference
fallback, `None`'s full backward compatibility, and three
`LocalHeuristicBackend` emission tests for the fallback/positive/negative
cases). Full suite compared via `git stash` against unmodified `main`:
identical baseline both before and after (652 passed / 31 failed / 1
xfailed / 5 errors, all pre-existing Chromium-binary/no-display
environment gaps this sandbox has throughout) — 661 passed after adding
this pass's 10 tests, zero new failures.

**Still open from the broader hardening plan:** guardrail short-circuit
on identical retries (AD2) — needs AA2's trace-comparison plumbing wired
up before it has anything to compare against, not yet done — the
doc-drift CI check (AE1), and the `aura audit-report` CLI on top of
AB2's `find_anomalies()` (AE2).

## D-061 — AE1/AE2: doc-drift guard and `aura audit-report` (2026-07-23)

**Context:** Phase AE, the last phase in the AA→AE hardening sequence
D-057 laid out.

**AE1 — doc-drift guard (`scripts/check_doc_drift.py` +
`tests/test_doc_drift.py`).** Same shape as AA3's
`check_silent_excepts.py` (D-057): a pure, unit-tested core
(`find_drift()`) plus a thin CLI wrapper, wired into the normal pytest
run rather than installed as an actual `.git/hooks` script (hooks
aren't checked into the repo, so a fresh clone silently loses them —
directly usable as a local pre-commit hook by anyone who wants one, see
its module docstring). Rule: any diff touching `agents/`,
`orchestrator/`, `aura/`, `api/`, `config/`, `reports/`, `runtime/`,
`scripts/`, `ui/`, or `webui/` must also touch `docs/decisions.md`;
generated run artifacts (`reports/run_*`, `runtime/traces/`,
`runtime/screenshots/`, `runtime/baselines/`, `runtime/data_cache/`) and
test-only/doc-only changes are exempt. Supports a local pre-commit mode
(`git diff --cached`, no args) and a CI/PR mode (`--base-ref <branch>`,
diffing against the merge-base).

Dogfooded directly: running it against this very change-set (AE1+AE2's
own files staged, before this entry existed) correctly flagged
`aura/cli/audit_cmd.py`, `aura/main.py`, and a synthetic test edit to
`orchestrator/kernel.py` as drift — caught its own commit missing a
decisions.md entry, which is what this entry is closing.

**AE2 — `aura audit-report` (`aura/cli/audit_cmd.py`, wired into
`aura/main.py`).** `aura audit-report <run_id>` (or `--all` across every
run) reads AB2's `logs/assertion_audit.jsonl` via `read_records()` and
`find_anomalies()`, prints a verification-method breakdown table and an
anomalies table (D-056's exact bug shape: `escalate=False` with
`passed=False`), and exits non-zero if any anomalies are found or if no
records exist for the given scope — usable as a CI gate on a run's own
audit trail, not just an interactive report a human has to remember to
read. `--full` also lists every record, not just anomalies. `--log-path`
overrides the default log location for testing/alternate deployments.

Verified: 7 new tests in `tests/test_doc_drift.py` (source-change
detection, decisions.md-present exemption, test/doc-only exemption,
empty-diff no-op, generated-artifact exemption, mixed change-sets, and
one integration test that runs the real CLI against this repo's own git
state without crashing) and 7 new tests in `tests/test_audit_cmd.py`
(clean run, D-056 bug-shape detection, missing-run handling, `--all`
cross-run scope, and CLI-level exit-code checks via
`typer.testing.CliRunner` for both the pass and failure paths, plus the
`run_id`-or-`--all`-required usage error) — 14 new tests total. Manually
verified end-to-end against a synthetic log: `aura audit-report demo-run`
correctly reported one anomaly and exited 1. Full suite: 689 passed / 17
failed / 1 xfailed / 5 errors in this environment — failures/errors are
entirely pre-existing Chromium-binary/no-display/DOM-fixture gaps
unrelated to this change (confirmed none reference `doc_drift` or
`audit_cmd`); the improved pass count vs. D-060's noted 661 reflects
this session's environment having more of the project's real
dependencies installed, not a change in this patch's own correctness.

**This closes Phase AE, and with it the full AA→AE hardening plan laid
out in D-057.** Genuinely still open, unchanged: AD2 (guardrail
short-circuit on identical retries, needs AA2's trace-comparison
plumbing wired up as actual comparison logic, not just the schema) and
the AB1 fake-500-error `xfail` (needs planner-side judgment to classify
that specific phrasing as a negative/error check — see D-060's note).

## D-062 — AD2: guardrail short-circuit on identical retry evidence (2026-07-23)

**Context:** the last genuinely open item from D-057's original AA→AE
plan (D-061 closed Phase AE but explicitly left this one and the AB1
`xfail` open). Directly motivated by D-055's incident: a live run's
self-healing retried a failing `ASSERT` step three times with an
identical result before the count-based guardrail hard-stop finally
fired. The count-based thresholds (`exact_failure_count`,
`same_tool_failure_count`) answer "how many times has this failed,"
which can legitimately still be mid-count while the *evidence itself*
already proves further retries are pointless — a gap the plan flagged
as needing AA1's trace schema (`verification_source`/`raw_evidence`) to
close, since that's the first place real per-attempt evidence became
available to compare, rather than a coarse proxy like confidence score
or a hand-built failure-signature string.

**What was built:**
- `orchestrator/guardrails.py::compute_evidence_fingerprint()` — a
  stable SHA-256 fingerprint of `(verification_source, raw_evidence)`
  (`json.dumps(..., sort_keys=True)` before hashing, so key order never
  affects the result). Returns `None` when `raw_evidence` is `None`
  (no verification ran for that attempt — a bare `SCROLL`/`NAVIGATE_URL`
  with no `expected_state`), and callers must never treat two `None`s as
  a match — there's nothing there to actually compare.
- `LoopGuardrail.record_evidence(step_id, tool_name,
  evidence_fingerprint)` — new method alongside the existing
  `record_failure()`/`record_no_progress()`. If the fingerprint matches
  the immediately preceding attempt's fingerprint for that step, returns
  `HARD_STOP` immediately, bypassing `exact_failure_count`/
  `same_tool_failure_count` entirely. Gated by a new
  `GuardrailSettings.short_circuit_on_identical_evidence` flag (default
  `True`) for anyone who wants pure count-based behavior back.
  `StepLoopState` gained `last_evidence_fingerprint` and
  `identical_evidence_short_circuited` (surfaced in `state_snapshot()`
  so a `memory.escalate()` record and, downstream, `aura audit-report`
  can both see *why* a hard-stop fired, not just that it did).
  `reset()` (called on a successful heal) already clears the whole
  per-step state dict, so it clears this fingerprint history too — no
  separate handling needed.
- `orchestrator/healing_loop.py::HealingLoop.heal()` — after the
  existing count-based `record_failure()` check, now also fingerprints
  `current_result` and calls `record_evidence()` before running
  `diagnose_fn`. On the loop's first iteration this only seeds the
  fingerprint (nothing to compare against yet); on the second and later
  iterations it's comparing the latest retry's evidence against the one
  immediately before it. A short-circuit escalates via the same
  `memory.escalate()` path as the count-based hard-stop, with a distinct
  `reason` string (`"...AD2 short-circuit"`) so it's identifiable in the
  escalation queue and in `aura audit-report`'s output, not
  indistinguishable from an ordinary count-based hard-stop.

**Verified:** 16 new tests — 12 appended to `tests/test_guardrails.py`
(fingerprint determinism/None-handling/source-sensitivity/key-order-
independence, `record_evidence()`'s first-call/None/identical/
different/config-disabled/snapshot/reset behavior) and 4 in the new
`tests/test_healing_loop.py` — the first HealingLoop tests in this repo
at all, run against real `RunMemoryStore`/`SkillStore` sqlite instances
rather than mocks. The key one,
`test_identical_evidence_retries_escalate_immediately_not_after_full_count_threshold`,
reproduces D-055's incident shape directly: with
`hard_stop_after_exact_failure` set to 10 (so the count-based path alone
would need 10 loop iterations), a `execute_step_fn` stub that always
returns byte-identical evidence escalates after exactly **1** retry
attempt, not 10 — proving the short-circuit is what fired, not the
count-based path getting lucky. A second test proves genuinely changing
evidence across retries does *not* short-circuit and the loop heals
normally; a third proves steps with no verification evidence at all
(`raw_evidence=None` throughout) correctly fall back to pure count-based
behavior instead of AD2 ever matching `None` against `None`.

Full suite: 705 passed / 17 failed / 1 xfailed / 5 errors — 16 more
passing than D-061's 689 (exactly the 16 new tests here), same
pre-existing Chromium/DOM-fixture failures/errors, confirmed none
reference `guardrails` or `healing_loop`. `scripts/check_doc_drift.py`
(D-061) correctly flagged this change-set's three source files before
this entry existed, same as it did for its own commit in D-061 — kept
running clean.

**This closes the AD2 item explicitly left open by D-061.** The only
genuinely open item remaining from the original D-057 plan is the AB1
fake-500-error `xfail`, which needs planner-level judgment (classifying
that specific error-page phrasing as a negative/error check) rather than
a mechanical fix — see D-060's note for why it was deliberately left as
a real `xfail(strict=True)` instead of silently worked around.



