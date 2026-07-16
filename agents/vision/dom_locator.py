"""
DOM locator — agents/vision/dom_locator.py (Phase C / TRD §10)

Accessibility-tree-first element resolution for browser targets, replacing
raw pixel/OCR guessing as the *primary* path (agents/vision/locator.py's
OCR pipeline remains the fallback for targets with no accessibility tree,
e.g. native desktop apps -- see agents/vision/executor.py).

Two responsibilities, mirroring docs/external_repos.md's Batch 1 & 6
findings:

1. `locate_dom()` -- capture a Playwright accessibility snapshot, resolve
   the target_description against it (role/name text matching, reusing
   agents.vision.locator's word-overlap scoring so both paths score
   similarly), and return a live Playwright Locator for the best match --
   never a raw screen coordinate for a browser target.

2. `relocate_dom()` -- a Scrapling-style (D4Vinci/Scrapling `relocate()`,
   docs/external_repos.md Batch 6) DOM self-heal: re-snapshot the page,
   score every current candidate against the target description with a
   *relaxed* threshold (0.40, matching Scrapling's own default), and
   return the best match(es) -- logging the top score found even on
   failure rather than silently returning nothing, and returning ties
   rather than guessing when multiple candidates share the top score.
   This is tried by the executor before falling all the way back to
   OCR/vision, per TRD §10 point 3.

Confidence returned by both functions reflects *locator resolution
quality* (exact accessible-name match vs. fuzzy text match vs. multiple
ambiguous candidates) rather than an OCR fuzzy-match ratio -- but is still
a float in [0, 1] gated against the same `settings.vision_confidence_threshold`
as the OCR path, so `VisionActionResult`'s schema doesn't change shape
(TRD §10's explicit non-goal).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.vision.locator import _match_score

# Scrapling's own default relocate() threshold (docs/external_repos.md
# Batch 6: "clears a configurable `percentage` threshold (default 40%)").
RELOCATE_MIN_RATIO = 0.40

# Accessibility roles Playwright's get_by_role() understands that are
# actually clickable/fillable targets in ordinary web UIs -- restricting to
# these (rather than every ARIA role, e.g. "generic"/"none") keeps
# candidate lists focused on things a test step would plausibly target.
_INTERACTIVE_ROLES = (
    "button", "link", "textbox", "checkbox", "radio", "combobox", "menuitem",
    "tab", "switch", "searchbox", "option", "listitem", "heading", "cell",
)


@dataclass
class DomLocateResult:
    found: bool
    locator: Any = None
    confidence: float = 0.0
    matched_text: str = ""
    role: str = ""
    strategy: str = ""  # "exact_name" | "fuzzy_text" | "relocate" | ""
    ambiguous_count: int = 0
    top_score_seen: float = 0.0  # populated even when found=False, per Scrapling's "log the top score" UX
    # Phase U (docs/decisions.md D-043): the resolved element's on-screen
    # bounding box ({"x", "y", "width", "height"}, Playwright's own
    # bounding_box() shape), best-effort populated whenever a locator was
    # actually resolved. Used by agents/vision/executor.py's OCR/DOM
    # compilation step to decide whether the two methods' locations
    # genuinely overlap (agreement) or point at different places
    # (disagreement, tie-break required) -- never populated when
    # found=False, since there is no element to measure.
    bbox: dict | None = None


def _flatten(node: dict, out: list[dict]) -> None:
    if not isinstance(node, dict):
        return
    role = node.get("role", "")
    name = (node.get("name") or "").strip()
    if role and role not in ("WebArea", "generic", "none") and name:
        out.append({"role": role, "name": name})
    for child in node.get("children", []) or []:
        _flatten(child, out)


def snapshot_elements(page) -> list[dict]:
    """
    Flattens Playwright's accessibility.snapshot() tree into a flat list of
    {"role": str, "name": str} candidates. Interactive-role-only nodes with
    non-empty accessible names -- text-only decorative nodes aren't useful
    click/type targets and would just add noise to scoring.
    """
    tree = page.accessibility.snapshot()
    out: list[dict] = []
    if tree:
        _flatten(tree, out)
    return [el for el in out if el["role"] in _INTERACTIVE_ROLES]


def _build_locator(page, role: str, name: str):
    """
    Resolves a role+name candidate to a live Playwright Locator, per
    docs/external_repos.md Batch 1's "resolve-by-reference, pixel dispatch
    last" pattern. Falls back to get_by_text() for roles get_by_role()
    doesn't recognize.
    """
    try:
        return page.get_by_role(role, name=name, exact=False).first
    except Exception:
        return page.get_by_text(name, exact=False).first


def _score_candidates(target_description: str, candidates: list[dict]) -> list[tuple[dict, float]]:
    target_norm = target_description.strip().lower()
    scored = [(c, _match_score(target_norm, c["name"].lower())) for c in candidates]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored


def _resolve_bbox(locator) -> dict | None:
    """
    Best-effort Playwright bounding_box() read (Phase U, D-043) -- returns
    None rather than raising if the element isn't visible/measurable
    (detached, off-screen, or the locator itself failed to resolve to a
    single element). A missing bbox just means the overlap check in
    executor.py can't confirm agreement geometrically and falls through to
    the tie-break path -- it's evidence of "couldn't measure," not a bug.
    """
    try:
        return locator.bounding_box()
    except Exception:
        return None


def locate_dom(page, target_description: str, min_ratio: float = 0.55) -> DomLocateResult:
    """
    Primary resolution path for browser targets: snapshot the accessibility
    tree, score every interactive candidate against target_description, and
    return a Locator for the best match if it clears min_ratio.
    """
    candidates = snapshot_elements(page)
    if not candidates:
        return DomLocateResult(found=False)

    scored = _score_candidates(target_description, candidates)
    best, best_score = scored[0]
    top_ties = [c for c, s in scored if s == best_score]

    if best_score < min_ratio:
        return DomLocateResult(found=False, top_score_seen=round(best_score, 4))

    strategy = "exact_name" if best_score >= 0.95 else "fuzzy_text"
    locator = _build_locator(page, best["role"], best["name"])
    return DomLocateResult(
        found=True,
        locator=locator,
        confidence=round(min(best_score, 0.99), 4),
        matched_text=best["name"],
        role=best["role"],
        strategy=strategy,
        ambiguous_count=len(top_ties),
        top_score_seen=round(best_score, 4),
        bbox=_resolve_bbox(locator),
    )


def relocate_dom(page, last_known: dict, min_ratio: float = RELOCATE_MIN_RATIO) -> DomLocateResult:
    """
    Scrapling-style DOM self-heal (docs/external_repos.md Batch 6): given a
    previously-known {"role", "name"} element that failed to resolve via
    locate_dom() at the primary threshold, re-score every *current*
    candidate against it with a relaxed threshold, and return the best
    match -- or, if nothing clears the threshold, report the top score
    found rather than silently returning nothing (top_score_seen is always
    populated). Ties at the top score are preserved via ambiguous_count
    rather than arbitrarily picked, matching relocate()'s own behavior.
    """
    candidates = snapshot_elements(page)
    if not candidates:
        return DomLocateResult(found=False)

    target_text = (last_known or {}).get("name", "")
    scored = _score_candidates(target_text, candidates)
    best, best_score = scored[0]
    top_ties = [c for c, s in scored if s == best_score]

    if best_score < min_ratio:
        return DomLocateResult(found=False, top_score_seen=round(best_score, 4))

    locator = _build_locator(page, best["role"], best["name"])
    return DomLocateResult(
        found=True,
        locator=locator,
        confidence=round(min(best_score, 0.99), 4),
        matched_text=best["name"],
        role=best["role"],
        strategy="relocate",
        ambiguous_count=len(top_ties),
        top_score_seen=round(best_score, 4),
        bbox=_resolve_bbox(locator),
    )
