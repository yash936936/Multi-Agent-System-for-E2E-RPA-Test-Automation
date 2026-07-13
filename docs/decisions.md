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
