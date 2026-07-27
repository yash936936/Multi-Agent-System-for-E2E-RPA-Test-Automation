# AURA Brain — Unified Core Architecture

> **Note (2026-07-27):** `aura/cli/explore_cmd.py` and the `"explore"`
> intent used throughout this document as the running example for "how
> a single entrypoint gets migrated onto the Brain" have since been
> removed entirely (the CLI's zero-instruction explore mode was
> retired — see `docs/STATUS.md`'s 2026-07-27 entry). The architectural
> narrative below is kept as-is because it's still the accurate history
> of *why* the Router/Policy pattern looks the way it does — `"explore"`
> was Phase B1's pilot migration case, and every subsequent phase
> (B2/B3, closing out at D-079/D-080) built on that same pattern to
> migrate the remaining intents, which are the ones that actually exist
> today: `execute_spec`, `execute_prompt`, `execute_interactive`,
> `ui_audit`, `capability_check`. Read every `"explore"` reference below
> as "the intent that piloted this pattern, since removed," not as
> current, runnable code.

Companion to `AURA_REARCHITECTURE_PLAN.md`. That plan fixes specific
subsystems (dispatch, change-detection, logging). This document answers
a different question underneath all of them: **why did each of those
subsystems drift out of sync with each other in the first place**, and
proposes the structural fix — a single decision-making core ("the
Brain") that every entrypoint routes through, plus an external knowledge
folder it reads its policy from instead of policy being hardcoded and
duplicated across files.

---

## 1. The actual problem, named precisely

This isn't "the code is messy." It's specific and structural:

- **`aura/cli/explore_cmd.py`** hand-assembles its own pipeline:
  `browser.open_url` → `run_autoscan` → `run_exploration` → prints. It
  decides DOM-vs-OCR readiness itself (checks `dom_page is not None`
  inline), decides retry posture itself, decides what counts as "clean"
  itself.
- **`aura/cli/execute_cmd.py`** hand-assembles a *different* pipeline for
  a related job: `RunEngine.run`/`run_spec`, its own DOM-first checks
  inside `run_engine.py`'s `WAIT_FOR_HUMAN_ACTION` branch, its own
  retry/escalation via `guardrails.py` + `healing_loop.py`.
- **`agents/planner/spec_generator.py`** has a *third* independent retry/
  escalation ladder (`HermesAgentBackend` → retry → `CloudLLMBackend`),
  unrelated in code to `guardrails.py`'s retry logic even though both are
  answering the same question ("try again or give up?").
- **`api/routers/runs.py`** presumably reimplements a fourth variant of
  "how does a run actually get executed" for the REST surface.
- The DOM-first-vs-OCR-fallback condition (`dom_page is not None`) is
  checked independently in `ui_audit_runner.py`, `run_engine.py`, and
  (per this plan's Phase 2) will need to be checked in
  `dom_extractor.py`/`ui_audit.py` too — four places asking the same
  question with no shared function.
- Retry/backoff numbers, confidence thresholds, vocab lists, band
  boundaries, timeout defaults are Python literals scattered through
  `ui_audit.py`, `assertions.py`, `guardrails.py`, `config/settings.py`,
  `http_retry.py` — changing "how cautious should AURA be" today means
  hunting through 6+ files, not one.

**The fix is not a bigger `orchestrator/kernel.py`.** `ToolRegistry`
already exists and does its one job well (validate + dispatch + audit a
tool call) — it's infrastructure, not a decision-maker; it doesn't know
*when* to call `Planner.generate_spec` vs skip straight to a cached
skill, or *when* to fall back to OCR. Nothing in the codebase owns that
layer today. That's the Brain.

---

## 2. The Brain — design

### 2.1 One entrypoint, one Intent type

```
orchestrator/brain/
    __init__.py
    brain.py          # AuraBrain — the single class every entrypoint calls
    intent.py         # Intent dataclass + the fixed set of intent kinds
    policy.py         # every "should I do X or Y" decision, in one place
    router.py         # intent -> which existing subsystem actually does the work
    context.py        # loads brain_knowledge/ at startup, hot-reloadable
```

```python
# orchestrator/brain/intent.py
@dataclass
class Intent:
    # Originally "explore" was listed first here as Phase B1's pilot
    # case (see the note at the top of this document) -- it's since
    # been removed, along with the CLI command it backed.
    kind: Literal["execute_spec", "execute_prompt",
                   "execute_interactive", "ui_audit", "capability_check"]
    params: dict[str, Any]          # url, prompt, spec_path, timeout, etc.
    caller: Literal["cli", "api", "slack_tag"]   # who's asking, for audit only
```

```python
# orchestrator/brain/brain.py
class AuraBrain:
    def __init__(self, knowledge: BrainKnowledge | None = None):
        self.knowledge = knowledge or BrainKnowledge.load()
        self.policy = Policy(self.knowledge)
        self.router = Router(self.policy)

    def handle(self, intent: Intent) -> BrainResult:
        run_id = self._new_run_id(intent)
        with unified_run_logger(run_id, intent):     # Phase 1's unified logging, automatic
            plan = self.router.resolve(intent)         # which subsystem(s), in what order
            result = plan.execute(self.policy)          # policy object threaded through, not re-decided per subsystem
        return BrainResult(run_id=run_id, ...)
```

**Every CLI command, every API route, and Slack Tag all become thin
adapters that build an `Intent` and call `AuraBrain().handle(intent)`.**
`aura/cli/explore_cmd.py` stops independently deciding anything — it
becomes ~15 lines: parse args, build `Intent(kind="explore", ...)`, call
the Brain, render `BrainResult` to the terminal. Same for
`execute_cmd.py`, same for `api/routers/runs.py`. This is the literal
fix for "AURA is divided into multiple parts that aren't connected even
when they have the same task" — there stops being more than one place
that *can* decide "DOM-first or OCR fallback," because `policy.py` is
the only thing that answers that question, and every router/executor
calls into it instead of re-deriving the answer locally.

### 2.2 `policy.py` — every cross-cutting decision, in one place

This absorbs the decisions currently duplicated across files:

```python
class Policy:
    def discovery_source(self, dom_page) -> Literal["dom", "ocr"]:
        """The ONE place `dom_page is not None` gets checked. Every
        subsystem (ui_audit_runner, run_engine, dom_extractor) calls
        this instead of checking the condition itself."""

    def change_detection_method(self, dom_page) -> Literal["mutation_observer", "hash_diff"]:
        """Same shape as discovery_source, deliberately -- one rule
        governs both fallbacks (see AURA_REARCHITECTURE_PLAN.md Phase 6)."""

    def retry_policy(self, operation_kind: str) -> RetryPolicy:
        """Replaces the three independent retry ladders (spec_generator's
        Hermes->Cloud escalation, guardrails.py's evidence-fingerprint
        short-circuit, http_retry.py's backoff) with one lookup against
        brain_knowledge/rules/retry.yaml, parameterized by operation kind
        ('llm_call', 'click_dispatch', 'network_capability'). The three
        call sites keep their own mechanics (an LLM retry and an HTTP
        retry aren't the same code) but stop hardcoding their own
        thresholds -- they ask Policy for the numbers."""

    def confidence_threshold(self, check_kind: str) -> float:
        """Replaces scattered magic numbers in assertions.py/ui_audit.py."""

    def is_interactive_element(self, dom_signal, ocr_signal) -> tuple[bool, str]:
        """The vocab-list + DOM-cross-check logic from today's session,
        as one policy function with a disclosed reason string -- this is
        what aura explain's red/green overlay reads directly."""
```

`Policy` loads its numbers/vocab/thresholds from `brain_knowledge/rules/`
(section 3 below) rather than from Python literals — so tuning AURA's
behavior is a data change, reviewable in a diff, not a code change
scattered across files.

### 2.3 `router.py` — intent to existing subsystems

The Brain does **not** reimplement `RunEngine`, `ui_audit_runner`,
`spec_generator`, or the capability adapters. Those stay exactly what
they are — the "hands." The router's only job is: given an `Intent`,
build the right call sequence into those existing modules, with the
`Policy` object threaded through instead of each module deciding
independently.

```
Intent("explore")           -> Router: autoscan (if requested) -> ui_audit_runner.run_exploration(policy=...)
Intent("execute_spec")      -> Router: spec_validator -> RunEngine.run_spec(policy=...)
Intent("execute_prompt")    -> Router: spec_generator.generate_spec(policy=...) -> RunEngine.run_spec(policy=...)
Intent("execute_interactive") -> Router: RunEngine.run_spec(policy=...) with a WAIT_FOR_HUMAN_ACTION step
Intent("ui_audit")          -> Router: ui_audit_runner.run_click_audit(policy=...)
Intent("capability_check")  -> Router: ToolRegistry dispatch directly (already a clean contract, kept as-is)
```

This also gives AURA something it structurally can't do today: an
`execute_prompt` intent and an `explore` intent can now share the same
click-audit/change-detection machinery, because both route through the
same `Policy`-driven subsystem calls instead of `execute_cmd.py` and
`explore_cmd.py` each maintaining separate, silently-diverging copies of
"how do I click something and tell if it worked."

### 2.4 What does *not* move into the Brain

To avoid rebuilding the exact fragmentation problem one layer up:
`RunEngine`, `ui_audit_runner`, `dom_extractor`, capability adapters,
`healing_loop`, `SkillStore` all keep their current internal logic and
public functions. They gain one new parameter (`policy: Policy`) and
lose the local copies of decisions `Policy` now owns. The Brain is a
coordination layer, not a rewrite of everything underneath it — this
keeps the migration mechanical (thread a parameter, delete a duplicated
`if dom_page is not None` block) rather than a full rewrite.

---

## 3. The memory/knowledge folder

A new top-level directory, **`brain_knowledge/`** (deliberately not
named `memory/` — that name is already taken by
`orchestrator/memory.py`'s `RunMemoryStore`, which is per-run SQLite
history, a completely different thing; reusing the name would recreate
exactly the kind of ambiguity this whole redesign is trying to remove).

```
brain_knowledge/
    context.md              # what AURA is, current architecture map, kept短 and current
    guidelines.md           # non-negotiable behavioral rules the Brain enforces
    rules/
        discovery.yaml       # dom-first/ocr-fallback condition + OCR vocab lists (moved out of ui_audit.py)
        change_detection.yaml # mutation vs hash-diff condition + noisy-node denylist
        retry.yaml            # per-operation-kind retry/backoff/escalation thresholds
        confidence.yaml        # per-check-kind confidence thresholds
        bands.yaml              # nav/hero/footer boundary fractions (currently _NAV_BAND_END etc.)
    playbooks/
        execute.md            # step-by-step decision tree the Brain follows for "execute_spec"/"execute_prompt" intents
        execute_interactive.md
        ui_audit.md
    prompts/
        planner_system_prompt.txt      # extracted verbatim from spec_generator.py's inline strings
        planner_retry_prompt.txt
        requirement_grounding_prompt.txt
    CHANGELOG.md             # every edit to this folder, dated -- this folder is reviewed like code
```

**Why a folder, not more Python:**
- `rules/*.yaml` are data, loaded by `Policy` at startup (with a
  `--reload-knowledge` dev flag / file-watch for iteration without a
  restart). Changing a confidence threshold or adding a vocab word
  becomes a one-line YAML diff, reviewable by a non-engineer, instead of
  a Python PR touching `ui_audit.py`.
- `playbooks/*.md` are the human-readable version of what `router.py`
  encodes in code — kept in sync by extending the project's existing
  `scripts/check_doc_drift.py` to diff a playbook's declared step list
  against the router's actual call sequence for that intent (mechanical,
  same posture as `check_silent_excepts.py`).
- `prompts/*.txt` get the LLM prompt text out of `spec_generator.py`
  entirely — versionable, diffable, and testable independently (a prompt
  regression test can load the file directly instead of importing
  Python and regexing a docstring).
- `guidelines.md` is the one file a human edits most: the plain-English
  version of "AURA must never do X" (e.g. "never treat an unconditional
  go_back() as evidence of anything," "never silently swallow an
  exception without a log line," "OCR is always the fallback, never the
  primary source when a DOM page exists") — each guideline gets an ID
  (`G-001`, ...) that `Policy` functions reference in their docstrings,
  the same way `decisions.md`'s `D-0xx` IDs already work, so "why does
  the Brain behave this way" always traces to one sentence in one file.
- `context.md` is intentionally short (under ~200 lines) — a living
  architecture map (what each `agents/`/`orchestrator/` module actually
  does, one line each), not a duplicate of `docs/decisions.md`'s
  chronological history. It's what you'd hand a new engineer (or a new
  Claude session) instead of asking them to read 3,700 lines of
  `decisions.md` to understand current shape.

**Relationship to existing docs:** `docs/decisions.md` stays exactly
what it is — the append-only historical log of *why* each change
happened. `brain_knowledge/` is the current, living, machine-and-human-
readable *state* the Brain actually runs on. One is history, one is
policy; they're allowed to disagree with each other (a decision from six
months ago may have been superseded), which is precisely the confusion
today's single accreted `decisions.md` file currently can't represent.

---

## 4. How this changes the previous plan's phases

`AURA_REARCHITECTURE_PLAN.md`'s phases don't get thrown out — they get
a home:

- **Phase 2 (DOM-first dispatch)** becomes: build `Policy.discovery_source()`
  and `Policy.is_interactive_element()`, backed by `rules/discovery.yaml`;
  every existing DOM-first check in `ui_audit_runner.py`/`run_engine.py`
  gets replaced with a call to `policy.discovery_source(dom_page)`
  instead of its own inline condition.
- **Phase 4 (MutationObserver)** becomes: `Policy.change_detection_method()`,
  backed by `rules/change_detection.yaml`, same treatment.
- **Phase 1 (unified logging + `aura explain`)** becomes the Brain's
  `unified_run_logger` context manager — every intent handled by
  `AuraBrain.handle()` gets timeline logging automatically, instead of
  each CLI command remembering to wire it up itself.
- **New phase, inserted first:** build `orchestrator/brain/` +
  `brain_knowledge/` skeleton with `Intent`/`Policy`/`Router` as thin
  pass-throughs to *today's* existing code paths (no behavior change
  yet) — this is the scaffolding everything else in both plans then
  slots into, and it's low-risk because it changes nothing about what
  runs, only *who calls what*.

### Revised phase order

| Phase | What | Depends on |
|---|---|---|
| 0 | Fixture tier (unchanged from prior plan) | — |
| **B1** | **Brain scaffolding**: `Intent`/`Policy`/`Router`/`brain_knowledge/` skeleton, CLI commands thinned to call `AuraBrain.handle()`, zero behavior change (pass-through only) | 0 |
| **B2** | **Rule extraction**: move vocab lists, band boundaries, confidence thresholds, retry numbers out of Python into `brain_knowledge/rules/*.yaml`, `Policy` reads them | B1 |
| **B3** | **Remaining-intent migration**: move `execute_spec`/`execute_prompt`/`execute_interactive`/`ui_audit`/`capability_check` onto `Router` — **done, 2026-07-25 (D-075)**. See §5.1 for the two design decisions this needed beyond B1's mechanical pattern (callback injection instead of an event-stream redesign; `ui_audit`/`capability_check` became real standalone commands) | B1, B2 |
| 1 | Unified logging + `aura explain`, now implemented as the Brain's logger | B1 |
| 2 | DOM-first dispatch, now implemented as `Policy.discovery_source()` | B1, B2 |
| 3 | Remove OS-mouse dependency | 2 |
| 4 | MutationObserver, as `Policy.change_detection_method()` | 2, 3 |
| 5 | CLI spinners (now live inside the Brain's shared status reporting, one implementation for every intent) | B1 |
| 6 | Docs, including `brain_knowledge/context.md` and `playbooks/` as first-class deliverables, not an afterthought | all above |

Everything downstream of B1/B2 gets *simpler* to implement than in the
original plan, because there's now exactly one place (`Policy`) to put
each decision instead of hunting down every duplicate.

---

## 5. Risk this design deliberately avoids

A "Brain" that becomes a second, competing implementation of
`RunEngine`/`ui_audit_runner` internals would make things worse, not
better — that's the exact fragmentation problem restated one layer up.
This design is deliberately narrow: the Brain owns **intent routing and
cross-cutting policy decisions only**; every actual capability (click,
verify, generate a spec, heal, check a link) stays owned by the module
that already owns it today. If a future decision needs new logic that
doesn't fit "which existing subsystem, with what policy inputs," that's
a sign it belongs in one of the hands, not in the Brain — worth stating
explicitly in `guidelines.md` itself (`G-000`, effectively) so this
doesn't regress the next time someone's tempted to add "just one more
thing" to `brain.py`.

### 5.1 — B3 was a materially bigger task than B1 — resolved 2026-07-25 (D-075)

Confirmed by reading the actual code before writing any migration code
(not assumed from B1's pattern generalizing cleanly): B3 was not five
mechanical repeats of B1's `_handle_explore()` move. Two real
complications were found by tracing the actual call graph, and both are
now resolved — this section is kept as the record of *why* the
resolution looks the way it does, not as an open question anymore.

1. **`execute_spec`/`execute_prompt`/`execute_interactive` are
   rendering-entangled in a way `explore` never was.**
   `aura/cli/execute_cmd.py::_run_requirement_text()` (the shared core
   behind three of the five "intents") passes `on_step_start`/
   `on_step_result`/`on_skill_learned` callbacks directly into
   `RunEngine`, and those callbacks call straight into `live_view`
   (rendering) *during* the run, not after it. `explore()`'s
   pre-migration logic, by contrast, only ever rendered from a
   completed report *after* the whole run finished — there were no
   live per-step callbacks to separate out. Moving
   `_run_requirement_text()` into `Router` as-is would mean the Router
   does rendering, which is exactly the boundary §5 above says not to
   cross.

   **Resolved: callback injection, not an event-stream redesign.** The
   CLI still builds every closure (now also including `approve_spec`
   for the spec-approval checkpoint, `confirm_heal_accept` for the
   heal accept/reject checkpoint, and `on_scan_progress`/`on_waiting`
   for the optional-pass and interactive-wait progress messages) and
   passes them through `Intent.params`; `Router` forwards them to
   `RunEngine`/the approval points unchanged and never imports or
   calls `live_view` itself. An event-stream redesign was rejected as
   the wrong-sized fix: it would mean modifying `RunEngine` itself (a
   "hand," not the Brain's to reimplement) for a problem callback
   injection solves without touching it at all.

2. **`ui_audit` and `capability_check` were not actually standalone CLI
   entrypoints**, despite being listed as their own `IntentKind` values
   in `orchestrator/brain/intent.py`. `ui_audit` was a boolean flag
   threaded through `_run_requirement_text()`'s shared core, not a
   separate code path; `capability_check` had no CLI command at all —
   only reachable as a `CAPABILITY_CHECK` step *inside* a spec via
   `run_engine.py`.

   **Resolved: both became real, minimal standalone commands** —
   `aura ui-audit <url>` and `aura capability-check <type> <target>
   [--params JSON] [--expected JSON]`. Deliberately minimal: each
   exposes an existing internal path (`orchestrator/ui_audit_runner.run_ui_audit`,
   `orchestrator/kernel.py`'s `Capability.check` `ToolCall` contract)
   directly rather than adding any new capability behind the new
   command names.

Full implementation detail, verification, and the exact files touched:
`docs/decisions.md` D-075.
