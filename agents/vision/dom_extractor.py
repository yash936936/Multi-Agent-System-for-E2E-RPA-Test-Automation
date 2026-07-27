"""
DOM extractor — agents/vision/dom_extractor.py

Live-DOM interactive-element detection, supplementing dom_locator.py's
ARIA-snapshot path and ui_audit.py's OCR-band path with a third signal:
a direct JS walk of the rendered DOM.

Why this exists (docs/external_repos.md correction, see context.md/user
history): browser-use/browser-use's `buildDomTree.js` demonstrated that
ARIA roles alone under-detect real click targets on modern client-side-
rendered React/Next.js sites, because a large fraction of custom controls
(a `<div onClick=...>` styled as a button, an icon-only nav toggle with no
accessible name, a card that's clickable via a wrapping handler) carry no
ARIA role and no readable static text at all -- invisible to both
agents/vision/dom_locator.py's aria_snapshot() walk and
agents/vision/ui_audit.py's OCR-band heuristic.

This module does NOT use browser-use itself (no LLM agent loop, no
network dependency -- AURA stays offline-by-construction). It reimplements
just the one genuinely offline-portable idea from that project: inject a
small piece of JS that walks the live DOM, flags elements interactive by
tag/role/tabindex/cursor-style/handler-attribute (not by asking an LLM),
filters to what's actually visible in the current viewport, and returns a
flat, indexed list Python can consume directly -- no copied source, an
AURA-native implementation of the same detection strategy.

Two entry points:
  - extract_interactive_elements(page) -> list[DomElement]: raw indexed
    scan, used by dom_locator.py callers that want every real click target,
    not just ARIA-labeled ones.
  - to_ui_elements(page, page_height) -> list[UIElement]: adapts the same
    scan into agents.vision.ui_audit.UIElement records (band-classified by
    y-position, same band boundaries ui_audit.py already uses) so
    orchestrator/ui_audit_runner.py's explore/click-audit loop can merge
    DOM-sourced candidates into its existing OCR-sourced candidate list
    with zero schema changes downstream.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

# Kept in one file (not a separate .js asset) so this module has no
# filesystem dependency beyond the Python file itself -- easier to audit,
# easier to keep in sync with the dataclass shape below.
_EXTRACT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const vw = window.innerWidth;
  const vh = window.innerHeight;

  const NATIVE_INTERACTIVE_TAGS = new Set([
    "a", "button", "input", "select", "textarea", "summary", "option",
  ]);

  function isVisible(el, rect) {
    if (rect.width <= 0 || rect.height <= 0) return false;
    const style = window.getComputedStyle(el);
    if (style.visibility === "hidden" || style.display === "none") return false;
    if (parseFloat(style.opacity) === 0) return false;
    // In-viewport only, matching what a real user could actually see and
    // click without scrolling -- callers that need off-screen elements
    // still have dom_locator.py's aria_snapshot() path, which isn't
    // viewport-limited.
    if (rect.bottom < 0 || rect.top > vh || rect.right < 0 || rect.left > vw) return false;
    return true;
  }

  function looksInteractive(el) {
    const tag = el.tagName.toLowerCase();
    if (NATIVE_INTERACTIVE_TAGS.has(tag)) return true;
    const role = el.getAttribute("role");
    if (role && ["button", "link", "checkbox", "radio", "tab", "menuitem", "switch"].includes(role)) return true;
    if (el.hasAttribute("tabindex") && el.getAttribute("tabindex") !== "-1") return true;
    if (el.hasAttribute("onclick")) return true;
    // Custom clickable divs/spans styled as controls but with no semantic
    // markup at all -- exactly the case buildDomTree.js's "cursor: pointer"
    // heuristic exists for, and the case ARIA-snapshot-only detection
    // (agents/vision/dom_locator.py) structurally cannot catch.
    const style = window.getComputedStyle(el);
    if (style.cursor === "pointer" && (tag === "div" || tag === "span" || tag === "li")) return true;
    return false;
  }

  function accessibleName(el) {
    const aria = el.getAttribute("aria-label");
    if (aria && aria.trim()) return aria.trim();
    const text = (el.innerText || el.value || el.placeholder || "").trim();
    return text.slice(0, 120);
  }

  const all = document.querySelectorAll("*");
  let index = 0;
  for (const el of all) {
    if (!looksInteractive(el)) continue;
    const rect = el.getBoundingClientRect();
    if (!isVisible(el, rect)) continue;
    const name = accessibleName(el);
    if (!name) continue;
    // Dedup identical (tag, name, rounded-position) triples -- common with
    // icon+label pairs both matching looksInteractive() for the same
    // visual control.
    const key = tag_key(el, rect, name);
    if (seen.has(key)) continue;
    seen.add(key);

    out.push({
      index: index++,
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute("role") || "",
      name: name,
      cx: Math.round(rect.left + rect.width / 2),
      cy: Math.round(rect.top + rect.height / 2),
      // Document-relative y (adds the current scroll offset) -- used
      // for landmark band classification against the *page's* total
      // height. `cy` above is deliberately left viewport-relative
      // (Playwright's page.mouse.click() operates in viewport/CSS
      // space, not document space), since callers dispatch clicks
      // straight at (cx, cy) via Playwright's mouse -- see
      // orchestrator/ui_audit_runner.py's "dom_extractor_direct"
      // dispatch path. Using this same viewport-relative cy for
      // band classification (dividing it by the full document
      // scrollHeight) was a real bug: on any page taller than one
      // viewport, this made every currently-visible element's
      // fraction-of-page-height collapse toward 0, misclassifying
      // hero/body elements as "nav".
      docY: Math.round(rect.top + window.scrollY + rect.height / 2),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    });
  }

  function tag_key(el, rect, name) {
    return el.tagName.toLowerCase() + "|" + name + "|" + Math.round(rect.left / 8) + "|" + Math.round(rect.top / 8);
  }

  return out;
}
"""


