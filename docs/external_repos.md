---
type: external-repo-extraction-log
project: AURA
last_updated: 2026-07-13
---

# external_repos.md — Verified extractions from external reference repos

Every entry below was produced by actually cloning the repo and reading real
files (see commands/paths cited per entry) — nothing here is guessed or
reconstructed from memory. Entries are grouped in the batches they were
processed in, per `context.md` §5.

**Excluded, on purpose, before any batch:**
- `elder-plinius/G0DM0D3` — apparent model-safeguard-removal tooling. Not reviewed, not extracted.
- `BraveOPotato/FckSignups` — apparent signup/verification-bypass tooling. Not reviewed, not extracted.

---

## Batch 1 — Automation & navigation (for Task 3: cursor-navigation + link-checking migration)

Repos: `microsoft/playwright`, `microsoft/playwright-mcp`, `bytedance/UI-TARS-desktop`, `vercel-labs/agent-browser`.

### 1. `microsoft/playwright` (and `playwright-mcp`, which is published from this monorepo)

Note: `playwright-mcp`'s own repo (`ext_playwright-mcp/src/README.md`) states its
source actually lives in the Playwright monorepo at
`packages/playwright-core/src/tools/mcp` and `.../tools/backend`. Both repos were
cloned; the real tool implementations were read from the monorepo path.

**Key architectural pattern to adopt — accessibility-tree snapshot targeting,
not pixel-only vision.**
`packages/playwright-core/src/tools/backend/snapshot.ts` defines `browser_snapshot`
("Capture accessibility snapshot of the current page, this is better than
screenshot") and `browser_click`, which resolves a `target` (an accessibility
snapshot ref or unique selector) to a Playwright `Locator` and calls
`.click()`/`.dblclick()` with configurable button/modifiers, wrapped in
`tab.waitForCompletion()`. Every action also emits the equivalent Playwright
code string (`response.addCode(...)`) for auditability — directly useful for
AURA's own report generation (`reports/render.py`), which already wants a
human-readable action trace.

**Navigation logic** — `packages/playwright-core/src/tools/backend/navigate.ts`:
`browser_navigate` calls `context.ensureTab()` then
`tab.checkUrlAndNavigate(params.url)`; `browser_navigate_back`/`_forward` wrap
`page.goBack()`/`page.goForward()` with `waitUntil: 'commit'` and a configurable
`navigationTimeoutOptions`. This `waitUntil: 'commit'` choice (don't block on
full load, just on navigation commit) is relevant to AURA's link-checker
redirect-chain handling.

