# AURA — Context (living document, keep under ~200 lines)

This is the current, living state of AURA's architecture — what a new
engineer (or a new Claude session) should read first, instead of
`docs/decisions.md`'s full chronological history. Disagreements between
this file and `decisions.md` are expected: `decisions.md` is history
(why something happened), this file is current state (what's true now).

## What AURA is

A multi-agent RPA/QA test automation platform: given a URL or a
plain-English requirement, it drives a real browser, verifies pages
render and interact correctly, and reports what's broken. Two autonomy
modes: `explore` (zero instructions, click everything, report back) and
`execute` (spec-driven or prompt-driven, scripted or human-in-the-loop).

## Core coordination layer

- `orchestrator/brain/` (Phase B1, 2026-07-25) — the single entrypoint
  every CLI command routes through. `Intent` (what's being asked),
  `Policy` (cross-cutting decisions: DOM-vs-OCR, retry thresholds,
  confidence thresholds — currently Python literals, see B2), `Router`
  (Intent -> which existing subsystem, in what order). Only the
  `explore` intent is migrated as of B1; everything else still runs
  through its own CLI command's hand-assembled pipeline until migrated.
  See `docs/AURA_BRAIN_ARCHITECTURE.md` for full design.

## Discovery & interaction (the "hands")

- `agents/vision/dom_extractor.py` — primary element-discovery path
  when a live Playwright page exists: real `<a>`/`<button>`/`role`/
  `cursor:pointer` detection, not text pattern matching.
- `agents/vision/ui_audit.py` — OCR-based element discovery
  (`_NAV_VOCAB`/`_CTA_VOCAB`/`_FOOTER_VOCAB` + text-shape heuristic).
  Fallback-only when no live DOM page exists (target state per Phase 2;
  as of this writing it's still a co-equal/cross-checked path, not a
  pure fallback — see `docs/AURA_REARCHITECTURE_PLAN.md` Phase 2).
- `orchestrator/ui_audit_runner.py` — the click-and-diff engine behind
  both `aura explore` and `aura execute --ui-audit`: clicks every
  candidate element, checks whether the page changed
  (`agents/vision/assertions.py`'s pixel-hash-diff today; Phase 4
  replaces this with a MutationObserver-based check wherever a live
  page exists).
- `runtime/hooks/interact.py` — click/scroll/type dispatch.
  `dom_click`/`dom_smart_back` (Playwright-native, viewport-space) are
  primary; `click`/`type_text`/`scroll` (pyautogui, OS-absolute-pixel
  space) are the fallback slated for full removal in Phase 3.
- `runtime/hooks/browser.py` — Playwright browser lifecycle,
  coordinate translation between viewport and OS-screen space (the
  coordinate-space mismatch bug class Phase 3 removes entirely by
  removing the OS-space side of the translation).

## Execution (spec-driven)

- `agents/planner/spec_generator.py` — turns a plain-English requirement
  into a structured `TestSpec` via an LLM (local Hermes backend, cloud
  fallback). Has its own retry/escalation ladder, independent of
  `orchestrator/guardrails.py`'s and `orchestrator/http_retry.py`'s —
  a Phase-B1-follow-on candidate for `Policy.retry_policy()`.
- `orchestrator/run_engine.py` — executes a `TestSpec` step by step,
  including `WAIT_FOR_HUMAN_ACTION` (the `--interactive` mode) and
  assertion checking (`agents/vision/assertions.py`).
- `orchestrator/healing_loop.py` + `orchestrator/guardrails.py` — retry/
  self-heal on a failed step, with a short-circuit on identical
  evidence (D-062) to avoid burning through a retry budget on a stub
  that always fails the same way.

## Logging & debugging (currently disconnected — Phase 1's target)

- `orchestrator/decision_trace_log.py` — planner backend decisions.
- `orchestrator/assertion_audit_log.py` — assertion verdicts,
  `find_anomalies()`.
- `aura audit-report <run_id>` — CLI on top of the assertion audit log.
- `aura explore --debug` — per-element `resolution_strategy` (D-067).
- **Not yet unified**: no single merged timeline across the above, and
  no `aura explain <run_id>` command yet. See
  `docs/AURA_REARCHITECTURE_PLAN.md` Phase 1.

## Where to look next

- `docs/STATUS.md` — what's actually done vs. what's next, kept current.
- `docs/decisions.md` — full history, one entry per decision, never
  deleted (superseded entries are marked, not removed).
- `docs/AURA_REARCHITECTURE_PLAN.md` / `docs/AURA_BRAIN_ARCHITECTURE.md`
  — the forward plan this file's "Core coordination layer" and
  "Discovery & interaction" sections are being migrated toward.
