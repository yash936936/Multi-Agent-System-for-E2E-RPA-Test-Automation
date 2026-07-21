"""
LLM semantic tie-break verifier — Phase W (decisions.md D-047).

Phase U's dual OCR/DOM verification (agents/vision/executor.py) resolves a
genuine disagreement (both locators clear the confidence threshold, but at
different locations) via `settings.dual_verification_tie_break`. Until this
phase every mode was a bare numeric/positional rule (highest confidence,
always-prefer-one-method). This module adds a *semantic* third opinion --
"llm_semantic" mode -- for the specific case a numeric rule structurally
can't handle: OCR and DOM both found *plausible* matches, but the step's
own `target_description` (plain English -- e.g. "the Submit button", "the
email field in the signup form") makes one candidate obviously the correct
target and the other a false positive (a decoy button, a similarly-labeled
link elsewhere on the page).

This is text-only, not a vision/screenshot call -- deliberately scoped
down from "send the LLM a screenshot" to keep this fast, cheap, and
usable with any already-configured text LLM backend (CloudLLMBackend or
HermesAgentBackend), rather than requiring a separate multimodal setup.
The inputs are exactly the structured evidence dual-verification already
collected (OCR matched_text, DOM matched_text/role/strategy) plus the
step's own target_description -- an LLM is well suited to "which of these
two short text snippets is a better match for this description," and
poorly suited to (and not asked to do) pixel-level localization, which
OCR/DOM already handle.

Fails soft, always: any missing config, disabled setting, or transport
error falls back to "no opinion" (None) so the caller
(executor.py::_apply_tie_break) can fall back to its pre-existing
"highest_confidence" behavior. The LLM verifier is a refinement layered on
top of dual verification, never a new required dependency or single point
of failure -- consistent with every other network-capable path in this
codebase (CloudLLMBackend, HermesAgentBackend, capability adapters).

Phase 4 (next-phase plan): backend selection (which of Hermes/cloud
handles this, with a real reachability check first) now delegates to
orchestrator/backend_router.py's select_backend("semantic_tie_break")
rather than this module resolving it independently -- see that module's
docstring for the scope/priority/health-check design. This module keeps
owning the semantic-verification prompt/parsing contract itself; only the
"which backend" question moved.
"""
from __future__ import annotations

import json
import logging

from config.settings import settings

_logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a UI test verification assistant. You will be given a "
    "description of what a test step is trying to interact with, plus two "
    "candidate matches found by two different detection methods (OCR text "
    "recognition and DOM/accessibility-tree lookup). Decide which candidate "
    "is the correct target, or that neither is. "
    'Respond with ONLY a JSON object: {"winner": "ocr"|"dom"|"neither", '
    '"reason": "<one short sentence>"}. No other text.'
)

_USER_TEMPLATE = (
    "Target description (what the test step wants to interact with):\n"
    "{target_description}\n\n"
    "Candidate A (OCR):\n"
    "  matched_text: {ocr_text!r}\n\n"
    "Candidate B (DOM):\n"
    "  matched_text: {dom_text!r}\n"
    "  role: {dom_role!r}\n"
    "  strategy: {dom_strategy!r}\n\n"
    "Which candidate is the correct target for the description above?"
)


def semantic_verify(target_description: str, ocr_result, dom_result) -> str | None:
    """
    Returns "ocr", "dom", or None (no usable opinion -- either the
    verifier isn't configured/enabled, or the call failed, or the model
    said "neither"/gave an unparseable answer). Never raises -- this is a
    best-effort refinement, not a required step.
    """
    if not settings.enable_llm_semantic_verifier:
        return None

    from orchestrator.backend_router import select_backend

    client = select_backend("semantic_tie_break")
    if client is None:
        _logger.info(
            "LLM semantic tie-break requested but backend_router found no "
            "backend both configured and reachable right now -- skipping, "
            "falling back to highest_confidence."
        )
        return None

    user_prompt = _USER_TEMPLATE.format(
        target_description=target_description,
        ocr_text=ocr_result.matched_text if ocr_result.found else None,
        dom_text=dom_result.matched_text if dom_result.found else None,
        dom_role=getattr(dom_result, "role", None),
        dom_strategy=getattr(dom_result, "strategy", None),
    )

    try:
        raw = client.chat(_SYSTEM_PROMPT, user_prompt)
        parsed = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
        winner = parsed.get("winner")
        if winner in ("ocr", "dom"):
            _logger.info(
                "LLM semantic tie-break: chose %s (reason: %s)",
                winner, parsed.get("reason", "<none given>"),
            )
            return winner
        return None
    except Exception as exc:  # noqa: BLE001 - fail soft, never break the run
        _logger.warning(
            "LLM semantic tie-break call failed (%s: %s) -- falling back to "
            "highest_confidence.", type(exc).__name__, exc,
        )
        return None
