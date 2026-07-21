"""
Autonomous form/signup fuzzer — agents/vision/form_fuzzer.py (D-045)

Answers a specific gap in `aura explore`: the existing click-audit engine
(orchestrator/ui_audit_runner.py) test-clicks nav/hero/footer elements and
watches for a visible change, but it never actually fills in a form (a
signup page, a search box, a checkout field) with data and submits it --
there was no code path anywhere in this repo that entered text into a
textbox/combobox and pressed submit without a hand-written spec telling
it exactly what to type. This module closes that gap for the zero
-instruction `aura explore` mode: detect every fillable field on the
current page, generate a value for each (realistic or deliberately
malformed, per PRD FR4's edge-case requirement), fill it, submit, and
report what happened.

Deliberately reuses existing code rather than re-implementing it
(context.md §6's ponytail ladder):
  - Field candidate discovery: agents/vision/dom_locator.snapshot_elements()
    -- the same accessibility-tree snapshot used for click-audit locate.
  - Value generation: agents/data_synth/generator.py's `_generate_value` --
    the same Faker-backed realistic/edge-case generators already used by
    spec-driven runs (agents/planner/spec_generator.py's edge_case_*
    field convention). No second data-generation implementation.
  - Field submission: runtime/hooks/interact.dom_fill()/dom_click() --
    the same Playwright Locator-based primitives the DOM-first click path
    (Phase C) already uses, not a new dispatch mechanism.
  - Locating the submit control and returning afterward: agents/vision/
    dom_locator.locate_dom()/relocate_dom() and
    runtime/hooks/interact.dom_smart_back() -- the same self-heal +
    tab-aware-back primitives added in D-044 for the click-audit path.

Confidence-gated, not a hard pass/fail oracle (matching PRD FR8 and this
codebase's existing click-and-diff philosophy elsewhere): AURA has no way
to know what a "correct" signup response looks like for an arbitrary
site, so this reports what it observed (URL changed, known error-ish or
success-ish wording appeared, or neither) and lets a human or a
--prompt requirement heuristic (ui_audit_runner._check_requirement_prompt)
draw the conclusion, rather than asserting pass/fail itself.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agents.data_synth.generator import generate_value
from agents.vision.dom_locator import locate_dom, relocate_dom, snapshot_elements
from runtime.hooks.interact import dom_click, dom_fill, dom_smart_back

# Accessible-name keyword -> data_synth field key. Longest/most specific
# keywords first so e.g. "confirm password" and "email address" resolve to
# the right generator rather than a coarser partial match.
_FIELD_KEYWORD_MAP: tuple[tuple[str, str], ...] = (
    ("confirm password", "password"),
    ("password", "password"),
    ("email address", "email"),
    ("email", "email"),
    ("username", "username"),
    ("user name", "username"),
    ("phone", "phone"),
    ("mobile", "phone"),
    ("zip", "zip"),
    ("postal", "postal_code"),
    ("date of birth", "dob"),
    ("birth", "dob"),
    ("credit card", "credit_card"),
    ("card number", "credit_card"),
    ("address", "address"),
    ("full name", "name"),
    ("first name", "name"),
    ("last name", "name"),
    ("name", "name"),
)

# Accessible-name/text fragments suggestive of an error or success response,
# used as a lightweight (disclosed-as-heuristic, not certain) signal for
# what happened after submit -- same "keyword heuristic, not language
# understanding" posture as ui_audit_runner._check_requirement_prompt.
_ERROR_MARKERS = ("invalid", "required", "already exists", "already taken", "must be", "doesn't match", "does not match", "error", "try again")
_SUCCESS_MARKERS = ("welcome", "success", "verify your email", "check your inbox", "account created", "thank you", "confirmation")


def classify_field(accessible_name: str) -> str:
    """
    Best-effort keyword classification of a field's accessible name into a
    agents/data_synth/generator.py field key. Falls back to "generic"
    (generator.py's own fallback -- a plausible word, not a crash) when
    nothing matches. Deliberately simple and disclosed as a heuristic
    rather than real language understanding, same posture as every other
    keyword-based decision already in this codebase.
    """
    name_norm = (accessible_name or "").strip().lower()
    for keyword, field_key in _FIELD_KEYWORD_MAP:
        if keyword in name_norm:
            return field_key
    return "generic"


@dataclass
class FilledField:
    label: str
    role: str
    field_key: str
    value_preview: str  # password/credit_card values are masked, everything else shown in full for auditability


@dataclass
class FormFuzzResult:
    filled: list[FilledField] = field(default_factory=list)
    submit_found: bool = False
    submit_clicked: bool = False
    url_before: str = ""
    url_after: str = ""
    url_changed: bool = False
    new_tab_opened: bool = False
    new_tab_url: str | None = None
    error_markers_seen: list[str] = field(default_factory=list)
    success_markers_seen: list[str] = field(default_factory=list)
    note: str = ""


_MASKED_FIELD_KEYS = {"password", "credit_card"}


def _preview(field_key: str, value: str) -> str:
    if field_key in _MASKED_FIELD_KEYS:
        return "*" * min(len(value), 12)
    return value


def fuzz_form(
    page,
    submit_label: str = "submit",
    mode: str = "realistic",
    max_fields: int = 15,
) -> FormFuzzResult:
    """
    Fills every detected textbox/combobox on the current page and submits
    it, per the "autonomously enter random things and check the buttons"
    request this closes. mode:
      - "realistic": plausible-looking values (Faker-backed), the normal
        happy-path signup attempt.
      - "edge_case": deliberately malformed/boundary values (unicode,
        max-length, malformed email, special characters) for every field
        -- reuses generator.py's existing edge_case_* generators, PRD
        FR4's boundary-testing requirement, applied autonomously instead
        of only when a human spec names a specific edge case.
    Never raises on an individual field's fill/submit failure -- each
    field is attempted independently, consistent with the rest of this
    codebase's "one bad element shouldn't take down the whole
    check" posture (see ui_audit_runner._run_click_audit).
    """
    result = FormFuzzResult(url_before=getattr(page, "url", ""))
    pages_before = len(page.context.pages)

    # Phase 3 bug fix (next-phase plan): this function's own docstring
    # already promises "never raises on an individual field's
    # fill/submit failure" -- but snapshot_elements()/locate_dom()/
    # relocate_dom() (the *resolution* calls, as opposed to the
    # dom_fill()/dom_click() dispatch calls already wrapped below) had no
    # exception handling at all. They call Playwright's own
    # page.locator("html").aria_snapshot() with nothing catching a
    # mid-navigation "Execution context was destroyed" (or similar) error
    # -- exactly the kind of thing this function's whole job (fill a form,
    # submit it, observe what happens, including navigation) makes likely,
    # not a rare edge case. See agents/vision/executor.py::_resolve_dom's
    # docstring for the same bug's more consequential twin in the main
    # execute_step path.
    try:
        candidates = [
            c for c in snapshot_elements(page)
            if c["role"] in ("textbox", "searchbox", "combobox")
        ][:max_fields]
    except Exception as e:
        result.note = f"Could not snapshot the page's form fields: {e}"
        return result

    for candidate in candidates:
        field_key = classify_field(candidate["name"])
        if mode == "edge_case":
            lookup_key = "edge_case_malformed" if field_key == "generic" else f"edge_case_{field_key}"
        else:
            lookup_key = field_key
        value = generate_value(lookup_key)

        try:
            located = locate_dom(page, candidate["name"])
            if not located.found:
                located = relocate_dom(page, {"name": candidate["name"]})
        except Exception:
            continue  # same posture as the dom_fill() failure below -- one field's resolution failing shouldn't stop the rest
        if not located.found or located.locator is None:
            continue

        try:
            dom_fill(located.locator, value)
            result.filled.append(FilledField(
                label=candidate["name"], role=candidate["role"], field_key=field_key,
                value_preview=_preview(field_key, value),
            ))
        except Exception:
            continue  # one field failing to fill shouldn't stop the rest -- reported implicitly by its absence from `filled`

    try:
        submit = locate_dom(page, submit_label)
        if not submit.found:
            # Try a couple of common alternates before giving up -- real signup
            # forms use "Sign up", "Create account", "Register" far more often
            # than the literal word "submit".
            for alt in ("sign up", "create account", "register", "continue"):
                submit = locate_dom(page, alt)
                if submit.found:
                    break
    except Exception as e:
        result.note = f"Form was filled but the submit button couldn't be resolved: {e}"
        return result

    if not submit.found or submit.locator is None:
        result.note = "No submit-like button found -- form was filled but not submitted."
        return result

    result.submit_found = True
    try:
        dom_click(submit.locator)
        result.submit_clicked = True
    except Exception as e:
        result.note = f"Found a submit-like button but the click failed: {e}"
        return result

    # Deliberately observe the result *before* touching navigation at all --
    # a naive "always go back afterward" (reusing dom_smart_back verbatim,
    # as the click-audit path does) would call page.go_back() right here
    # and erase the very outcome (a redirect to a "welcome"/"verify your
    # email" page, or a same-page validation error) this function exists to
    # report. New tabs are the one case that's still safe to reconcile
    # immediately, since the main page never navigated away in that case.
    try:
        page.wait_for_load_state("networkidle", timeout=4000)
    except Exception:
        pass  # best-effort only -- still read whatever state exists below, same posture as the rest of this pipeline

    if len(page.context.pages) > pages_before:
        back = dom_smart_back(page, pages_before)
        result.new_tab_opened = back.new_tab_opened
        result.new_tab_url = back.new_tab_url

    result.url_after = getattr(page, "url", "")
    result.url_changed = bool(result.url_before) and result.url_after != result.url_before

    # Same best-effort posture as the wait_for_load_state above: a submit
    # that navigated the page can leave this snapshot racing a destroyed
    # execution context. Report no markers seen rather than crash -- the
    # url_changed/new_tab_opened signals above already captured the
    # navigation itself either way.
    try:
        after_text = " ".join(c["name"].lower() for c in snapshot_elements(page))
        result.error_markers_seen = [m for m in _ERROR_MARKERS if m in after_text]
        result.success_markers_seen = [m for m in _SUCCESS_MARKERS if m in after_text]
    except Exception:
        pass

    return result
