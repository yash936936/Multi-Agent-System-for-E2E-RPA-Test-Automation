---
type: master-context
project: AURA (Multi-Agent-System-for-E2E-RPA-Test-Automation)
root_file: true
last_updated: 2026-07-23
---

# context.md — Master Orientation File

**Read this file first, every session, before touching any code.** This is the
single entry point for any AI agent (Claude or otherwise) working in this repo.
It tells you what the project is, where every doc lives, what each doc is for,
where real data/config comes from, and what the current priorities are. All
other `.md` files referenced below live in `/docs` unless noted otherwise.

If anything in this file conflicts with a doc it references, the more specific
doc wins for its own domain, but **you must update this file in the same pass**
so the conflict doesn't persist (see `docs/debug.md` §3).

---

## 1. What this project is

**AURA** — Autonomous Unified RPA Agent for Offline QA Test Automation. A
local-first, vision-driven multi-agent system that:
- turns plain-language requirement docs into structured test specs (Planner agent),
- executes UI tests by *looking at the screen* (screenshot → OCR → click/type),
  not brittle DOM selectors (Vision agent),
- generates synthetic test data including edge cases (Data Synth agent),
- self-heals when the UI drifts, and escalates only when it truly can't recover,
- runs entirely offline/on-device (no data egress) via a central "Hermes Agent
  API" tool-calling interface,
- is also growing a second surface: non-UI "capability adapters" (DB, API,
  email, file, Excel, PDF, cloud, SharePoint, chat-ops) plus a FastAPI service
  layer + web dashboard, for testing systems beyond browser UIs.

Two things are true at once and must not be conflated:
1. The original CLI tool (Phases 1–12) is complete, tested, and the
   recommended way to run AURA today.
2. The "universal platform" backend (Phases 13–19) is real code, but the
   service layer has known, documented gaps — see `docs/STATUS.md` before
   assuming anything in `api/` or `webui/` works end-to-end.

---

## 2. Directory map — what's authoritative, what's not

```
/context.md              ← you are here. Root-level. ONLY .md file in root.
/docs/                   ← ALL narrative docs live here (per this task's requirement)
  README.md              ← project readme (moved here from root — see note below)
  PRD.md                 ← product requirements (CLI scope only — see its own 2026-07-04 note)
  TRD.md                 ← technical requirements / architecture
  WORKFLOW.md            ← agent-to-agent workflow / Hermes Agent API contract
  APPFLOW.md             ← user-facing app flow (CLI + web)
  PROJECT_OVERVIEW.md    ← condensed project summary
  STATUS.md              ← CURRENT STATE. Overwritten each pass, not accumulated. READ THIS FIRST for "is X actually working."
  Roadmap.md             ← phased plan, Phases 1–19, with an explicit "what's real today" table
  PHASES.md              ← phase breakdown detail
  decisions.md           ← architecture decision log (why, not just what)
  progress.md            ← accumulated changelog (append-only, unlike STATUS.md)
  debug.md               ← MANDATORY debug protocol, run on every code change (see below)
  debug_report.md        ← GENERATED artifact from `aura debug <path>` (ruff-backed static analysis). Not hand-maintained — regenerate, don't hand-edit.
  external_repos.md      ← extracted logic/snippets from external reference repos (see §5) — all 6 batches / 18 repos complete
/agents/                 ← the actual sub-agents: planner, vision, capability, data_synth, auditor
/orchestrator/           ← Hermes-Agent-API-style kernel: run_engine, healing_loop, memory, skill_store, guardrails, capability_router
/api/                    ← FastAPI service layer (Phase 17) — check docs/STATUS.md for what's actually wired
/aura/                   ← CLI entry point and commands (aura/main.py, aura/cli/*)
/runtime/hooks/          ← low-level OS interaction: browser.py, capture.py, interact.py (screenshot/click/type primitives)
/config/                 ← settings.py (canonical paths/config), tool_registry.yaml (adapter registry), local_config.json, users.json, vault.key
/reports/                ← report rendering (render.py + Jinja templates)
/tests/                  ← pytest suite — the ground truth for "does it actually work"
/webui/                  ← static dashboard (templates/static) served by api/main.py
/target_app/             ← demo app used for local testing
/requirements_input/     ← example input requirement docs (example_login_flow.md) — FUNCTIONAL DATA, not project documentation, deliberately NOT moved to /docs (see exception below)
```

