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
    except Exception:
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
    """
    from agents.vision.ui_audit import UIElement, _NAV_BAND_END, _FOOTER_BAND_START

    elements = extract_interactive_elements(page)
    out = []
    for el in elements:
        frac = (el.cy / page_height) if page_height else 0.0
        if frac < _NAV_BAND_END:
            band = "nav"
        elif frac >= _FOOTER_BAND_START:
            band = "footer"
        else:
            band = "body"
        out.append(UIElement(text=el.name, cx=el.cx, cy=el.cy, band=band, looks_interactive=True))
    return out