@dataclass
class DomElement:
    index: int
    tag: str
    role: str
    name: str
    cx: int
    cy: int
    width: int
    height: int
    doc_y: int = 0


def extract_interactive_elements(page) -> list[DomElement]:
    """
    Runs the JS walk against the live page and returns a flat, indexed
    list of every currently-visible interactive-looking element -- native
    controls, ARIA-role controls, and cursor-styled custom controls alike.

    Returns [] rather than raising if evaluate() fails for any reason
    (detached page, navigation mid-scan) -- callers treat an empty result
    the same as "nothing found," never as an error, matching
    dom_locator.py's snapshot_elements()/locate_dom() failure shape.
    """
    try:
        raw = page.evaluate(_EXTRACT_JS)
    except Exception as e:
        logging.getLogger(__name__).debug(
            "extract_interactive_elements: page.evaluate failed (%s) -- treating as no elements found.", e
        )
        return []
    if not raw:
        return []
    return [
        DomElement(
            index=item.get("index", i),
            tag=item.get("tag", ""),
            role=item.get("role", ""),
            name=item.get("name", ""),
            cx=item.get("cx", 0),
            cy=item.get("cy", 0),
            width=item.get("width", 0),
            height=item.get("height", 0),
            doc_y=item.get("docY", item.get("cy", 0)),
        )
        for i, item in enumerate(raw)
    ]


def to_ui_elements(page, page_height: int):
    """
    Adapts extract_interactive_elements()'s output into
    agents.vision.ui_audit.UIElement records, band-classified with the
    same boundaries ui_audit.py's OCR path already uses, so
    orchestrator/ui_audit_runner.py can merge DOM-sourced candidates into
    its existing all_elements list with no schema changes. Import is
    local to avoid a hard import-time dependency from dom_extractor.py
    (a low-level module) back up to ui_audit.py.

    `page_height` is expected to be the full document height
    (document.documentElement.scrollHeight), matching `doc_y`'s
    coordinate space. Band classification uses `doc_y` (document-
    relative), NOT `cy` (viewport-relative) -- an earlier version of
    this function divided the viewport-relative `cy` by the full
    document height, which on any page taller than one viewport
    silently collapsed every visible element's fraction toward 0 and
    misclassified hero/body elements (anything below the very top of
    the viewport) as "nav". `cx`/`cy` themselves are still returned
    viewport-relative in the resulting UIElement, because callers
    dispatch clicks straight at (cx, cy) via Playwright's mouse, which
    operates in viewport space, not document space.
    """
    from agents.vision.ui_audit import UIElement, _NAV_BAND_END, _HERO_BAND_END, _FOOTER_BAND_START

    elements = extract_interactive_elements(page)
    out = []
    for el in elements:
        frac = (el.doc_y / page_height) if page_height else 0.0
        if frac < _NAV_BAND_END:
            band = "nav"
        elif frac >= _FOOTER_BAND_START:
            band = "footer"
        elif frac < _HERO_BAND_END:
            band = "hero"
        else:
            band = "body"
        out.append(UIElement(text=el.name, cx=el.cx, cy=el.cy, band=band, looks_interactive=True))
    return out


