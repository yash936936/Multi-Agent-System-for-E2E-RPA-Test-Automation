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
