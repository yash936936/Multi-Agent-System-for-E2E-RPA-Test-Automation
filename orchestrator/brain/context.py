"""
orchestrator/brain/context.py

Loads `brain_knowledge/` (repo root) -- the Brain's externalized policy
source (docs/AURA_BRAIN_ARCHITECTURE.md §3). `rules/*.yaml` is parsed
into `BrainKnowledge.rules` (Phase B2, docs/decisions.md D-071);
`prompts/*.txt` loading is still pending (tracked against migrating the
`execute_*` intents onto the Brain, not yet done).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def _find_knowledge_dir() -> Path:
    # orchestrator/brain/context.py -> repo root is two parents up.
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "brain_knowledge"


def _load_rules(root: Path) -> dict:
    """
    Parses every `*.yaml` file under `root/rules/` into a dict keyed by
    filename stem (`discovery.yaml` -> `rules["discovery"]`). Missing
    folder, missing/malformed individual files, and an unparseable YAML
    document are all non-fatal: `Policy`'s methods have their own
    hardcoded fallback for exactly this reason (see
    orchestrator/brain/policy.py's docstring) -- a knowledge-loading
    problem should degrade to "use the built-in default," never crash
    every command that touches the Brain.
    """
    rules_dir = root / "rules"
    rules: dict = {}
    if not rules_dir.is_dir():
        return rules
    for yaml_path in sorted(rules_dir.glob("*.yaml")):
        try:
            with yaml_path.open("r", encoding="utf-8") as f:
                parsed = yaml.safe_load(f)
            rules[yaml_path.stem] = parsed if parsed is not None else {}
        except Exception as e:
            logger.warning(
                "BrainKnowledge: failed to parse %s (%s) -- Policy will fall back to its "
                "built-in default for anything this file would have provided.",
                yaml_path, e,
            )
    return rules


@dataclass
class BrainKnowledge:
    """
    Read-only view over `brain_knowledge/`. `prompts` stays an empty
    dict pending the `execute_*` intents' migration -- see module
    docstring.
    """

    root: Path
    rules: dict = field(default_factory=dict)
    prompts: dict = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path | None = None) -> "BrainKnowledge":
        knowledge_root = root or _find_knowledge_dir()
        return cls(root=knowledge_root, rules=_load_rules(knowledge_root))

    def guidelines_path(self) -> Path:
        return self.root / "guidelines.md"

    def context_path(self) -> Path:
        return self.root / "context.md"

    def playbook_path(self, name: str) -> Path:
        return self.root / "playbooks" / f"{name}.md"

    def exists(self) -> bool:
        return self.root.is_dir()
