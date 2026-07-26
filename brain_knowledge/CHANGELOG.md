# brain_knowledge/ — Changelog

This folder is reviewed like code (docs/AURA_BRAIN_ARCHITECTURE.md §3).
Every edit here gets a dated entry.

## 2026-07-25 — Phase B1 initial skeleton
- `context.md`, `guidelines.md` (G-000 through G-006) written.
- `rules/*.yaml` created as placeholders — documented planned shape,
  not yet loaded by `orchestrator/brain/policy.py` (that's Phase B2).
- `playbooks/explore.md` written, mirroring
  `orchestrator/brain/router.py::Router._handle_explore()` — the only
  intent migrated onto the Brain in B1.
- `prompts/` created empty — populated when `agents/planner/spec_generator.py`'s
  inline prompt strings are extracted (tracked as part of migrating the
  `execute_prompt`/`execute_spec` intents onto the Brain, not yet done).

## 2026-07-25 — Phase B2: rule extraction
- `rules/discovery.yaml` — `ocr_vocab.{nav,cta,footer}` populated with
  the exact contents of `agents/vision/ui_audit.py`'s `_NAV_VOCAB` /
  `_CTA_VOCAB` / `_FOOTER_VOCAB` (25/27/18 entries respectively) as of
  D-067/D-070. Not yet read by `ui_audit.py` itself (Phase 2).
- `rules/bands.yaml` — `nav_band_end`/`hero_band_end`/`footer_band_start`
  populated (0.10/0.45/0.88), matching both `ui_audit.py`'s constants
  and `dom_extractor.py`'s D-067 fix.
- `rules/retry.yaml`, `rules/confidence.yaml` — populated with the
  values `orchestrator/brain/policy.py` was already hardcoding in B1.
- `rules/change_detection.yaml` — populated with a first-draft
  `ignore_selectors` list for Phase 4 (new data, not extracted from
  anywhere existing).
- `orchestrator/brain/context.py::BrainKnowledge.load()` now actually
  parses every `rules/*.yaml` file (`yaml.safe_load`), non-fatally --
  a missing folder, a missing file, or a malformed individual file all
  degrade to `Policy`'s hardcoded fallback rather than raising.
- `orchestrator/brain/policy.py` — every method now reads from
  `self.knowledge.rules` first, falling back to the exact B1 hardcoded
  value if the YAML/key is absent. Added `ocr_vocab(band)` and
  `band_boundaries()`, not present in B1 (the vocab/band data didn't
  have anywhere to live until this pass).

## 2026-07-25 — Phase B3: all remaining intents migrated
- `playbooks/` not yet extended with the 5 new intent handlers'
  decision trees (only `explore.md` exists) -- follow-on documentation
  work, tracked here rather than done silently as part of B3 itself.
- No `rules/*.yaml` changes in this pass -- B3 was Router/CLI wiring,
  not policy data; B2's files are unaffected.

## 2026-07-26 — Gap #3 (D-079): remaining playbooks written
- `playbooks/execute.md` — mirrors
  `orchestrator/brain/router.py::Router._handle_execute_requirement()`
  (serves both `execute_spec` and `execute_prompt` intents), including
  the `built_spec`/`run_id` override params D-079's Gap #1 work added.
- `playbooks/execute_interactive.md` — mirrors
  `Router._handle_execute_interactive()`.
- `playbooks/ui_audit.md` — mirrors `Router._handle_ui_audit()`.
- No `capability_check.md` — `docs/AURA_BRAIN_ARCHITECTURE.md`'s own
  `playbooks/` tree listing names exactly these four files
  (`explore.md`, `execute.md`, `execute_interactive.md`, `ui_audit.md`);
  `capability_check` was never specified to have one.
- Still open, tracked separately: extending
  `scripts/check_doc_drift.py` to mechanically diff each playbook's
  declared step list against its router handler's actual call
  sequence — these four files are accurate as of this dated entry, kept
  in sync by hand like `explore.md` already was, not yet enforced by
  tooling.

## 2026-07-26 — Gap #4 (D-080): planner prompts moved into `prompts/*.txt`
- `prompts/planner_system_prompt.txt`, `prompts/planner_retry_prompt.txt`,
  `prompts/requirement_grounding_prompt.txt` written -- `prompts/` no
  longer holds just a `.gitkeep`.
- `orchestrator/brain/context.py::BrainKnowledge` now loads these into
  `.prompts`, same load-with-fallback contract `rules/*.yaml` already
  has via `Policy`.
- `planner_retry_prompt.txt` is named to match
  `docs/AURA_BRAIN_ARCHITECTURE.md`'s tree, but its actual content is
  the user-message template used on every `generate()` call (initial
  and retry alike) -- there is no separate retry-specific wording in
  current behavior to extract instead. See D-080 for the full trace.
- `agents/planner/prompts.py::DIAGNOSIS_SYSTEM_PROMPT`/
  `DIAGNOSIS_USER_TEMPLATE` left as-is (flagged as apparent dead code
  in D-080, out of this gap's scope).
