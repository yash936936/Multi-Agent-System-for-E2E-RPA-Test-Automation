from __future__ import annotations

from config.settings import GuardrailSettings
from orchestrator.guardrails import GuardrailVerdict, LoopGuardrail, compute_evidence_fingerprint


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


# -- AD2 (docs/decisions.md D-062): compute_evidence_fingerprint() -----------

def test_fingerprint_none_when_raw_evidence_is_none():
    assert compute_evidence_fingerprint("ocr", None) is None


def test_fingerprint_identical_for_identical_evidence():
    fp1 = compute_evidence_fingerprint("ocr", {"ocr_text_found": "Submit", "confidence": 0.4})
    fp2 = compute_evidence_fingerprint("ocr", {"ocr_text_found": "Submit", "confidence": 0.4})
    assert fp1 == fp2


def test_fingerprint_differs_for_different_evidence():
    fp1 = compute_evidence_fingerprint("ocr", {"ocr_text_found": "Submit"})
    fp2 = compute_evidence_fingerprint("ocr", {"ocr_text_found": "Cancel"})
    assert fp1 != fp2


def test_fingerprint_differs_for_different_source_same_evidence_shape():
    fp1 = compute_evidence_fingerprint("ocr", {"x": 1})
    fp2 = compute_evidence_fingerprint("dom", {"x": 1})
    assert fp1 != fp2


def test_fingerprint_key_order_independent():
    fp1 = compute_evidence_fingerprint("ocr", {"a": 1, "b": 2})
    fp2 = compute_evidence_fingerprint("ocr", {"b": 2, "a": 1})
    assert fp1 == fp2


# -- AD2: LoopGuardrail.record_evidence() short-circuit -----------------------

def test_record_evidence_first_call_continues_and_stores_fingerprint():
    g = make_guardrail()
    verdict = g.record_evidence(step_id=1, tool_name="Vision.execute_step", evidence_fingerprint="fp-a")
    assert verdict is GuardrailVerdict.CONTINUE


def test_record_evidence_none_fingerprint_never_short_circuits():
    g = make_guardrail()
    v1 = g.record_evidence(1, "Vision.execute_step", None)
    v2 = g.record_evidence(1, "Vision.execute_step", None)
    assert v1 is GuardrailVerdict.CONTINUE
    assert v2 is GuardrailVerdict.CONTINUE


def test_record_evidence_identical_fingerprint_short_circuits_to_hard_stop():
    g = make_guardrail()
    g.record_evidence(1, "Vision.execute_step", "fp-a")
    verdict = g.record_evidence(1, "Vision.execute_step", "fp-a")
    assert verdict is GuardrailVerdict.HARD_STOP


def test_record_evidence_different_fingerprint_does_not_short_circuit():
    g = make_guardrail()
    g.record_evidence(1, "Vision.execute_step", "fp-a")
    verdict = g.record_evidence(1, "Vision.execute_step", "fp-b")
    assert verdict is GuardrailVerdict.CONTINUE


def test_record_evidence_short_circuit_disabled_via_config():
    cfg = GuardrailSettings(short_circuit_on_identical_evidence=False)
    g = LoopGuardrail(config=cfg)
    g.record_evidence(1, "Vision.execute_step", "fp-a")
    verdict = g.record_evidence(1, "Vision.execute_step", "fp-a")
    assert verdict is GuardrailVerdict.CONTINUE


def test_record_evidence_short_circuit_reflected_in_state_snapshot():
    g = make_guardrail()
    g.record_evidence(1, "Vision.execute_step", "fp-a")
    g.record_evidence(1, "Vision.execute_step", "fp-a")
    assert g.state_snapshot(1)["identical_evidence_short_circuited"] is True


def test_reset_clears_evidence_fingerprint_history():
    g = make_guardrail()
    g.record_evidence(1, "Vision.execute_step", "fp-a")
    g.reset(1)
    # After reset, "fp-a" again should be treated as the *first* sighting,
    # not a repeat -- proves reset() clears AD2's fingerprint state too,
    # not just the count-based fields.
    verdict = g.record_evidence(1, "Vision.execute_step", "fp-a")
    assert verdict is GuardrailVerdict.CONTINUE
