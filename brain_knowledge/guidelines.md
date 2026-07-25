# AURA Brain — Guidelines

Plain-English, non-negotiable behavioral rules. Each has an ID
(`G-0xx`) that `orchestrator/brain/policy.py` and other code can
reference in docstrings/comments, the same way `docs/decisions.md`'s
`D-0xx` IDs work — so "why does the Brain behave this way" always
traces to one sentence here.

**G-000 — The Brain coordinates and decides; it does not re-implement.**
If a new requirement needs logic that doesn't fit "which existing
subsystem, called with what policy inputs," that's a sign the logic
belongs in one of the hands (`RunEngine`, `ui_audit_runner`,
`dom_extractor`, a capability adapter), not in `orchestrator/brain/`.
Stated explicitly because it's the single easiest way for this design
to regress back into the fragmentation it exists to fix — see
`docs/AURA_BRAIN_ARCHITECTURE.md` §5.

**G-001 — DOM is the primary source of truth; OCR is the fallback,
never a co-equal path.** When a live Playwright page exists, element
discovery and click dispatch go through the DOM first. OCR/vocab-list
heuristics apply only when `Policy.discovery_source()` returns `"ocr"`
(no live page). See D-067 for what happens when this gets inverted —
a footer heading matching a text-shape heuristic got treated as a real
control.

**G-002 — A "did anything happen" check must never assume its own
side effects didn't happen.** `dom_smart_back()`'s pre-D-067 bug: it
called `page.go_back()` unconditionally, then downstream code read the
resulting page diff as evidence the *click* did something — when the
diff was actually caused by the *undo* step itself. Any verification
step that can itself change state must account for its own effect
before reporting a verdict.

**G-003 — Never silently swallow an exception without a log line.**
Enforced mechanically by `scripts/check_silent_excepts.py` +
`tests/test_no_silent_excepts.py`. An allowlist entry requires a
written, reviewed reason — it is not a way to avoid adding a log line.

**G-004 — A heuristic result must say it's a heuristic.** Keyword
matching, confidence scores, and "looks interactive" classifications
are disclosed as such in output (CLI text, JSON reports, logs) — never
presented with the same certainty as a real assertion (D-060's
`assertion_kind` field, D-067.7's confidence-scored human-action
check).

**G-005 — Escalate uncertainty; don't guess a pass.** When a check
can't confidently determine pass/fail (D-067.7's "screen changed but no
keyword overlap with the prompt" case), the default is to escalate for
review, not to default to "passed." A wrong "escalate" costs a human a
minute of review; a wrong "passed" costs trust in every future report.

**G-006 — Every cross-cutting decision has exactly one implementation.**
DOM-vs-OCR, mutation-vs-hash-diff, retry thresholds, confidence
thresholds: one `Policy` method each, consulted by every caller. Not a
condition copy-pasted into a second file "just for this one case."