**Exception to the "everything moves to /docs" rule:** `requirements_input/example_login_flow.md`
is real input data consumed by the Planner agent at a path other code may
reference — it is a test fixture, not a narrative doc about the system.
Moving it would risk breaking whatever expects it at that path for no
documentation benefit. It stays where it is. If this reasoning ever stops
applying (e.g. the path becomes configurable), update this note and §4.

**`docs/README.md` note:** the project README was moved into `/docs` along
with everything else per this task's explicit instruction ("only keep
context.md in the root repo"). This is a deviation from the common
convention of keeping `README.md` at repo root for GitHub's auto-render —
if this repo is pushed somewhere that expects a root README (e.g. GitHub's
repo landing page), that's a real tradeoff to flag back to a human, not
something to silently work around.

---

## 3. Doc-by-doc guide: purpose, source of truth, when to update

| Doc | Purpose | Update it when... |
|---|---|---|
| `docs/README.md` | Project readme (setup, CLI reference, install) — moved from root per this task | New CLI command, new setup step, new dependency a fresh clone needs |
| `docs/PRD.md` | Product requirements, goals, non-goals, user stories, FR1–FR13, success metrics — **CLI scope only** | Product scope/requirements change. Note: still needs a v2.2 section for the capability-adapter/service surface per `docs/STATUS.md`'s "Needs review." |
| `docs/TRD.md` | Technical architecture / design | Architecture changes (new agent, new adapter pattern, new orchestration mechanism) |
| `docs/WORKFLOW.md` | How agents communicate via the Hermes Agent API (tool-calling contract) | The tool-calling interface or agent registration pattern changes |
| `docs/APPFLOW.md` | End-user flow through CLI and/or web UI | A new CLI command or dashboard view is added |
| `docs/PROJECT_OVERVIEW.md` | Short summary for newcomers | Rarely — only on major scope shifts |
| `docs/STATUS.md` | **Ground truth for "what works right now."** Overwrite, don't accumulate. | Every single pass that changes code. This is the file to read before trusting any other doc's claims. |
| `docs/Roadmap.md` | Phased plan + "what's real today" table (§1 of that file) | A phase completes, or scope is re-sequenced |
| `docs/PHASES.md` | Phase-level detail backing the roadmap | Same cadence as Roadmap.md |
| `docs/decisions.md` | Why choices were made (architecture decision records) | Any non-obvious technical decision, especially ones that reject an alternative |
| `docs/progress.md` | Append-only changelog, dated entries | Every pass — append, never rewrite history |
| `docs/debug.md` | **Mandatory checklist run before any code change is considered done** | Only when the debug process itself needs to evolve |
| `docs/debug_report.md` | **Generated** output of `aura debug <path>` (ruff-backed static analysis) | Never hand-edit — regenerate by re-running the command. Stale copies should be deleted, not edited. |
| `docs/external_repos.md` | Extracted, verified code/logic pulled from external reference repos, mapped to where it's used in AURA | Whenever a new external repo is reviewed per §5 below (currently: all 18 in-scope repos done) |

---

## 4. Where data actually comes from (don't assume, check these)

- **Config / settings:** `config/settings.py` is canonical. Don't hardcode a
  path that already has a settings entry.