def to_ui_elements_full_page(page, max_steps: int = 20):
    """
    Like to_ui_elements(), but not limited to whatever's currently in the
    viewport. extract_interactive_elements()'s JS walk deliberately only
    ever sees on-screen elements (see its module docstring) -- fine for a
    single snapshot, but on any page taller than one viewport this meant
    below-the-fold content (a footer's links, for instance) was simply
    never discovered by the DOM path at all, with no error or signal that
    anything had been skipped.

    This scrolls window.scrollTo(0, y) in viewport-height increments from
    the top of the document to the bottom (capped at max_steps, matching
    the same "an unattended loop needs a stop condition" philosophy as
    orchestrator/autoscan.py and orchestrator/ui_audit_runner.py's own
    max_elements cap), calling to_ui_elements() at each stop and merging
    results. Duplicates (the same element visible across two overlapping
    scroll positions, or a sticky/fixed-position element visible at every
    scroll position by construction) are removed by (text, band) -- the
    same key granularity orchestrator/ui_audit_runner.py's own click-
    resolution loop already uses to recognize a DOM-sourced element, so
    this doesn't introduce a second, finer-grained notion of "the same
    element" the rest of the pipeline doesn't share.

    Each returned UIElement's `scroll_y` records the exact window.scrollY
    the page was at when its cx/cy were measured -- callers MUST scroll
    back to that position before dispatching a click at (cx, cy), since
    those coordinates are viewport-relative and only valid at the scroll
    position they were captured at (see UIElement.scroll_y's docstring).

    Restores the page's original scroll position before returning,
    win or lose (even if evaluate() fails partway through), so this is
    transparent to callers that don't expect their page to end up
    scrolled somewhere unexpected as a side effect of discovery.
    """
    original_scroll_y = 0
    try:
        original_scroll_y = int(page.evaluate("window.scrollY") or 0)
    except Exception:
        original_scroll_y = 0

    try:
        viewport_height = int(page.evaluate("window.innerHeight") or 720)
    except Exception:
        viewport_height = 720
    try:
        doc_height = int(page.evaluate("document.documentElement.scrollHeight") or viewport_height)
    except Exception:
        doc_height = viewport_height

    seen: set[tuple] = set()
    out = []
    step = max(int(viewport_height), 1)
    scroll_positions = list(range(0, max(int(doc_height) - step, 0) + 1, step)) or [0]
    scroll_positions = scroll_positions[:max_steps]
    # Always include the very bottom of the page, even if it doesn't
    # land on an exact step boundary -- otherwise a footer just past the
    # last full increment could be missed entirely.
    bottom = max(int(doc_height) - step, 0)
    if bottom not in scroll_positions:
        scroll_positions.append(bottom)

    try:
        for scroll_y in scroll_positions:
            try:
                page.evaluate(f"window.scrollTo(0, {scroll_y})")
                try:
                    actual_scroll_y = int(page.evaluate("window.scrollY") or scroll_y)
                except Exception:
                    actual_scroll_y = scroll_y
                elements = to_ui_elements(page, doc_height)
                for el in elements:
                    key = (el.text.strip().lower(), el.band)
                    if key in seen:
                        continue
                    seen.add(key)
                    el.scroll_y = actual_scroll_y
                    out.append(el)
            except Exception:
                # This one scroll position failed for any reason (mock
                # page with a simplified evaluate(), detached page mid-
                # scroll, etc.) -- skip it rather than losing every
                # position's results collected so far.
                continue
    finally:
        try:
            page.evaluate(f"window.scrollTo(0, {original_scroll_y})")
        except Exception:
            pass

    return out
