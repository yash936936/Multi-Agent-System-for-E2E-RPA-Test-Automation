"""
orchestrator/brain -- AURA's unified coordination core (Phase B1,
docs/AURA_BRAIN_ARCHITECTURE.md, docs/decisions.md D-070).

Deliberately narrow: owns *intent routing* and *cross-cutting policy
decisions* (DOM-vs-OCR, retry thresholds, confidence thresholds,
change-detection method) in one place, so those decisions stop being
independently re-derived in `ui_audit_runner.py`, `run_engine.py`, and
`spec_generator.py`. It does NOT reimplement what those modules already
do -- `RunEngine`, `ui_audit_runner`, `spec_generator`, and the
capability adapters stay exactly what they are and are called into by
`router.py`, unchanged. See docs/AURA_BRAIN_ARCHITECTURE.md §5 for why
that boundary is enforced deliberately, not just as an aspiration.

Public surface: `AuraBrain`, `Intent`.
"""
from orchestrator.brain.brain import AuraBrain, BrainResult
from orchestrator.brain.intent import Intent

__all__ = ["AuraBrain", "BrainResult", "Intent"]
