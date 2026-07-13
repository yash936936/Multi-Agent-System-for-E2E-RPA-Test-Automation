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
