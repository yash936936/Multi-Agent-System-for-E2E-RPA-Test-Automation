"""
Continuous-audit / run-monitor agent — agents/auditor/run_monitor.py

Next-phase plan, Phase 1. This is genuinely new: agents/auditor/code_auditor.py
is static-source-only (AST/ruff over files at rest) and has nothing to do with
a live run, so there's no overlap to reuse there. This module is the
"second opinion" layer that sits alongside RunEngine, not inside it --
RunEngine calls review_step()/log_verdict() the same way it already calls
on_step_result(), just with the added ability to push a result back into
the existing self-healing retry path.

Design choices, and why:

- **Independent of the step's own confidence score.** A step's `escalate`
  flag only fires when *its own* detection confidence is low. The failure
  mode this phase targets is different: the step was confident, dispatched
  successfully, and self-reported "fulfilled" -- but the run still moved on
  prematurely (wrong outcome, right confidence). So this reviews the
  *evidence*, not just the confidence number, and is skipped for steps that
  already escalated on their own (nothing to second-guess there; the
  existing healing_loop already owns that case).

- **Text-over-evidence, not vision-over-screenshot.** Every LLM backend
  wired into this codebase so far (HermesAgentClient, CloudLLMBackend, via
  llm_verifier.py's `_get_backend_client()`) exposes a text-only
  `.chat(system, user) -> str` contract -- none of them do multimodal
  image input today. Rather than stand up a second, separate multimodal
  client (a real "which backend for which task" decision that Phase 4's
  backend_router.py is explicitly meant to own, not this phase), this
  reviews the same *compiled* evidence the step itself already produced:
  target_description/expected_state (what was supposed to happen) against
  confidence/assertion_passed/verification_method/verification_evidence
  (what the step says did happen). That's a genuine second opinion -- a
  different reasoning pass over the same facts -- even though it isn't
  looking at pixels directly. Swapping in a vision-capable backend later
  is a change to `_build_user_prompt`/`_get_backend_client` only; nothing
  about the RunEngine wiring below needs to change.

- **Fails soft, always.** No configured/reachable backend, or a call that
  errors or returns unparseable JSON, all resolve to `agrees=True,
  checked=False` -- "no opinion" defers to the step's own self-report
  rather than blocking or falsely flagging the run. This mirrors
  llm_verifier.semantic_verify()'s existing fail-soft contract exactly.
  `checked` distinguishes "the monitor actually reviewed this and agreed"
  from "the monitor had nothing to say" -- both log, but only the former
  is a real second opinion.

- **Never a silent side-channel.** Every verdict -- agreement or
  disagreement, checked or not -- is written through the existing
  orchestrator/audit_logger.py sink, the same discipline the rest of the
  system already holds itself to (see capability_router.py's
  CAPABILITY_EGRESS audit entries).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from orchestrator.audit_logger import audit_logger
from orchestrator.schemas import TestStep, VisionActionResult

_logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are an independent QA auditor reviewing one step of an automated UI "
    "test run. You did not perform the step yourself and cannot see the "
    "screen -- you are a second opinion checking whether the step's own "
    "self-reported evidence actually supports the outcome it claims. You "
    "will be given the step's declared intent and the evidence it produced. "
    "Decide whether that evidence genuinely supports the step being "
    "fulfilled, or whether it looks like the run moved on prematurely. "
    'Respond with ONLY a JSON object: {"agrees": true|false, "reason": '
    '"<one short sentence>"}. No other text.'
)

_USER_TEMPLATE = (
    "Step {step_id} -- action: {action}\n"
    "Target description: {target_description!r}\n"
    "Expected state (if any): {expected_state!r}\n\n"
    "Step's own self-reported evidence:\n"
    "  confidence: {confidence}\n"
    "  assertion_passed: {assertion_passed}\n"
    "  verification_method: {verification_method}\n"
    "  verification_evidence: {verification_evidence}\n\n"
    "Does this evidence genuinely support the step being fulfilled?"
)


@dataclass
class MonitorVerdict:
    step_id: int
    agrees: bool
    reason: str
    # False whenever the monitor had no real opinion (backend not
    # configured, unreachable, or gave an unparseable answer) -- agrees
    # defaults True in that case so an unconfigured monitor never blocks a
    # run, but `checked=False` records that this wasn't a genuine review.
    checked: bool


def _get_backend_client():
    """
    Resolves whichever text LLM backend is actually configured and
    currently reachable, via orchestrator/backend_router.py (Phase 4,
    next-phase plan) -- centralizes exactly this Hermes-then-cloud
    resolution logic (previously duplicated between this module and
    agents/vision/llm_verifier.py) in one place, with a real reachability
    check before a task is committed to a backend. See that module's
    docstring for the scope/priority/health-check design.
    """
    from orchestrator.backend_router import select_backend

    return select_backend("continuous_audit")


def review_step(step: TestStep, result: VisionActionResult) -> MonitorVerdict:
    """
    Independent second opinion on whether `result` (the step's own
    self-reported outcome) should be trusted. Never raises -- see the
    module docstring's "fails soft, always" note.
    """
    if result.escalate:
        return MonitorVerdict(
            step_id=step.step_id,
            agrees=True,
            reason="step already escalated on its own; not re-reviewed",
            checked=False,
        )

    client = _get_backend_client()
    if client is None:
        return MonitorVerdict(
            step_id=step.step_id,
            agrees=True,
            reason="no LLM backend configured -- continuous-audit monitor skipped",
            checked=False,
        )

    user_prompt = _USER_TEMPLATE.format(
        step_id=step.step_id,
        action=result.action_taken,
        target_description=step.target_description or step.field_description,
        expected_state=step.expected_state,
        confidence=result.confidence,
        assertion_passed=result.assertion_passed,
        verification_method=result.verification_method,
        verification_evidence=result.verification_evidence,
    )

    try:
        raw = client.chat(_SYSTEM_PROMPT, user_prompt)
        parsed = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        agrees = bool(parsed.get("agrees", True))
        reason = str(parsed.get("reason", ""))
        return MonitorVerdict(step_id=step.step_id, agrees=agrees, reason=reason, checked=True)
    except Exception as exc:  # noqa: BLE001 - fail soft, never break the run
        _logger.warning(
            "Continuous-audit monitor call failed for step %s: %s -- "
            "defaulting to agree (fail-soft, matches llm_verifier's contract).",
            step.step_id, exc,
        )
        return MonitorVerdict(
            step_id=step.step_id, agrees=True, reason=f"monitor call failed: {exc}", checked=False,
        )


def log_verdict(run_id: str, verdict: MonitorVerdict) -> None:
    """
    Writes every verdict through the existing audit trail -- agreement or
    disagreement, checked or not. tenant_id/user_id are "system" here for
    the same reason capability_router.py's CAPABILITY_EGRESS entries use
    "system": this fires from inside RunEngine's own execution loop, which
    doesn't carry the calling user's tenant/user id down to step level.
    """
    audit_logger.log(
        tenant_id="system",
        user_id="system",
        action="CONTINUOUS_AUDIT_VERDICT",
        resource=run_id,
        details={
            "step_id": verdict.step_id,
            "agrees": verdict.agrees,
            "reason": verdict.reason,
            "checked": verdict.checked,
        },
    )
