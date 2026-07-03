from __future__ import annotations

from config.settings import GuardrailSettings
from orchestrator.guardrails import GuardrailVerdict, LoopGuardrail


def make_guardrail() -> LoopGuardrail:
    # Small explicit thresholds so tests don't depend on config/settings.py defaults changing.
    cfg = GuardrailSettings(
        warnings_enabled=True,
        hard_stop_enabled=True,
        warn_after_exact_failure=2,
        warn_after_same_tool_failure=3,
        warn_after_idempotent_no_progress=2,
        hard_stop_after_exact_failure=5,
        hard_stop_after_same_tool_failure=8,
    )
    return LoopGuardrail(config=cfg)


def test_continue_below_thresholds():
    g = make_guardrail()
    verdict = g.record_failure(step_id=1, tool_name="Vision.execute_step", failure_signature="button_not_found")
    assert verdict is GuardrailVerdict.CONTINUE


def test_warn_after_exact_failure_threshold():
    g = make_guardrail()
    g.record_failure(1, "Vision.execute_step", "button_not_found")
    verdict = g.record_failure(1, "Vision.execute_step", "button_not_found")
    assert verdict is GuardrailVerdict.WARN


def test_hard_stop_after_exact_failure_threshold():
    g = make_guardrail()
    verdict = GuardrailVerdict.CONTINUE
    for _ in range(5):
        verdict = g.record_failure(1, "Vision.execute_step", "button_not_found")
    assert verdict is GuardrailVerdict.HARD_STOP


def test_different_failure_signature_resets_exact_count():
    g = make_guardrail()
    g.record_failure(1, "Vision.execute_step", "button_not_found")
    g.record_failure(1, "Vision.execute_step", "button_not_found")
    # different signature -> exact_failure_count resets to 1.
    # Note: same_tool_failure_count keeps climbing (it's tool-identity based,
    # not signature based) and hits warn_after_same_tool_failure=3 on this
    # very call, so the overall verdict is still WARN -- that's correct
    # guardrail behavior (repeated failures of the *same tool* are still
    # a warning sign even if the error text changed). What this test
    # actually locks down is that exact_failure_count itself resets.
    g.record_failure(1, "Vision.execute_step", "field_not_found")
    snap = g.state_snapshot(1)
    assert snap["exact_failure_count"] == 1


def test_same_tool_failure_warn_threshold_independent_of_signature():
    g = make_guardrail()
    # 3 different failure signatures, same tool each time -> same_tool_failure triggers WARN
    g.record_failure(1, "Vision.execute_step", "sig_a")
    g.record_failure(1, "Vision.execute_step", "sig_b")
    verdict = g.record_failure(1, "Vision.execute_step", "sig_c")
    assert verdict is GuardrailVerdict.WARN


def test_hard_stop_after_same_tool_failure_threshold():
    g = make_guardrail()
    verdict = GuardrailVerdict.CONTINUE
    for i in range(8):
        verdict = g.record_failure(1, "Vision.execute_step", f"sig_{i}")
    assert verdict is GuardrailVerdict.HARD_STOP


def test_no_progress_warn_threshold():
    g = make_guardrail()
    g.record_no_progress(2, "Vision.execute_step")
    verdict = g.record_no_progress(2, "Vision.execute_step")
    assert verdict is GuardrailVerdict.WARN


def test_reset_clears_step_state():
    g = make_guardrail()
    g.record_failure(1, "Vision.execute_step", "button_not_found")
    g.record_failure(1, "Vision.execute_step", "button_not_found")
    g.reset(1)
    verdict = g.record_failure(1, "Vision.execute_step", "button_not_found")
    assert verdict is GuardrailVerdict.CONTINUE


def test_steps_are_tracked_independently():
    g = make_guardrail()
    g.record_failure(1, "Vision.execute_step", "sig")
    g.record_failure(1, "Vision.execute_step", "sig")
    verdict_step2 = g.record_failure(2, "Vision.execute_step", "other_sig")
    assert verdict_step2 is GuardrailVerdict.CONTINUE


def test_hard_stop_disabled_falls_back_to_warn():
    cfg = GuardrailSettings(
        hard_stop_enabled=False,
        warn_after_exact_failure=2,
        hard_stop_after_exact_failure=3,
    )
    g = LoopGuardrail(config=cfg)
    verdict = None
    for _ in range(10):
        verdict = g.record_failure(1, "Vision.execute_step", "sig")
    assert verdict is GuardrailVerdict.WARN
