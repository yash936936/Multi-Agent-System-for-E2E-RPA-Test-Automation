"""
orchestrator/brain/policy.py

The one place every cross-cutting decision AURA makes gets answered,
instead of the same question being independently re-derived in
`orchestrator/ui_audit_runner.py`, `orchestrator/run_engine.py`, and
`agents/planner/spec_generator.py`. See
docs/AURA_BRAIN_ARCHITECTURE.md §2.2 for the full rationale.

**Phase B1 scope (docs/decisions.md D-070):** these methods exist and
are correct, unit-tested -- but nothing outside this package calls them
yet. Wiring `ui_audit_runner.py`/`run_engine.py` to call
`Policy.discovery_source()`/`Policy.change_detection_method()` instead
of their own local `dom_page is not None` checks is Phase 2/Phase 4's
job specifically, not this package's -- that's a different, larger
change (touching call sites outside `orchestrator/brain/`) from what
B1/B2 scope to.

**Phase B2 scope (docs/decisions.md D-071), done in this pass:** every
value below now comes from `brain_knowledge/rules/*.yaml` via
`self.knowledge.rules`, with the exact same value hardcoded as a
fallback for when the knowledge folder is missing, a file fails to
parse, or a key isn't present (e.g. a bare `Policy()` in a test with no
`brain_knowledge/` on disk). This means editing a `.yaml` file is now a
real, live behavior change for `Policy`'s own callers -- it just has no
callers outside this package's own tests yet, so the practical effect
is still zero until Phase 2/4 wire other subsystems to it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from orchestrator.brain.context import BrainKnowledge

DiscoverySource = Literal["dom", "ocr"]
ChangeDetectionMethod = Literal["mutation_observer", "hash_diff"]

# Hardcoded fallbacks -- used only when brain_knowledge/rules/*.yaml is
# missing, fails to parse, or doesn't have the relevant key. Kept as
# the exact same values the pre-B2 Python-literal version had, so a
# missing/broken knowledge folder degrades to B1's already-verified
# behavior rather than a new failure mode.
_RETRY_FALLBACKS = {
    "llm_call": {"max_attempts": 3, "backoff_seconds": 1.0},
    "click_dispatch": {"max_attempts": 1, "backoff_seconds": 0.0},
    "network_capability": {"max_attempts": 3, "backoff_seconds": 1.0},
}
_CONFIDENCE_FALLBACKS = {
    "expected_state_match": 1.0,
    "keyword_heuristic_match": 0.6,
    "keyword_heuristic_weak_match": 0.3,
    "no_match": 0.0,
}
_DEFAULT_CONFIDENCE_FALLBACK = 0.5
_DEFAULT_RETRY_FALLBACK = {"max_attempts": 1, "backoff_seconds": 0.0}


@dataclass
class RetryPolicy:
    max_attempts: int
    backoff_seconds: float


class Policy:
    def __init__(self, knowledge: BrainKnowledge | None = None):
        self.knowledge = knowledge or BrainKnowledge.load()

    def discovery_source(self, dom_page) -> DiscoverySource:
        """
        The single condition that today independently governs: (a)
        whether `orchestrator/ui_audit_runner.py::_run_click_audit`
        merges DOM elements / cross-checks OCR false positives against
        DOM ground truth, and (b) which click-dispatch path
        (`_try_dom_click` vs OCR/OS fallback) is attempted first.

        Reads `brain_knowledge/rules/discovery.yaml`'s
        `default_source`/`fallback_source` -- but since the only two
        valid values are literally "is there a live page or not," this
        stays a boolean condition regardless of what the YAML says
        (a YAML file can't change *whether* dom_page is None). What it
        DOES make configurable, once Phase 2 wires this in, is which
        vocab lists back the OCR fallback (`ocr_vocab` in the same
        file) -- the source/fallback labels are kept in the YAML for
        readability/documentation, not because they're actually
        branched on here.
        """
        return "dom" if dom_page is not None else "ocr"

    def change_detection_method(self, dom_page) -> ChangeDetectionMethod:
        """
        Governs Phase 4's MutationObserver-vs-hash-diff choice. Uses the
        exact same condition as discovery_source() deliberately -- one
        rule governs both fallbacks, so there's one mental model for
        "when does AURA fall back to vision-only mode," not two
        independent ones that happen to currently coincide. Reads
        `brain_knowledge/rules/change_detection.yaml`'s
        `mutation_observer.settle_wait_seconds`/`ignore_selectors` once
        Phase 4 actually uses them; this method itself is the same
        live/no-live-page condition as discovery_source(), same caveat.
        """
        return "mutation_observer" if dom_page is not None else "hash_diff"

    def ocr_vocab(self, band: Literal["nav", "cta", "footer"]) -> set[str]:
        """
        The OCR-fallback vocabulary for a given band, read from
        `brain_knowledge/rules/discovery.yaml`'s `ocr_vocab.<band>`
        list. Falls back to an empty set (not the hardcoded vocab
        itself) if the file/key is missing -- unlike the other
        fallbacks here, there's no sensible "old Python literal"
        fallback to reach for from *this* package, since the literal
        still lives in `agents/vision/ui_audit.py` until Phase 2
        repoints that file to call this method instead of using its own
        module-level `_NAV_VOCAB`/`_CTA_VOCAB`/`_FOOTER_VOCAB` sets. An
        empty-set fallback is safe specifically because nothing calls
        this method yet (same B1/B2 "not load-bearing outside this
        package" scope as everything else here).
        """
        band_lists = self.knowledge.rules.get("discovery", {}).get("ocr_vocab", {})
        return set(band_lists.get(band, []))

    def band_boundaries(self) -> dict[str, float]:
        """
        Reads `brain_knowledge/rules/bands.yaml`. Falls back to the
        exact values `agents/vision/ui_audit.py` hardcodes today
        (`_NAV_BAND_END`/`_HERO_BAND_END`/`_FOOTER_BAND_START`).
        """
        bands = self.knowledge.rules.get("bands", {})
        return {
            "nav_band_end": bands.get("nav_band_end", 0.10),
            "hero_band_end": bands.get("hero_band_end", 0.45),
            "footer_band_start": bands.get("footer_band_start", 0.88),
        }

    def change_detection_settings(self) -> dict:
        """
        Reads `brain_knowledge/rules/change_detection.yaml`'s
        `mutation_observer.*` block for
        `agents/vision/dom_change_detector.py` -- `settle_wait_seconds`
        (a short wait before reading back the mutation buffer) and
        `ignore_selectors` (known-noisy nodes -- ad iframes, analytics
        beacons, live regions -- that shouldn't count as a real change).
        Falls back to the same values `rules/change_detection.yaml`
        ships with by default, so a missing/broken knowledge folder
        degrades to a sane default rather than "no denylist at all."
        """
        rules = self.knowledge.rules.get("change_detection", {}).get("mutation_observer", {})
        return {
            "settle_wait_seconds": rules.get("settle_wait_seconds", 0.5),
            "ignore_selectors": rules.get("ignore_selectors", ["[data-ad]", ".analytics-beacon", "[aria-live]"]),
        }

    def retry_policy(self, operation_kind: str) -> RetryPolicy:
        """
        Replaces three independent, currently-hardcoded retry ladders:
        `agents/planner/spec_generator.py`'s Hermes->Cloud escalation,
        `orchestrator/http_retry.py`'s backoff, and
        `orchestrator/guardrails.py`'s evidence-fingerprint short-circuit
        threshold. Each call site keeps its own retry *mechanics* (an
        LLM backend escalation and an HTTP retry aren't the same code)
        but should ask this for the numbers instead of hardcoding them
        -- not yet true of any of the three; see class docstring.
        """
        rules = self.knowledge.rules.get("retry", {})
        values = rules.get(operation_kind) or _RETRY_FALLBACKS.get(operation_kind, _DEFAULT_RETRY_FALLBACK)
        return RetryPolicy(
            max_attempts=values.get("max_attempts", _DEFAULT_RETRY_FALLBACK["max_attempts"]),
            backoff_seconds=values.get("backoff_seconds", _DEFAULT_RETRY_FALLBACK["backoff_seconds"]),
        )

    def confidence_threshold(self, check_kind: str) -> float:
        """
        Replaces scattered magic numbers (e.g.
        `orchestrator/run_engine.py`'s 0.6/1.0/0.3 confidence literals
        introduced in D-067.7's keyword-heuristic fix).
        """
        rules = self.knowledge.rules.get("confidence", {})
        fallback = _CONFIDENCE_FALLBACKS.get(check_kind, _DEFAULT_CONFIDENCE_FALLBACK)
        return rules.get(check_kind, fallback)
