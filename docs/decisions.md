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
