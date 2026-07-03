"""
Test-spec explainer — agents/planner/explainer.py

Generates a short, plain-English narrative summary of what a TestSpec
actually checks, for non-technical stakeholders reviewing the HTML
report (feature roadmap item: "explain this test"). Pure Python over
the already-structured TestSpec -- no LLM/network call needed, since
the Planner has already done the hard work of extracting structure;
this just narrates it back out in prose.

Deliberately NOT a tool in config/tool_registry.yaml: it's a read-only
presentation helper over data that already exists, not a step in the
Planner -> Vision -> DataSynth pipeline, so it doesn't need kernel
dispatch/audit-trail treatment the way the real agent tools do.
"""
from __future__ import annotations

from orchestrator.schemas import ActionType, TestSpec, TestStep


def _describe_step(step: TestStep) -> str:
    if step.action is ActionType.VISUAL_CLICK:
        target = step.target_description or "an on-screen element"
        return f"click {target}"
    if step.action is ActionType.TYPE_TEXT:
        field = step.field_description or "a field"
        return f"enter a value into {field}"
    if step.action is ActionType.SCROLL:
        return "scroll the screen"
    if step.action is ActionType.ASSERT:
        state = step.expected_state or "the expected state"
        return f"verify that {state} is visible"
    return f"perform a {step.action.value} action"  # pragma: no cover - exhaustive over current enum


def explain_spec(spec: TestSpec) -> str:
    """
    Returns a short multi-sentence plain-English narrative describing what
    this TestSpec exercises: the starting conditions, what the test does
    step by step, and what it ultimately checks. Intended for a report
    reader who doesn't want to parse structured JSON steps.
    """
    sentences: list[str] = []

    sentences.append(f'Test "{spec.test_id}" (ref: {spec.requirement_ref}).')

    if spec.preconditions:
        readable_preconditions = [p.replace("_", " ") for p in spec.preconditions]
        sentences.append("Starting conditions: " + "; ".join(readable_preconditions) + ".")

    if spec.steps:
        step_phrases = [_describe_step(s) for s in spec.steps]
        if len(step_phrases) == 1:
            body = step_phrases[0]
        elif len(step_phrases) == 2:
            body = f"{step_phrases[0]}, then {step_phrases[1]}"
        else:
            body = ", ".join(step_phrases[:-1]) + f", then {step_phrases[-1]}"
        sentences.append(f"The test will {body}.")

    if spec.assertions:
        expected = [a.expected.replace("_", " ") for a in spec.assertions]
        if len(expected) == 1:
            sentences.append(f"Success is confirmed by checking that {expected[0]} is visible.")
        else:
            sentences.append(
                "Success is confirmed by checking that all of the following are visible: "
                + ", ".join(expected)
                + "."
            )

    if spec.data_requirements:
        edge_cases = [d for d in spec.data_requirements if d.startswith("edge_case_")]
        regular = [d for d in spec.data_requirements if not d.startswith("edge_case_")]
        data_bits = []
        if regular:
            data_bits.append("realistic synthetic values for " + ", ".join(f.replace("_", " ") for f in regular))
        if edge_cases:
            data_bits.append(
                "edge-case data covering " + ", ".join(e.removeprefix("edge_case_").replace("_", " ") for e in edge_cases)
            )
        if data_bits:
            sentences.append("The test uses " + " and ".join(data_bits) + ".")

    return " ".join(sentences)
