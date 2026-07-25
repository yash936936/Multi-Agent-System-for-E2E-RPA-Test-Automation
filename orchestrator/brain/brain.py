"""
orchestrator/brain/brain.py

`AuraBrain` is the single entrypoint every CLI command, API route, and
(later) Slack Tag adapter calls into instead of hand-assembling its own
pipeline. See docs/AURA_BRAIN_ARCHITECTURE.md §2.1.
"""
from __future__ import annotations

from orchestrator.brain.context import BrainKnowledge
from orchestrator.brain.intent import Intent
from orchestrator.brain.policy import Policy
from orchestrator.brain.router import BrainResult, Router

__all__ = ["AuraBrain", "BrainResult"]


class AuraBrain:
    def __init__(self, knowledge: BrainKnowledge | None = None):
        self.knowledge = knowledge or BrainKnowledge.load()
        self.policy = Policy(self.knowledge)
        self.router = Router(self.policy)

    def handle(self, intent: Intent) -> BrainResult:
        """
        Phase B1 scope: routes and returns the result. Phase 1 (unified
        logging) is where this method grows a `with
        unified_run_logger(run_id, intent): ...` wrapper so every intent
        handled here gets timeline logging automatically instead of each
        CLI command remembering to wire it up itself
        (docs/AURA_BRAIN_ARCHITECTURE.md §2.1) -- not added yet, to keep
        this phase's diff to exactly "route the call," nothing else.
        """
        return self.router.resolve(intent)