**Where this maps in AURA:**
- `agents/vision/locator.py` — today locates elements purely via OCR/pixel
  coordinates (per `runtime/hooks/capture.py` + `interact.py`). The
  Playwright pattern suggests adding an accessibility-tree-first path: when
  the target is a live web page, resolve elements via Playwright's
  accessibility snapshot + locator resolution *before* falling back to pixel/OCR
  vision. This directly fixes the client-rendered-page gap recorded in
  `docs/STATUS.md` ("aura explore ... gave a misleading 'no links found'
  message on client-rendered (React/Next.js) pages... would require a
  headless-browser render step (e.g. Playwright)").
- `agents/capability/link_checker.py` — currently fetches raw HTML (per
  `STATUS.md`'s own note that it can't see JS-injected links). Replacing the
  fetch step with a headless Playwright page load + accessibility/DOM query
  for `<a>` elements after JS execution closes this exact documented gap.
- `runtime/hooks/interact.py` — pixel-coordinate click/type primitives.
  Playwright's locator-based click should become the primary path for
  browser targets, with the existing pixel-based path retained as the
  fallback for non-browser (native desktop) targets — this preserves AURA's
  original "vision survives DOM churn" value prop for cases where there is no
  accessibility tree to query (see Batch item on UI-TARS below for that
  fallback).

**License note:** Apache-2.0 (per file headers observed in
`packages/playwright-core/src/tools/backend/snapshot.ts` and `navigate.ts`) —
compatible with reuse; retain the copyright header if code is copied verbatim
rather than reimplemented.

---

### 2. `bytedance/UI-TARS-desktop`

**Key pattern to adopt — coordinate normalization for vision-based clicking.**
`packages/ui-tars/action-parser/src/actionParser.ts` implements
`smartResizeForV15()` and `actionParser()`, which take a model's raw
prediction text plus the actual screen dimensions and a scale/aspect-ratio
factor, and produce normalized, pixel-accurate click coordinates
(`roundByFactor`/`floorByFactor`/`ceilByFactor` against `IMAGE_FACTOR`,
`MIN_PIXELS`, `MAX_PIXELS_V1_5`, with an aspect-ratio sanity check via
`MAX_RATIO`). This solves a real, common vision-agent bug class: a
model reasoning over a resized/downsampled screenshot produces coordinates
that don't map 1:1 back to actual screen pixels.

**Where this maps in AURA:**
- `agents/vision/locator.py` / `agents/vision/executor.py` — AURA's vision
  pipeline (`mss` capture → `pytesseract` OCR → `pyautogui` click, per
  `docs/Roadmap.md`'s "Vision Core" row) currently has no documented
  coordinate-normalization step between OCR'd text bounding boxes and actual
  screen coordinates. Porting UI-TARS's `smartResizeForV15`-style scaling
  (adapted for OCR bounding boxes instead of a VLM's raw text coordinates) is
  a concrete, low-risk hardening for `agents/vision/locator.py`, and directly
  relevant to Task 3's "PixelRAG logic" requirement for the desktop-app
  fallback path (where there's no DOM/accessibility tree, only pixels).
- This is the natural home for the eventual PixelRAG-derived cursor logic:
  UI-TARS provides the coordinate-normalization *math*; a PixelRAG-derived
  component (not yet reviewed — pending a later batch) would provide the
  screen-text-retrieval layer on top. Both belong in the same fallback path,
  used only when Playwright's accessibility tree isn't available (native
  desktop apps — this is also the explicit gap flagged in `docs/STATUS.md`:
  "no test in this codebase driving an actual non-browser desktop app
  end-to-end").

**License note:** Apache-2.0 (per file header in `actionParser.ts`).

---

### 3. `vercel-labs/agent-browser`

**Key pattern to adopt — compact accessibility-ref element addressing (`@eN`).**
The repo's own skill doc (`skills/agent-browser/agent-browser.md`) describes
its core value prop: "Chrome/Chromium via CDP with accessibility-tree
snapshots and compact `@eN` element refs," explicitly preferring
accessibility-tree refs over raw selectors or pixel coordinates for
reliability. The Rust CLI's element-resolution logic
(`cli/src/native/element.rs`) implements `resolve_element_center`,
`resolve_element_object_id`, and `resolve_by_selector`, backed by Chrome
DevTools Protocol's `DOM.resolveNode` — i.e., resolve a compact ref to a real
DOM node, then to an object id, then to a center point, only falling to pixel
coordinates as the last step needed to actually dispatch a click.

**Where this maps in AURA:**
- Reinforces the same architectural direction as the Playwright extraction
  above: resolve-by-reference first, pixel-coordinate dispatch last. AURA's
  `agents/vision/locator.py` currently has no notion of a stable "element
  ref" at all — every locate is a fresh OCR pass. Adding a ref-based cache
  (map a resolved element to a short-lived ref, valid until the next
  navigation/snapshot) would reduce redundant OCR/vision calls across
  multi-step flows in `orchestrator/run_engine.py`.
- Its skill-file "discovery stub" pattern (a short pointer doc that tells the
  agent to fetch full instructions from the live CLI, "so instructions never
  go stale") is a good pattern for AURA's own `docs/` — worth considering for
  the `debug.md`/`context.md` relationship if these docs start drifting from
  actual code behavior over time. Noted as a documentation-process idea, not
  a code change.

**License note:** repo's `LICENSE` file present at root (not read in full for
this pass — read it before copying any code verbatim, only the documented
CLI-usage pattern was reused here, not literal source).

---

## Batch 2 — Screen reading (`StarTrail-org/PixelRAG`)

**Important correction to the original task framing:** PixelRAG is a
*visual retrieval-augmented generation* system (paper: "PixelRAG: Web
Screenshots Beat Text for Retrieval-Augmented Generation," Berkeley
SkyLab/BAIR/NLP) — it renders pages/PDFs/images to tiled screenshots and lets
a vision model **read and search over them**. It does **not** do cursor
movement or clicking. The original task description lumped "navigating the
cursor, clicking, and reading on-screen text" into one PixelRAG bullet; only
the *reading* part is actually in scope for this repo. Cursor/click logic
comes from Batch 1 (Playwright accessibility-click, UI-TARS coordinate
normalization, agent-browser ref resolution) — noting this explicitly per
`context.md`'s rule against fabricating extractions that aren't really there.

**Core mechanism** (`plugin/skills/pixelbrowse/SKILL.md`, `demos/render/run.py`,
the `render/src/pixelrag_render` package): a `pixelshot` CLI renders a URL/PDF/
local HTML file into tiled JPEG images sized for vision-model consumption —
critically, capped at **1568px tile height**, because Claude's vision models
downscale any image with a long edge over 1568px (Sonnet/Haiku) or 2576px
(Opus), and the default 8192px tile height would produce unreadable text if
fed to a model directly. Two flags matter operationally:
- `--wait-network-idle` — waits for the page's load event plus a network-quiet
  window before capturing, specifically to avoid capturing JS-heavy/SPA pages
  half-rendered. **This is the same problem AURA's link-checker already hit**
  (`docs/STATUS.md`'s client-rendered-page gap) — independent confirmation
  that a load+network-idle wait, not just `DOMContentLoaded`, is the right fix.
- Crop-and-zoom follow-up: for content too small to read at tile resolution,
  crop the region with Pillow and re-read at full resolution — a cheap,
  concrete pattern for AURA's OCR pipeline when `pytesseract` confidence is
  low on small text.

**Where this maps in AURA:**
- `agents/vision/executor.py` / `runtime/hooks/capture.py` — today AURA
  captures raw screenshots via `mss` at native resolution and OCRs them
  directly. PixelRAG's tiling-to-vision-model-limits pattern is directly
  reusable if/when AURA's vision agent is backed by a multimodal LLM call
  (rather than OCR-only) — tile + cap long edge at the target model's
  downscale threshold before sending, and only OCR-scan the specific tile
  containing the target region, rather than the whole screen.
- `agents/capability/link_checker.py` — independent confirmation (see above)
  that AURA's own planned fix (headless-browser render + network-idle wait,
  per Batch 1's Playwright extraction) is the correct direction, not a
  workaround.
- The crop-and-zoom-on-low-confidence pattern is a good addition to
  `agents/vision/locator.py`'s existing confidence-gating story (FR8 in
  `docs/PRD.md`: "low-confidence actions are queued for planner review") —
  crop-and-retry before escalating to human review, not instead of it.

**License note:** Apache-2.0 (badge in README; not independently re-verified
against the LICENSE file text for this pass — check before verbatim reuse).

---

## Batch 3 — AI optimization + agent memory (`ponytail`, `TencentDB-Agent-Memory`, `cognee`)

### 1. `DietrichGebert/ponytail`

**What it actually is:** not a memory system — a code-minimalism *behavior
skill/prompt* injected into an AI coding agent (Claude Code, Codex, Cline,
Copilot, Gemini, etc. via per-tool hooks under `hooks/`), enforcing "write the
least code that correctly solves the problem" instead of over-engineering.
Reported (per its own benchmark writeup, not independently re-verified here)
~54% mean code reduction on real Claude Code sessions.

**Core mechanism** (`hooks/ponytail-instructions.js`, `getFallbackInstructions()`):
a fixed decision ladder run *before* writing any code:
1. Does this need to be built at all? (YAGNI)
2. Does it already exist in this codebase? Reuse, don't rewrite.
3. Does the standard library do this?
4. Does a native platform feature cover it?
5. Does an already-installed dependency solve it?
6. Can this be one line?
7. Only then: write the minimum code that works.

Plus explicit non-negotiables ("When NOT to be lazy"): never simplify away
input validation at trust boundaries, error handling that prevents data loss,
security measures, accessibility basics, or hardware/platform calibration
("the platform is never the spec ideal") — and any deliberate corner-cut must
be marked with a `ponytail:` comment naming the ceiling and upgrade path
rather than silently shipped.

**Where this maps in AURA / this task:**
- This is a direct, adoptable addition to `docs/debug.md` and `context.md`'s
  "standing instructions" section — AURA's own recorded bug history (stub
  `execute_run()`, schema-rename half-migrated across 7 files) is exactly the
  kind of thing this ladder + "mark deliberate simplifications, never hide
  them" rule would have caught or prevented. Recommend adding ponytail's
  ladder as an explicit pre-code-change step in `docs/debug.md`, and its
  "mark cut corners with an inline comment naming the ceiling" rule as a
  companion to `docs/debug.md`'s existing TODO/FIXME grep step.
- Not applicable to AURA's runtime agents themselves (it's a prompting/hook
  pattern for the *AI contributor*, not a piece of software AURA executes) —
  scope it to `docs/debug.md`/`context.md` updates, not `agents/`/`orchestrator/`.
- License: MIT (badge in README).

### 2. `TencentCloud/TencentDB-Agent-Memory`

**Notable naming overlap (verified, not coincidence to gloss over):** this
repo's plugin architecture is built for a system it calls **"Hermes"**
(`Hermes Gateway`, `hermes-agent.nousresearch.com`, `hermes-plugin/` as the
actual source directory) — the same term AURA's own docs use for its
inter-agent tool-calling interface ("Hermes Agent API," per `docs/PRD.md`
FR13, `docs/WORKFLOW.md`). These are two unrelated Hermes-named systems (this
repo's Hermes is a third-party agent gateway product, not AURA's), but this
should be flagged in code/docs so nobody conflates them when reading imports
or config later.

**Core mechanism:** two-tier memory, not flat vector storage —
1. **Symbolic short-term memory** — compresses heavy tool-call logs/output
   into compact Mermaid-diagram symbols mid-session, cutting token usage
   (self-reported ~61% on one benchmark, ~30-33% on others — see README table,
   not independently re-verified here).
2. **Layered long-term memory** — distills fragmented conversation history
   into structured "personas and scenes" instead of a flat vector-embedding
   pile, aimed at cross-session recall.

Architecturally it runs as a **sidecar process**: `hermes-plugin/memory/memory_tencentdb/supervisor.py`'s
`GatewaySupervisor` spawns/health-checks a separate Node.js "Gateway" process
over HTTP (default `127.0.0.1:8420`), with a Bearer-token client
(`client.py`) — i.e., the memory store is a separate long-running service the
main agent process talks to, not an in-process library call.

**Where this maps in AURA:**
- `orchestrator/memory.py` (general agent memory) and
  `orchestrator/skill_store.py` (reusable failure/fix "skills") are AURA's
  closest existing equivalents, both currently simple file/JSON-backed local
  stores per `context.md` §4. The **symbolic short-term compression** idea
  (compact structured summary instead of raw tool-log accumulation) is
  directly relevant to AURA's per-run audit trail
  (`orchestrator/audit_logger.py` → `logs/audit.jsonl`) and to keeping
  Planner-agent context small on long multi-step specs — worth a follow-up
  design note in `docs/decisions.md` rather than an immediate rewrite.
- The **sidecar-process-with-health-check** pattern is a reasonable template
  if AURA's memory/skill stores ever need to move off simple file storage
  (e.g. to support the multi-tenant API run-store persistence gap noted in
  `docs/STATUS.md`) — but this is a bigger architecture decision, not a
  drop-in.
- License: MIT (README badge).

### 3. `topoteretes/cognee`

**Core mechanism:** "AI Memory Platform" — ingests arbitrary data, builds a
self-hosted **knowledge graph** (not just vector embeddings) so agents can
"recall, connect, and act with full context" across sessions. Exposes a
clean, memory-verb-shaped API surface: `cognee/api/v1/remember/remember.py`
(`remember()` — ingest + store, with `RememberKwargs` for power-user options
like `graph_model`, `node_set`, `incremental_loading`), and a matching
`cognee/api/v1/recall/recall.py` for retrieval, plus adjacent verbs —
`cognify`, `memify`, `forget`, `sync`, `visualize` — each its own API module
under `cognee/api/v1/`. Observability is built in from the start
(`cognee.modules.observability` spans tagged with dataset name, session id,
data size, operation mode).

**Where this maps in AURA:**
- The **verb-shaped API design** (`remember`/`recall`/`forget`, each a small
  dedicated module) is a clean pattern worth mirroring if
  `orchestrator/memory.py` and `orchestrator/skill_store.py` are ever merged
  or given a public-facing API surface (relevant if/when the FastAPI service
  layer in `api/` matures past its current documented gaps).
- The **knowledge-graph-over-flat-storage** approach is the more ambitious of
  the three memory repos in this batch — most relevant to AURA's stated
  Roadmap Phase 3 goal ("local failure-memory index," FR11 in `docs/PRD.md`)
  if AURA ever wants relational reasoning over past failures/fixes (e.g. "this
  failure class is connected to that adapter's known gap") rather than simple
  key-based lookup. Flagged as a Phase-3-relevant option in
  `docs/Roadmap.md`, not an immediate change — `orchestrator/skill_store.py`
  and `orchestrator/memory.py` are file/JSON-backed today and a graph-backed
  rewrite is a real scope increase, not a drop-in swap.
- License: check `cognee`'s own LICENSE file before any verbatim reuse (not
  re-verified in this pass — only the architecture pattern was reviewed).

---

## Batch 4 — agent loop guardrails, knowledge/brain layer, internet access, harness engineering

### 1. `FoundationAgents/OpenManus`

**Correction to original task framing:** listed under "for training local
llm," but OpenManus is actually a general-purpose autonomous agent framework
(Manus-style: `BaseAgent`/`ToolCallAgent`/`ReActAgent`/`BrowserAgent`/`Manus`
subclasses under `app/agent/`), not an LLM training/fine-tuning toolkit. No
training code was found in `app/`. Flagging honestly rather than fabricating
a "local LLM training" extraction that isn't in this repo.

**Genuinely useful, verified content — stuck-loop detection.**
`app/agent/base.py`'s `BaseAgent.run()` implements exactly the guarded
step-loop AURA's own `orchestrator/guardrails.py` also aims for (per
`docs/PRD.md` FR7: "detect and halt unproductive retry loops"):
- Hard step cap: `while self.current_step < self.max_steps and self.state != AgentState.FINISHED`.
- `is_stuck()`: compares the latest assistant message's content against prior
  assistant messages in memory; if identical content repeats
  `>= duplicate_threshold` (default 2) times, the agent is considered stuck.
- `handle_stuck_state()`: doesn't hard-abort — it injects a corrective
  instruction ("Observed duplicate responses. Consider new strategies...")
  into `next_step_prompt` before the next step, giving the agent one chance
  to self-correct before the hard step cap eventually terminates it.

**Where this maps in AURA:**
- `orchestrator/guardrails.py` and `orchestrator/healing_loop.py` — compare
  against this exact-duplicate-content detection method. AURA's guardrails
  are referenced throughout `docs/PRD.md`/`docs/Roadmap.md` but this is a
  concrete, small, verified algorithm worth checking against AURA's current
  implementation during the next `docs/debug.md` pass on those two files —
  specifically whether AURA already has a "nudge before hard-stop" step like
  `handle_stuck_state()`, or only a hard cap.
- License: MIT (README badge).

### 2. `garrytan/gbrain`

**Correction to original task framing:** listed as "our system's main LLM
brain," but gbrain is actually a personal knowledge-management "brain layer"
(synthesis + graph traversal + gap analysis over ingested pages), built by
Garry Tan (Y Combinator) for his own agent deployments — not an LLM itself,
and not something to literally become AURA's "main brain." Framing corrected
here rather than silently adopting the task's phrasing as fact.

**Genuinely useful pattern — compiled-truth-plus-timeline knowledge model**
(`docs/GBRAIN_V0.md`): every knowledge page splits into **compiled truth**
(current best understanding, rewritten as evidence changes) and an
**append-only timeline** (raw evidence trail, never edited, only appended).
Retrieval is hybrid: vector embeddings + keyword (`tsvector`/`pg_trgm`) +
Reciprocal Rank Fusion, over Postgres (originally sqlite-based, later ported
to embedded Postgres via PGLite per the doc's own migration note).

**Where this maps in AURA:**
- This is a strong candidate pattern for `orchestrator/skill_store.py` and
  `orchestrator/memory.py`'s eventual evolution (same Phase-3 "local
  failure-memory index" goal flagged for `cognee` in Batch 3): instead of
  overwriting a stored "skill"/fix when a new instance of a failure is
  diagnosed, keep a **compiled current understanding** (the best-known fix)
  plus an **append-only timeline** of every time that failure/fix was seen —
  this preserves history for `docs/progress.md`-style audit while still
  giving the Planner agent a single current answer to act on. Worth a
  `docs/decisions.md` entry as a candidate design, not an immediate rewrite.
- License: check `ext_gbrain/LICENSE` before any reuse beyond the pattern
  itself — not verified in this pass.

### 3. `Panniantong/Agent-Reach`

**What it actually is:** an installer/health-check ("doctor") tool that
configures upstream internet-access CLIs (`twitter-cli`, `yt-dlp`,
`mcporter`, `gh`, etc.) for an agent to call directly — it does not perform
search itself; per its own `core.py` docstring: "For reading/searching, use
the upstream tools directly." Its value is channel selection + health
verification, not a search backend.

**Genuinely useful pattern — the `doctor()`/health-report design**
(`agent_reach/core.py::AgentReach.doctor()` → `agent_reach/doctor.py::check_all()`
→ `format_report()`): a single call that checks every configured
access channel's availability and returns a uniform report.

**Where this maps in AURA:**
- AURA already has an equivalent concept — `aura/cli/preflight.py`. This is
  worth a direct side-by-side comparison in a future `docs/debug.md` pass:
  does `preflight.py` check every capability adapter's live availability
  (API/DB/email/file/Excel/PDF/cloud/SharePoint/chat-ops) the way
  Agent-Reach's `check_all()` checks every configured channel, with one
  uniform pass/fail report? If not, this is a concrete, low-risk hardening
  for `preflight.py`.
- Not a source of "online search" capability itself — no search backend to
  extract. Correcting the original task's framing here rather than inventing
  a search-integration that doesn't exist in this repo.
- License: MIT (README badge).

### 4. `kju4q/q-agent-harness`

**What it is:** a starter-kit/reference doc set (not primarily code) for
"harness engineering" — building the environment around an AI coding agent:
a map (docs/context), guardrails (approval policy), and feedback loops. This
maps almost one-to-one onto this task's own `context.md` + `debug.md` design.

**Genuinely useful, directly adoptable pattern — explicit approval-tier list**
(`docs/approval-policy.md`): a two-column policy — actions allowed without
approval (read files, update docs, edit non-destructive code, run local
tests/validation, create safe preview data) vs. actions requiring approval
(delete an environment, change billing config, remove users, rotate secrets,
run destructive shell commands) — with a stated rationale ("make high-risk
actions explicit, not slow agents down") and worked examples.

**Where this maps in AURA / this task:**
- Directly adoptable into `context.md` §6 ("Standing instructions") and/or a
  new subsection of `docs/debug.md`: define AURA's own allowed-without-approval
  vs. requires-approval action tiers (e.g., editing `agents/`/`orchestrator/`
  code = no approval needed if `docs/debug.md`'s checklist passes; rotating
  `config/vault.key`, deleting `orchestrator/memory_store/`/`skills_store/`
  contents, or modifying `config/users.json` = approval required). Recommend
  adding this as a concrete near-term update to `context.md` §6.
- `docs/architecture-boundaries.md` and `docs/repo-structure.md` (not fully
  read this pass) look structurally similar to this task's own
  `context.md` §2 "directory map" — worth a follow-up read if further harness
  refinement is wanted.
- License: not confirmed in this pass (no LICENSE file spotted at repo root
  in the initial listing) — check before any verbatim text reuse.

---

## Batch 5 — agent loops, conversational voice, self-evolving skills, self-reflection bounds

### 1. `cobusgreyling/loop-engineering`

**What it is:** a reference repo of patterns for running unattended/scheduled
AI agent "loops" safely (`LOOP.md` is the operating doc). Genuinely relevant
to AURA's own healing/orchestration loops, not a mismatch.

**Core pattern — tiered loop autonomy + hard safety rails**
(`LOOP.md`'s "Active Loops" section):
- Loops are explicitly tiered by autonomy: **L1** ("automated + report" —
  runs unattended but only produces a report, human decides actions) vs.
  **L2** ("assisted, manual trigger" or "patch-only" — bounded automatic
  fixes, e.g. patch/low-risk-CVE dependency bumps only, with a human gate on
  anything major).
- Every unattended code-change attempt runs in an **isolated git worktree**,
  discarded after a verifier REJECT or human escalation — changes are never
  applied in-place speculatively.
- Explicit **multi-loop priority ordering** (CI Sweeper → PR Babysitter →
  Dependency Sweeper → Post-Merge/Changelog Drafter → Daily Triage) so
  concurrent loops don't fight each other.
- **Budget & kill-switch primitives**: documented token caps
  (`loop-budget.md`), an append-only `loop-run-log.md`, and a `loop-pause-all`
  flag/label as a global kill switch.

**Where this maps in AURA:**
- `orchestrator/healing_loop.py` and `orchestrator/guardrails.py` — AURA's
  self-healing already has a bounded retry count (2 heal attempts before
  escalating, per `docs/STATUS.md`'s cross-modal-healing note), but this
  repo's **tiered autonomy model** (report-only vs. bounded-auto-fix vs.
  human-gated) is a more structured way to express that than a single
  attempt-count. Worth considering for `docs/decisions.md` as a framing for
  AURA's `--yes`/`--autonomous` vs. `--interactive` modes (`docs/STATUS.md`'s
  "Autonomy modes" section) — those are already close to L1/L2 in spirit;
  formalizing the tier names and a kill-switch flag (AURA doesn't appear to
  have an equivalent of `loop-pause-all` for its scheduled runs,
  `aura/cli/schedule_cmd.py`) is a concrete, scoped addition.
- License: MIT (LICENSE file present at root).

### 2. `pipecat-ai/pipecat`

**What it is:** a real-time voice/multimodal conversational-agent pipeline
framework (audio in → STT → LLM → TTS → audio out, plus video/vision), used
in production voice agents. Directly on-topic for "adding conversational
feature in our AI agent."

**Core architecture — bidirectional frame-processor pipeline**
(`src/pipecat/pipeline/pipeline.py`, `src/pipecat/processors/frame_processor.py`,
`src/pipecat/frames/frames.py`): a `Pipeline` is a sequence of
`FrameProcessor`s; `Frame` objects flow **downstream** (audio/text/control
data moving forward through STT→LLM→TTS) and **upstream** (interruptions,
errors, backpressure) through the same chain via `FrameDirection`. Each
processor only needs to implement `process_frame()` — the pipeline handles
routing. This cleanly separates "what runs" (services under
`src/pipecat/services/`) from "how data flows between them" (the frame/pipeline
abstraction), which is why pipecat can swap STT/LLM/TTS providers without
rewriting pipeline logic.

**Where this maps in AURA:**
- AURA doesn't currently have a voice/conversational interface — this is a
  genuinely new capability, not a hardening of existing code. If AURA adds a
  "narrate this test run" or "talk to a live QA session" feature (not
  currently in `docs/PRD.md`'s FR list), pipecat's frame-processor pattern is
  the right architectural reference: model AURA's own run events (screenshot
  captured, click dispatched, assertion failed, self-heal triggered — the
  same events already logged by `orchestrator/audit_logger.py`) as frames
  flowing through a pipeline, and hang a TTS/narration processor off the
  existing audit-log frame stream rather than bolting voice onto
  `orchestrator/run_engine.py` directly.
- This should be flagged as a new PRD requirement / roadmap phase
  (`docs/PRD.md`, `docs/Roadmap.md`) before implementation, since it's new
  scope, not a bug fix or hardening — per `docs/debug.md`'s convention of not
  silently expanding scope.
- License: BSD 2-Clause (per file headers, e.g. `pipeline.py`).

### 3. `HKUDS/OpenSpace`

**What it is:** a framework for making coding agents "self-evolving" —
agents analyze their own execution trajectories and patch/version their own
skill files over time, rather than a human hand-writing every skill.

**Core mechanism** (`openspace/skill_engine/`):
- `analyzer.py`'s `ExecutionAnalyzer.analyze_execution()` and
  `get_evolution_candidates()` — reviews a completed agent run's trajectory
  (tool calls, results, conversation) and identifies which skills should be
  revised, including quality feedback per tool
  (`_record_tool_quality_feedback`).
- `evolver.py` — takes evolution candidates and produces an actual skill
  patch (`patch.py`), i.e., the skill file itself is rewritten based on
  observed real-world performance, not just on new manual instructions.
- `store.py`/`registry.py` — versioned skill storage + lookup, with
  `fuzzy_match.py` for retrieving the closest matching skill for a new
  situation.

**Where this maps in AURA:**
- This is the closest external analog to `orchestrator/skill_store.py` (AURA's
  own "persist diagnosed failures as reusable skills," FR6 in `docs/PRD.md`).
  Current gap: AURA's skill store appears to persist a skill once a fix is
  found, but (per what's documented in `docs/STATUS.md`/`docs/Roadmap.md`)
  there's no described mechanism for *analyzing whether a stored skill is
  still good* over repeated use, the way OpenSpace's `analyzer.py` tracks
  per-tool quality feedback across runs. Concrete, scoped follow-up: add a
  lightweight quality-tracking field to whatever `skill_store.py` persists
  per skill (success/failure count on reuse), surfaced in
  `docs/STATUS.md`/`progress.md` the next time `skill_store.py` is touched —
  not a full port of OpenSpace's analyzer, just the tracking-field idea.
- License: MIT (README badge).

### 4. `MervinPraison/PraisonAI`

**Correction to original task framing:** listed under "research self
improvement," which is closer to what this repo actually has — but it's a
general multi-agent orchestration framework (agents, tools, memory, workflow)
with a **bounded self-reflection loop** feature, not a research-specific
self-improvement system.

**Core mechanism** (`praisonaiagents/agent/agent.py`): `self_reflect` (bool,
default `False`), with `min_reflect`/`max_reflect` (default `1`/`3`) —
an agent that self-reflects runs at least `min_reflect` and at most
`max_reflect` critique-and-revise passes on its own output before returning,
configurable per-agent, with an optional separate `reflect_llm` (a
different/cheaper model can be used just for the critique pass than for the
main generation).

**Where this maps in AURA:**
- Directly comparable to AURA's cross-modal self-healing bound ("up to 2 heal
  attempts before escalating," per `docs/STATUS.md`) — PraisonAI's
  min/max-bounded reflection with a *separate, possibly cheaper model for the
  critique step* is worth comparing against `agents/planner/cross_modal_diagnoser.py`'s
  current implementation: does AURA's diagnoser use the same model/backend
  for diagnosis as for the main planning step, or a lighter one? If the same,
  a cheaper dedicated diagnosis backend (mirroring `reflect_llm`) is a
  concrete resource-footprint improvement in line with `docs/PRD.md`'s
  success metric ("Resource footprint: minimized to the lowest technically
  viable level").
- License: MIT (per PyPI badge convention; not independently re-verified
  against the LICENSE file text this pass).

---

## Batch 6 — DOM self-healing, harness architecture, observability, in-page browsing, codebase-review scoping

### 1. `D4Vinci/Scrapling`

**What it is:** a Python web-scraping library whose headline feature is
**adaptive element relocation** — when a page's structure changes, it
re-finds a previously-known element by similarity rather than failing on a
stale selector.

**Core mechanism — verified, directly transferable** (`scrapling/parser.py`,
`Selector.relocate()`): given a previously-captured element (as a dict/HTML
element), it walks every element currently in the page tree
(`_find_all_elements`), computes a **similarity score** against the target
for each one (`__calculate_similarity_score`), and returns the highest-scoring
match(es) — but only if the top score clears a configurable `percentage`
threshold (default 40%). If nothing clears the threshold, it logs a warning
naming the top score found rather than silently returning a wrong element.
Ties (multiple elements at the same top score) are explicitly preserved and
returned together rather than arbitrarily picking one.

**Where this maps in AURA — this is the single strongest, most literal match
in all six batches:**
- This is functionally the same problem AURA's whole self-healing story
  (FR4/FR5 in `docs/PRD.md`, `orchestrator/healing_loop.py`,
  `agents/planner/diagnoser.py`) solves for vision/pixel targets — Scrapling
  solves it for DOM targets, with a genuinely reusable algorithm shape:
  score-every-candidate → threshold-gate → return-ties-not-guesses. Once
  Task 3's Playwright-based accessibility-tree path lands (Batch 1), a
  DOM-target self-heal step modeled directly on `relocate()`'s
  score-and-threshold approach — not a vision/OCR fallback — should be the
  first thing tried when a Playwright locator fails to resolve, before
  escalating to the pixel/vision path. This is a concrete, scoped addition to
  whatever module ends up owning the new Playwright-first location logic
  (see Batch 1's note on `agents/vision/locator.py`).
- The "log the top score even on failure, don't silently return nothing" UX
  choice is worth carrying over to AURA's own confidence-gating message shape
  (FR8 in `docs/PRD.md`).
- License: BSD-3-Clause (check `ext_Scrapling/LICENSE` before verbatim reuse
  — not independently re-verified this pass beyond the badge).

### 2. `tinyhumansai/openhuman`

**What it is:** a local-first personal AI "super intelligence" desktop app
(Tauri-based) with its own agent harness — not primarily an automation tool,
but its harness architecture doc is genuinely useful.

**Two adoptable patterns:**
1. **Path-gated conditional context loading** (`.claude/rules/README.md`):
   rule files are only added when they need to be loaded conditionally for a
   narrow part of the tree (via `paths:` frontmatter matching), explicitly
   to avoid every agent context being bloated with irrelevant rules — "each
   file added here ships in every agent context that matches its `paths:`
   glob, so keep them small, current, and non-overlapping." This is a
   scaling pattern AURA's own `context.md`/`docs/debug.md` don't need yet
   (repo is still small enough for one root context file) but is worth
   noting in `context.md` §6 as the pattern to adopt if/when AURA's doc set
   grows past what one root file can usefully summarize.
2. **Stop-hook middleware for loop guardrails**
   (`gitbooks/developing/architecture/agent-harness.md`): budget, thread-goal,
   and iteration caps are implemented as a `StopHookMiddleware` that "pauses
   the run on the first stop vote" — i.e., any one of several independent
   guardrail checks (budget exceeded, goal apparently met, iteration cap hit)
   can independently halt the loop, rather than one monolithic check.
   Directly comparable to `orchestrator/guardrails.py` — worth checking
   whether AURA's guardrails are structured as independently-voting checks or
   one combined condition; the former is more extensible (new guardrail =
   new independent check, no need to touch existing logic).
- License: not confirmed this pass — check before reuse beyond the pattern.

### 3. `langfuse/langfuse`

**What it is:** the most mature, widely-used open-source LLM observability
platform (traces, spans, generations, scores, evals).

**Core mechanism — directly reusable taxonomy**
(`packages/shared/src/domain/observations.ts`): a fixed `ObservationType` enum
— `SPAN`, `EVENT`, `GENERATION`, `AGENT`, `TOOL`, `CHAIN`, `RETRIEVER`,
`EVALUATOR`, `EMBEDDING`, `GUARDRAIL` — used to tag every logged unit of
agent activity, plus a separate `ObservationLevel` (`DEBUG`/`DEFAULT`/
`WARNING`/...) for severity independent of type.

**Where this maps in AURA:**
- `orchestrator/audit_logger.py` (writing to `logs/audit.jsonl`) currently
  has no documented fixed taxonomy for what kind of event each log line
  represents. Adopting a small, fixed set of event types modeled on
  Langfuse's (adapted to AURA's actual units of work: e.g. `VISION_ACTION`,
  `CAPABILITY_CHECK`, `PLANNER_DIAGNOSIS`, `SELF_HEAL`, `GUARDRAIL_STOP`,
  matching the `CapabilityType`/`ActionType` enums already in
  `orchestrator/schemas.py`) would make `logs/audit.jsonl` queryable and
  reportable in a structured way, and gives `reports/render.py` a stable
  vocabulary to group/filter on. Concrete, scoped, low-risk addition — flag
  in `docs/decisions.md` before implementing since it changes a logged data
  shape other tooling may depend on.
- License: MIT/Apache-2.0 dual-licensed per Langfuse's public licensing (not
  independently re-verified against this clone's LICENSE file this pass).

### 4. `alibaba/page-agent`

**What it is:** an in-browser (extension-based) web agent — its `PageController`
runs *inside* the page context itself (content script), not over CDP like
Playwright/agent-browser.

**Core mechanism** (`packages/page-controller/src/PageController.ts`):
`clickElement(index)`/`inputText(index, text)` operate against an
**index-based selector map** (`this.selectorMap`, populated by a separate DOM
indexing pass — `assertIndexed()` guards against calling before indexing
runs), with explicit handling for edge cases like `target="_blank"` anchors
(reports "opened in a new tab" rather than silently doing nothing), and
every action returns a structured `ActionResult` (`success`, `message`) —
errors are caught and returned as data, never thrown past the action
boundary.

**Where this maps in AURA:**
- Reinforces, from yet another independent implementation, the
  index/ref-based element addressing pattern already seen in Batch 1
  (agent-browser's `@eN` refs) and Batch 6 (Scrapling's relocate). Three
  independent projects converging on "assign short-lived stable indices to
  resolved elements, don't re-resolve from scratch every action" is strong
  evidence this belongs in AURA's `agents/vision/locator.py` redesign per
  Task 3.
- The **structured `ActionResult` with caught-and-returned errors** (never
  throwing past the action boundary) is a good, simple hardening check for
  `runtime/hooks/interact.py` and `agents/vision/executor.py` — worth a
  `docs/debug.md` pass specifically checking whether every action function
  already does this or lets exceptions propagate uncaught into
  `orchestrator/run_engine.py`.
- License: check `ext_page-agent/LICENSE` before verbatim reuse.

### 5. `tirth8205/code-review-graph`

**What it is:** a Tree-sitter-based structural code graph tool that gives AI
coding assistants precise, scoped context via MCP instead of re-reading whole
files/repos on every review — reports a 38x–528x token reduction across its
own benchmark repos (self-reported, not independently re-verified here).

**Core mechanism:** parses the codebase into a structural graph with
Tree-sitter, tracks changes **incrementally** (only re-parses what changed),
and exposes precise per-symbol/per-region context over MCP so an AI
assistant reads only the parts of the codebase relevant to the change at
hand, rather than whole files.

**Where this maps in AURA / this task specifically:**
- This is directly relevant to `docs/debug.md`'s own mandate ("review each
  and every file line by line... each time the AI updates the codebase") —
  as AURA's codebase grows, a full line-by-line pass over every file on every
  change becomes expensive. A Tree-sitter-based incremental graph (scoped to
  "what actually changed, plus its direct callers/callees" rather than every
  file) is the natural way to keep `docs/debug.md`'s checklist affordable at
  scale without weakening it. Recommend noting this as a candidate tooling
  addition in `docs/debug.md` itself — not a runtime AURA feature, a
  developer-tooling addition for whoever (human or AI) is applying
  `docs/debug.md`'s protocol.
- Not relevant to AURA's own product surface (`agents/`/`orchestrator/`) —
  scope this purely to the debug-protocol tooling question.
- License: check `ext_code-review-graph/LICENSE` before verbatim reuse.

---

## Batch status

- Batch 1 (Playwright/playwright-mcp, UI-TARS-desktop, agent-browser): **done**.
- Batch 2 (PixelRAG): **done**.
- Batch 3 (ponytail, TencentDB-Agent-Memory, cognee): **done**.
- Batch 4 (OpenManus, gbrain, Agent-Reach, q-agent-harness): **done**.
- Batch 5 (loop-engineering, pipecat, OpenSpace, PraisonAI): **done**.
- Batch 6 (Scrapling, openhuman, langfuse, page-agent, code-review-graph): **done**.
- **All 18 in-scope repos processed.** Excluded permanently: `G0DM0D3`,
  `FckSignups` (see top of file).

## Cross-cutting summary (read this before Task 3 implementation)

Three fully independent batches (1, 6, and page-agent within 6) converged,
without prompting, on the same core design: **resolve elements by a
stable reference/index, not by re-locating from raw pixels/selectors every
single action** — Playwright's accessibility-snapshot targets, agent-browser's
`@eN` refs, Scrapling's DOM `relocate()`, and page-agent's index-based
selector map. This is now a well-evidenced, multi-source-verified direction
for AURA's Task 3 navigation-logic migration, not a single repo's opinion.

For self-healing specifically: Scrapling's score-every-candidate +
threshold-gate + never-silently-guess pattern is the most directly portable
algorithm found across all six batches, and should be the template for a new
DOM-target self-heal step sitting alongside AURA's existing vision-based
self-heal, once Task 3's Playwright path exists to heal.

Do not extend this file with unverified content — if a future pass can't
actually fetch a repo, record that explicitly here rather than fabricating an
entry.
