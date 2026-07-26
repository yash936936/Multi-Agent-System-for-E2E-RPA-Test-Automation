"""
Prompt templates for the Planner agent.

Kept separate from spec_generator.py / diagnoser.py so wording can be
iterated on without touching control flow. These are consumed by
LLMBackend implementations (see agents/planner/spec_generator.py); the
default LocalHeuristicBackend does not use them at all since it runs
without any model.

**Gap #4 (docs/decisions.md D-080):** the two SPEC_GENERATION_*
constants below are no longer the source of truth for their wording --
they're now the hardcoded fallback for when `brain_knowledge/prompts/`
is missing, unreadable, or a file's stem doesn't match. The real
content lives in `brain_knowledge/prompts/*.txt`, loaded once here via
`orchestrator.brain.context.BrainKnowledge.load()`, mirroring the exact
same fallback posture `orchestrator/brain/policy.py` already uses for
`rules/*.yaml`. Editing a `.txt` file there is now a live prompt-wording
change for every LLM-backed planner backend, without touching this
module.

**Naming caveat, documented rather than silently papered over:**
`brain_knowledge/prompts/planner_retry_prompt.txt` maps to
SPEC_GENERATION_USER_TEMPLATE, not a genuinely distinct retry-specific
prompt -- `agents/planner/spec_generator.py::_generate_with_retry()`
retries by calling `backend.generate(text)` a second time with the
identical text; there is no separate wording sent on retry in current
behavior. `docs/AURA_BRAIN_ARCHITECTURE.md`'s `brain_knowledge/`
directory listing names this file `planner_retry_prompt.txt`, so the
file is named to match that spec, but its actual content and role is
"the user-message template used on every generate() call, initial and
retry alike." See D-080 for the full trace of why no separate retry
wording exists to extract.

DIAGNOSIS_SYSTEM_PROMPT / DIAGNOSIS_USER_TEMPLATE below are unrelated
to this migration and unaffected by it -- see D-080's note that they
appear to be dead code (agents/planner/diagnoser.py uses its own
separate inline `_SYSTEM_PROMPT`/`_USER_TEMPLATE` class attributes
instead), flagged but deliberately not touched as part of Gap #4's
scope, which is the Planner's *spec-generation* prompts specifically.
"""
from __future__ import annotations

from orchestrator.brain.context import BrainKnowledge

_knowledge = BrainKnowledge.load()

_SPEC_GENERATION_SYSTEM_PROMPT_FALLBACK = """\
You are the Planner agent inside AURA, an offline RPA test automation system.
Convert the given requirement document into a single JSON object matching
this exact schema (no prose, no markdown fences, JSON only):

{
  "test_id": "TC-<SHORT-NAME>-<NNN>",
  "requirement_ref": "<short reference to the source requirement>",
  "preconditions": ["<precondition>", ...],
  "steps": [
    {
      "step_id": <int, 1-indexed>,
      "action": "visual_click" | "type_text" | "scroll" | "assert",
      "target_description": "<what to click on screen, if action is visual_click>",
      "field_description": "<what field to type into, if action is type_text>",
      "expected_state": "<observable UI state after this step>",
      "assertion_kind": "literal_text" | "page_rendered" | "negative" | "custom",
      "value_ref": "<reference into synthetic data, e.g. 'synthetic.username', if action is type_text>"
    }
  ],
  "assertions": [{"type": "visual_state", "expected": "<final expected UI state>", "assertion_kind": "literal_text" | "page_rendered" | "negative" | "custom"}],
  "data_requirements": ["<field name>", ...]
}

Rules:
- Every user-facing interaction implied by the requirement becomes its own step.
- Only use action values from the enum above.
- data_requirements must list every field referenced by a value_ref, plus any
  edge cases explicitly mentioned (e.g. "unicode name", "max length").
- Output valid JSON only.
- If the requirement document includes a section listing elements actually
  found on the live target page, treat that list as ground truth for
  target_description/field_description wording -- prefer an exact or close
  match from it over inventing a plausible-sounding label that isn't there.
- assertion_kind is required whenever expected_state (or an assertion's
  "expected") is set -- omit it only when there is genuinely nothing to
  verify for that step. Choose exactly one:
    literal_text  -- expected_state is on-screen text/label that must
                     literally appear (e.g. "Dashboard", "Welcome, Alex")
    page_rendered -- there is no specific text to check, only "did some
                     real content load" (e.g. after a bare navigation with
                     no stated Then-clause)
    negative      -- expected_state must NOT appear on screen (e.g. an
                     error banner, a "field required" message, a element
                     that should have disappeared)
    custom        -- the check doesn't fit the three categories above and
                     no built-in verification applies; state this
                     explicitly rather than defaulting to literal_text
"""

_SPEC_GENERATION_USER_TEMPLATE_FALLBACK = """\
Requirement document:
---
{requirement_text}
---
Produce the TestSpec JSON now.
"""

SPEC_GENERATION_SYSTEM_PROMPT = _knowledge.prompts.get("planner_system_prompt", _SPEC_GENERATION_SYSTEM_PROMPT_FALLBACK)
SPEC_GENERATION_USER_TEMPLATE = _knowledge.prompts.get("planner_retry_prompt", _SPEC_GENERATION_USER_TEMPLATE_FALLBACK)

# The grounding block itself (agents/planner/spec_generator.py::_build_grounded_text)
# is a separate, third piece of prompt wording -- also externalized as
# part of Gap #4, read directly by that function via BrainKnowledge
# rather than through a module-level constant here, since it's only
# ever used in that one place and needs its own {elements_block}
# substitution done there, not here.

DIAGNOSIS_SYSTEM_PROMPT = """\
You are the Auditor agent inside AURA. You are given a test step that
failed, along with before/after screenshots (described as text) and
execution logs. Produce a single JSON object matching this schema
(no prose, JSON only):

{
  "skill_id": "SKILL-<YYYYMMDD>-<NNN>",
  "failure_signature": "<short machine-matchable string identifying this failure class>",
  "root_cause": "<one or two sentence explanation>",
  "proposed_fix": "<concrete, actionable fix>",
  "fix_type": "retry_strategy" | "spec_correction",
  "confidence": <float 0-1>
}

Use "retry_strategy" when the fix changes *how* Vision searches/acts (e.g.
broaden search region, wait longer, try alternate label text). Use
"spec_correction" when the fix means the TestSpec itself is wrong (e.g.
target_description no longer matches any real UI element).
"""

DIAGNOSIS_USER_TEMPLATE = """\
Failed step: {failed_step_json}
Execution logs:
{execution_logs}

Produce the SkillRecord JSON now.
"""
