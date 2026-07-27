"""
tests/test_brain.py

Phase B1 (docs/AURA_BRAIN_ARCHITECTURE.md, docs/decisions.md D-070).
Covers the Brain scaffolding itself: Intent/Policy/Router/AuraBrain.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from orchestrator.brain import AuraBrain, Intent
from orchestrator.brain.policy import Policy, RetryPolicy


def test_policy_discovery_source_is_dom_when_page_present():
    policy = Policy()
    assert policy.discovery_source(dom_page=MagicMock()) == "dom"
    assert policy.discovery_source(dom_page=None) == "ocr"


def test_policy_change_detection_method_matches_discovery_source_condition():
    # G-... / docs/AURA_BRAIN_ARCHITECTURE.md: these two must use the
    # exact same condition -- one rule governs both fallbacks.
    policy = Policy()
    page = MagicMock()
    assert policy.change_detection_method(page) == "mutation_observer"
    assert policy.change_detection_method(None) == "hash_diff"
    assert (policy.discovery_source(page) == "dom") == (policy.change_detection_method(page) == "mutation_observer")
    assert (policy.discovery_source(None) == "ocr") == (policy.change_detection_method(None) == "hash_diff")


def test_policy_retry_policy_returns_known_defaults():
    policy = Policy()
    llm = policy.retry_policy("llm_call")
    assert isinstance(llm, RetryPolicy)
    assert llm.max_attempts == 3
    unknown = policy.retry_policy("some_unregistered_kind")
    assert unknown.max_attempts == 1  # safe default, not an exception


def test_policy_confidence_threshold_known_and_unknown_kinds():
    policy = Policy()
    assert policy.confidence_threshold("expected_state_match") == 1.0
    assert policy.confidence_threshold("keyword_heuristic_match") == 0.6
    assert policy.confidence_threshold("totally_unknown") == 0.5


def test_policy_loads_real_ocr_vocab_and_bands_from_brain_knowledge_yaml():
    """
    Phase B2 (docs/decisions.md D-071): Policy's values now come from
    brain_knowledge/rules/*.yaml, not Python literals. This is the
    regression test that the real repo's YAML files parse and match
    agents/vision/ui_audit.py's current hardcoded vocab/bands exactly
    (the values these files were extracted from).
    """
    policy = Policy()
    nav_vocab = policy.ocr_vocab("nav")
    assert "sign up" in nav_vocab
    assert "contact us" in nav_vocab
    assert len(nav_vocab) == 25  # matches agents/vision/ui_audit.py's _NAV_VOCAB size exactly

    bands = policy.band_boundaries()
    assert bands == {"nav_band_end": 0.10, "hero_band_end": 0.45, "footer_band_start": 0.88}


def test_policy_falls_back_safely_when_knowledge_folder_is_missing():
    """
    A missing/broken brain_knowledge/ folder must degrade to the exact
    same defaults Phase B1 had hardcoded, never raise -- G-006-adjacent
    resilience requirement stated in policy.py's own docstring.
    """
    from pathlib import Path

    from orchestrator.brain.context import BrainKnowledge

    knowledge = BrainKnowledge.load(root=Path("/tmp/definitely_does_not_exist_brain_knowledge"))
    policy = Policy(knowledge)

    assert policy.ocr_vocab("nav") == set()  # no sensible non-empty fallback available from this package alone
    assert policy.band_boundaries() == {"nav_band_end": 0.10, "hero_band_end": 0.45, "footer_band_start": 0.88}
    assert policy.retry_policy("llm_call") == RetryPolicy(max_attempts=3, backoff_seconds=1.0)
    assert policy.confidence_threshold("expected_state_match") == 1.0


def test_malformed_yaml_file_does_not_crash_knowledge_loading(tmp_path):
    """A single bad rules/*.yaml file must not take down every other rule."""
    from orchestrator.brain.context import BrainKnowledge

    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "discovery.yaml").write_text("not: valid: yaml: [", encoding="utf-8")
    (rules_dir / "bands.yaml").write_text("nav_band_end: 0.10\nhero_band_end: 0.45\nfooter_band_start: 0.88\n", encoding="utf-8")

    knowledge = BrainKnowledge.load(root=tmp_path)
    policy = Policy(knowledge)

    assert policy.ocr_vocab("nav") == set()  # discovery.yaml failed to parse -- safe fallback, no crash
    assert policy.band_boundaries()["nav_band_end"] == 0.10  # bands.yaml parsed fine independently


def test_genuinely_unknown_intent_kind_raises_clear_not_implemented_error():
    """
    Phase B3 (docs/decisions.md D-075) migrated every documented
    IntentKind ('execute_spec', 'execute_prompt',
    'execute_interactive', 'ui_audit', 'capability_check') -- there is
    no longer a real IntentKind this error path fires for. Router.resolve()
    still needs to fail clearly rather than crash on a kind outside that
    set entirely (Intent.kind isn't runtime-validated against the
    Literal), so this tests that fallback path directly instead.
    """
    brain = AuraBrain()
    with pytest.raises(NotImplementedError, match="no handler"):
        brain.handle(Intent(kind="totally_made_up_kind", params={}))  # type: ignore[arg-type]
