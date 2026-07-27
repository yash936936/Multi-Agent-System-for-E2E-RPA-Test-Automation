"""
orchestrator/brain/intent.py

`Intent` is the one typed object every entrypoint (CLI today; API/Slack
Tag later) builds instead of hand-assembling its own pipeline of
subsystem calls. `Router.resolve()` is the only thing that reads it.
See docs/AURA_BRAIN_ARCHITECTURE.md §2.1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

IntentKind = Literal[
    "execute_spec",
    "execute_prompt",
    "execute_interactive",
    "ui_audit",
    "capability_check",
]

Caller = Literal["cli", "api", "slack_tag"]


@dataclass
class Intent:
    kind: IntentKind
    params: dict[str, Any] = field(default_factory=dict)
    caller: Caller = "cli"

    def get(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)