- **Tool/adapter registry:** `config/tool_registry.yaml` + `orchestrator/capability_adapter.py::default_registry()`. A capability adapter is only "real" if it's registered in **both** places plus has a `CapabilityType` entry in `orchestrator/schemas.py` — three-way consistency is a known historical failure mode (see `docs/debug.md` §2.4).
- **Requirement docs (input to the Planner agent):** `requirements_input/*.md`, e.g. `example_login_flow.md`.
- **Secrets/credentials:** `config/vault.key` via the vault mechanism referenced in `docs/STATUS.md` (note the documented gap: Fernet key currently doubles as JWT signing secret — don't build new secret-dependent features on that without flagging it).
- **Users (API auth):** `api/user_store.py`, JSON-file backed.
- **Persistent run history (API):** `api/run_store.py`, SQLite (`memory/api_runs.db`).
- **Skill memory (self-healing reuse):** `orchestrator/skill_store.py`, backed by `orchestrator/skills_store/`.
- **General agent memory:** `orchestrator/memory.py`, backed by `orchestrator/memory_store/`.
- **Screenshots / audit logs:** `runtime/screenshots/`, `logs/audit.jsonl` via `orchestrator/audit_logger.py`.
- **Test ground truth:** `tests/` — pytest is the actual source of truth for "does this work," not any doc's prose claim.

---

## 5. External repo extraction — COMPLETE (all 18 in-scope repos, 6 batches)

We are extracting reusable logic/snippets from external reference repos into
`docs/external_repos.md`, one small batch at a time, with each extraction
verified against the real repo content (not guessed). Two repos from the
original list are **excluded on purpose**:

- `elder-plinius/G0DM0D3` — excluded. By name/author pattern this reads as
  model-safeguard-removal ("jailbreak") tooling, not a legitimate library for
  "molding an LLM for our purpose." Not pulled into this codebase.
- `BraveOPotato/FckSignups` — excluded. By name this reads as a signup/verification-bypass
  tool. Not pulled into this codebase; AURA's own capability-router design already
  covers legitimate multi-step form automation without needing bypass tooling.

Remaining repos are being processed in batches of 3–4, each batch appended to
`docs/external_repos.md` with: what was actually found in the repo, the
specific snippet/pattern extracted, and which AURA file it's intended to
inform or update. **Do not fabricate an extraction** — if a repo can't be
verified/fetched, say so in that file rather than inventing plausible-sounding
code.

**Batch 1 — done** (2026-07-13): `microsoft/playwright` (+ `playwright-mcp`,
whose source actually lives in the playwright monorepo), `bytedance/UI-TARS-desktop`,
`vercel-labs/agent-browser`. See `docs/external_repos.md` for verified
findings. Headline results: Playwright's accessibility-snapshot-first
targeting pattern (`browser_snapshot`/`browser_click` in
`packages/playwright-core/src/tools/backend/snapshot.ts`) should become
AURA's primary element-location path for browser targets, with the existing
pixel/OCR vision path as fallback for native desktop targets only. UI-TARS's
`actionParser.ts` coordinate-normalization math (`smartResizeForV15`) is the
right base for hardening `agents/vision/locator.py`'s pixel path. agent-browser's
`@eN` ref-based element addressing reinforces the same "resolve by reference,
not raw pixels" direction.

**Batch 2 — done** (2026-07-13): `StarTrail-org/PixelRAG`. Important
correction recorded in `docs/external_repos.md`: PixelRAG is a visual-RAG
*screenshot-reading* system (render page/PDF → tiled images → vision-model
read/search), not a cursor/click tool — the original task bullet conflated
"navigating the cursor, clicking, and reading on-screen text" but only the
reading part lives in this repo. Cursor/click logic is covered by Batch 1.
Headline result: tile screenshots to the target vision model's downscale
threshold (1568px long edge for Claude Sonnet/Haiku) before OCR/vision-model
read, use load+network-idle wait before capture (independent confirmation of
the Playwright-based fix already planned for the link-checker), and
crop-and-zoom on low-confidence regions before escalating to human review.

**Batch 3 — done** (2026-07-13): `DietrichGebert/ponytail`,
`TencentCloud/TencentDB-Agent-Memory`, `topoteretes/cognee`. See
`docs/external_repos.md` for full findings. Headline results:
- **ponytail** is a code-minimalism *prompting/hook pattern* for AI
  contributors (not a runtime library) — its 7-rung "does this need to exist
  → can this be one line" decision ladder and its rule that deliberate
  corner-cuts must be marked inline (never silently shipped) should be folded
  into `docs/debug.md` as a pre-code-change step. Not applicable to AURA's
  `agents/`/`orchestrator/` runtime code itself.
- **TencentDB-Agent-Memory** — two-tier memory (symbolic short-term log
  compression + layered long-term "persona/scene" memory), run as an HTTP
  sidecar. Relevant to `orchestrator/memory.py`/`orchestrator/audit_logger.py`
  as a future design direction, not an immediate rewrite. **Naming flag:**
  this repo's own "Hermes" (a third-party agent gateway) is unrelated to
  AURA's "Hermes Agent API" — same name, different systems, noted so nobody
  conflates them later.
- **cognee** — knowledge-graph-backed agent memory with a clean
  `remember`/`recall`/`forget` verb-shaped API. Most relevant to
  `docs/PRD.md` FR11 / `docs/Roadmap.md` Phase 3 ("local failure-memory
  index") if AURA later wants relational reasoning over past failures rather
  than flat key lookup — flagged as a Phase-3 option, not a current change.

**Batch 4 — done** (2026-07-13): `OpenManus`, `gbrain`, `Agent-Reach`,
`q-agent-harness`. Note: `OpenManus` (listed as "local LLM training") and
`gbrain` (listed as "our main LLM brain") were both corrected on inspection —
neither does what the original task bullet claimed; see
`docs/external_repos.md` for what they actually are and what's genuinely
reusable (OpenManus's stuck-loop detection for `orchestrator/guardrails.py`;
gbrain's compiled-truth + append-only-timeline knowledge model for
`orchestrator/skill_store.py`/`memory.py`). `Agent-Reach`'s `doctor()` health-check
pattern is comparable to `aura/cli/preflight.py`. `q-agent-harness`'s explicit
approval-tier list (allowed-without-approval vs. requires-approval actions)
is directly adoptable into this file's §6.

**Batch 5 — done** (2026-07-13): `loop-engineering`, `pipecat`, `OpenSpace`,
`PraisonAI`. Headline results: loop-engineering's tiered loop-autonomy model
(report-only / bounded-auto-fix / human-gated, plus a `loop-pause-all` kill
switch) is a good frame for AURA's `--yes`/`--interactive` modes and
`aura/cli/schedule_cmd.py`. pipecat is a genuinely new capability (real-time
conversational pipeline) relevant only if voice/narration becomes an actual
roadmap item — flagged as new scope, not a hardening. OpenSpace's skill
quality-tracking (`skill_engine/analyzer.py`) is a concrete addition for
`orchestrator/skill_store.py`. PraisonAI's bounded `min_reflect`/`max_reflect`
with an optional separate cheaper `reflect_llm` is directly comparable to
`agents/planner/cross_modal_diagnoser.py`'s heal-attempt bound.

**Batch 6 — done** (2026-07-13, final batch): `Scrapling`, `openhuman`,
`langfuse`, `page-agent`, `code-review-graph`. **Scrapling's `relocate()`
(score-every-candidate, threshold-gate, never-silently-guess DOM self-healing)
is the single strongest, most directly portable match found across all six
batches** — template for a new DOM-target self-heal step once Task 3's
Playwright path exists. langfuse's fixed `ObservationType` taxonomy
(SPAN/EVENT/GENERATION/AGENT/TOOL/CHAIN/RETRIEVER/EVALUATOR/EMBEDDING/GUARDRAIL)
is a good model for giving `orchestrator/audit_logger.py` a structured event
vocabulary. openhuman's stop-hook-middleware pattern (independent voting
guardrail checks) is worth comparing against `orchestrator/guardrails.py`'s
actual structure. page-agent independently reinforces the index/ref-based
element-addressing direction (see cross-cutting note below).

**All 18 in-scope external repos have now been processed.** Full detail,
including corrections where a repo didn't match its original task
description, license notes, and exact file paths cited, lives in
`docs/external_repos.md`. Excluded permanently: `G0DM0D3`, `FckSignups`.

**Cross-cutting finding for Task 3:** three independent batches (Playwright/
agent-browser in Batch 1, Scrapling in Batch 6, page-agent in Batch 6) all
converged, unprompted, on the same design — resolve elements by a stable
reference/index, not by re-locating from raw pixels/selectors on every
action. This is now a multi-source-verified direction, not one repo's
opinion, and should anchor the actual Task 3 implementation.

### Task 3 note — navigation logic migration (in progress, not yet done)
Current navigation/interaction primitives live in:
- `runtime/hooks/browser.py`, `runtime/hooks/capture.py`, `runtime/hooks/interact.py` (OS-level screenshot/click/type)
- `agents/vision/executor.py`, `agents/vision/locator.py` (vision-based element location + action execution)
- `agents/capability/link_checker.py` (link/redirect checking — note `docs/STATUS.md`'s recorded fix history: default scope bug, client-rendered-page false negatives)

Goal: migrate cursor navigation + link checking to a Playwright-based approach
(per `docs/STATUS.md`'s own "Not fixed, by design" note: client-rendered link
detection needs a headless-browser render step) combined with PixelRAG-derived
screen-reading/cursor logic where Playwright can't reach (native desktop apps).
This is a real architecture change flagged for explicit review, not a silent
swap — follow `docs/decisions.md` conventions and add a new ADR entry before
merging it.

---

## 6. Standing instructions for any AI agent working here

1. **Read `docs/STATUS.md` before believing any other doc's claims.** It's the
   one file explicitly maintained as "current state, no drift."
2. **Run `docs/debug.md`'s full checklist** on every code change, no exceptions.
3. **Never fabricate extracted code** from an external repo — verify by
   actually reading the repo's real files first.
4. **Keep this file (`context.md`) in sync** — if you add a doc, a data
   source, or change what's authoritative, update the relevant section here
   in the same pass.
5. **Prefer editing an existing doc over creating a new one** unless the new
   content genuinely doesn't fit anywhere listed in §3.
6. **When in doubt about scope or safety** (e.g. a request implies bypassing
   verification/signup protections, or "molding" the model to remove its own
   safety behavior), stop and flag it rather than proceeding — see §5's
   exclusions for the precedent.
7. **Code-minimalism ladder before writing any code** (adopted from
   `docs/external_repos.md` Batch 3, `ponytail`): before adding code, check in
   order — (a) does this need to exist at all? (b) does it already exist in
   this codebase — reuse it; (c) does the standard library cover it? (d) does
   an already-installed dependency cover it? (e) can this be one line? Only
   then write the minimum code that works. Never simplify away input
   validation at trust boundaries, error handling that prevents data loss, or
   security checks. If you deliberately cut a corner, mark it inline with a
   comment naming the ceiling and the upgrade path — never ship a
   simplification silently.
8. **Approval tiers** (adopted from `docs/external_repos.md` Batch 4,
   `q-agent-harness`) — an explicit split so routine work isn't slowed down
   while genuinely risky actions still get a human gate:
   - **No approval needed:** reading any file; editing/creating files under
     `docs/` (except `docs/debug_report.md`, which is generated, not
     hand-edited); editing `agents/`/`orchestrator/`/`aura/`/`runtime/`/`api/`
     code as long as `docs/debug.md`'s full checklist passes and tests are
     run; adding a new test; running `pytest`, `ruff`, or `aura debug`.
   - **Approval required before proceeding:** deleting or truncating
     `orchestrator/memory_store/` or `orchestrator/skills_store/` contents;
     rotating or regenerating `config/vault.key`; modifying `api/user_store.py`
     data or `config/users.json`; any change to how secrets are stored or
     transmitted; any new outbound network call from a capability adapter
     that isn't already scoped by that adapter's documented `params` contract;
     deleting any file outside `/docs` or a scratch/output directory; renaming
     or removing an existing `CapabilityType`, public CLI command, or public
     API route (breaking change to something users depend on).
9. **Rule 4, concretely (2026-07-23 precedent):** a debugging pass merged
   real fixes into `main` (`ActionType.ASSERT` branch,
   `LinkCheckAdapter.live_page_html`) with zero `docs/decisions.md` entry,
   while `docs/STATUS.md`'s "Next action" kept pointing at a phase (T)
   that had been done for 10+ phases. Neither doc was wrong about the
   code *before* those fixes — they just weren't updated *in the same
   pass* as the fixes, which is exactly what rule 4 exists to prevent.
   See `docs/decisions.md` D-055/D-056 and the corrected `docs/STATUS.md`
   "Next action" for the fix. Don't repeat this: if you merge a fix,
   write its decision entry and correct any doc pointer it invalidates
   before ending that pass, not "in a follow-up."
