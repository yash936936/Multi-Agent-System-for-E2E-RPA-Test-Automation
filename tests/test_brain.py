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


# ---- merged from test_brain_b3.py (Phase B3, D-075) ----
def test_execute_requirement_intent_reaches_engine_run_with_callbacks_forwarded():
    fake_spec = MagicMock(test_id="TC-FAKE-001")
    fake_engine_result = MagicMock(run_id="tc-fake-001", validation_warnings=[])
    captured_callbacks = {}

    def fake_engine_ctor(**kwargs):
        captured_callbacks.update(kwargs)
        engine = MagicMock()
        engine.run.return_value = fake_engine_result
        return engine

    with patch("agents.planner.tool.generate_spec", return_value=fake_spec), \
         patch("agents.planner.page_grounding.snapshot_page_elements", return_value=None), \
         patch("orchestrator.run_engine.RunEngine", side_effect=fake_engine_ctor):
        on_step_start = MagicMock()
        intent = Intent(
            kind="execute_spec",
            params={
                "requirement_text": "Given: navigate to http://example.test",
                "auto_approve": True,
                "screenshot_provider": MagicMock(),
                "on_step_start": on_step_start,
            },
        )
        result = AuraBrain().handle(intent)

    # The exact closure passed in must be the one RunEngine received --
    # not a Router-owned rendering call.
    assert captured_callbacks["on_step_start"] is on_step_start
    assert result.data["spec"] is fake_spec
    assert result.data["result"] is fake_engine_result
    assert result.data["cancelled"] is False


def test_execute_requirement_intent_calls_approve_spec_before_generating_data():
    fake_spec = MagicMock(test_id="TC-FAKE-002")
    approve_calls = []

    def approve_spec(spec):
        approve_calls.append(spec)
        return False  # reject

    with patch("agents.planner.tool.generate_spec", return_value=fake_spec), \
         patch("agents.planner.page_grounding.snapshot_page_elements", return_value=None):
        intent = Intent(
            kind="execute_prompt",
            params={
                "requirement_text": "Check something",
                "auto_approve": False,
                "screenshot_provider": MagicMock(),
                "approve_spec": approve_spec,
            },
        )
        result = AuraBrain().handle(intent)

    assert approve_calls == [fake_spec]
    assert result.data["cancelled"] is True


def test_execute_interactive_intent_reaches_run_spec_with_on_waiting_forwarded():
    fake_result = MagicMock(report=MagicMock(escalated_steps=0), validation_warnings=[])
    captured = {}

    def fake_engine_ctor(**kwargs):
        captured.update(kwargs)
        engine = MagicMock()
        engine.run_spec.return_value = fake_result
        return engine

    on_waiting = MagicMock()
    with patch("orchestrator.run_engine.RunEngine", side_effect=fake_engine_ctor):
        intent = Intent(
            kind="execute_interactive",
            params={"prompt": "click the button", "url": None, "timeout": 0, "screenshot_provider": MagicMock(), "on_waiting": on_waiting},
        )
        result = AuraBrain().handle(intent)

    assert captured["on_waiting_for_human"] is on_waiting
    assert result.data["result"] is fake_result


def test_ui_audit_intent_reaches_run_ui_audit_with_expected_params():
    fake_report = MagicMock(has_nav=True)
    with patch("orchestrator.ui_audit_runner.run_ui_audit", return_value=fake_report) as mock_run_ui_audit, \
         patch("runtime.hooks.browser.open_url"), \
         patch("runtime.hooks.browser.normalize_url", side_effect=lambda u: u), \
         patch("time.sleep"):
        intent = Intent(kind="ui_audit", params={"url": "http://example.test", "max_elements": 5, "link_scope": "footer"})
        result = AuraBrain().handle(intent)

    _, kwargs = mock_run_ui_audit.call_args
    assert kwargs["max_elements"] == 5
    assert kwargs["page_url"] == "http://example.test"
    assert kwargs["link_check_scope"] == "footer"
    assert result.data["report"] is fake_report


def test_capability_check_intent_reaches_kernel_call_tool_with_expected_payload():
    from orchestrator.schemas import ToolResponse

    fake_response = ToolResponse(name="Capability.check", result={"capability": "api", "passed": True, "confidence": 1.0, "evidence": {}}, ok=True)

    with patch("orchestrator.kernel.OrchestratorKernel.call_tool", return_value=fake_response) as mock_call_tool, \
         patch("orchestrator.kernel.ToolRegistry.load", return_value=MagicMock(get=MagicMock(return_value=MagicMock(output_schema=__import__("orchestrator.schemas", fromlist=["CapabilityCheckResult"]).CapabilityCheckResult)))):
        intent = Intent(kind="capability_check", params={"capability_type": "api", "target": "http://example.test/health", "params": {}, "expected": {}})
        result = AuraBrain().handle(intent)

    assert mock_call_tool.called
    call_arg = mock_call_tool.call_args[0][0]
    assert call_arg.name == "Capability.check"
    assert result.data["error"] is None
    assert result.data["result"].passed is True
