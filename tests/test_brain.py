"""
tests/test_brain.py

Phase B1 (docs/AURA_BRAIN_ARCHITECTURE.md, docs/decisions.md D-070).
Covers the Brain scaffolding itself: Intent/Policy/Router/AuraBrain,
and that the explore intent (the only one migrated in B1) actually
reaches the same underlying subsystem call (`run_exploration`) the CLI
used to call directly.
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


def test_unmigrated_intent_kind_raises_clear_not_implemented_error():
    brain = AuraBrain()
    with pytest.raises(NotImplementedError, match="not yet migrated"):
        brain.handle(Intent(kind="execute_spec", params={}))


def test_explore_intent_reaches_run_exploration_with_expected_params():
    """
    The core B1 regression test: aura/cli/explore_cmd.py used to call
    orchestrator.ui_audit_runner.run_exploration directly; after the B1
    migration it must reach the exact same function, with the same
    params, via AuraBrain -- this is a coordination move, not a
    behavior change.
    """
    fake_report = MagicMock(has_nav=True, has_hero=False, has_footer=True, checked=[], page_issues=[], link_check_result=None, requirement_match=None, requirement_notes=[], possibly_broken=[])

    with patch("orchestrator.ui_audit_runner.run_exploration", return_value=fake_report) as mock_run_exploration, \
         patch("runtime.hooks.browser.open_url") as mock_open_url, \
         patch("runtime.hooks.browser.normalize_url", side_effect=lambda u: u), \
         patch("orchestrator.autoscan.run_autoscan") as mock_autoscan, \
         patch("time.sleep"):
        mock_autoscan.return_value = MagicMock(display_unavailable=False, all_issues=[], reached_bottom=True)

        brain = AuraBrain()
        intent = Intent(kind="explore", params={"url": "http://example.test", "max_elements": 10, "prompt": "check the button", "scroll_scan": True, "check_links": False, "link_scope": "all"})
        result = brain.handle(intent)

    mock_open_url.assert_called_once_with("http://example.test")
    mock_run_exploration.assert_called_once()
    _, kwargs = mock_run_exploration.call_args
    assert kwargs["max_elements"] == 10
    assert kwargs["requirement_prompt"] == "check the button"
    assert kwargs["page_url"] is None  # check_links=False
    assert result.kind == "explore"
    assert result.data["report"] is fake_report


def test_explore_intent_records_open_error_without_raising():
    fake_report = MagicMock(has_nav=False, has_hero=False, has_footer=False, checked=[], page_issues=[], link_check_result=None, requirement_match=None, requirement_notes=[], possibly_broken=[])

    with patch("orchestrator.ui_audit_runner.run_exploration", return_value=fake_report), \
         patch("runtime.hooks.browser.open_url", side_effect=RuntimeError("no browser available")), \
         patch("runtime.hooks.browser.normalize_url", side_effect=lambda u: u), \
         patch("time.sleep"):
        brain = AuraBrain()
        result = brain.handle(Intent(kind="explore", params={"url": "http://example.test", "scroll_scan": False}))

    assert "no browser available" in result.data["open_error"]
    assert result.data["autoscan_report"] is None  # scroll_scan=False
