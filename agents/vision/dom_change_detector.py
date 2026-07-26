"""
agents/vision/dom_change_detector.py

Phase 4 (docs/decisions.md D-077, docs/AURA_REARCHITECTURE_PLAN.md).

Replaces the pixel-hash-diff gate (`agents/vision/assertions.py`'s
`file_hash` comparison) as the primary "did anything actually happen"
check wherever a live Playwright page exists -- a real DOM mutation
check, not an inference from whether two screenshots happen to differ
byte-for-byte. This is the direct structural fix for the bug class
D-067 found: a pixel-hash-diff can't distinguish "the contact form
appeared" from "an ad rotated" or "an unrelated `go_back()` silently
navigated somewhere else" -- a real mutation observer only counts as
"changed" what actually mutated in the DOM (or a real URL change),
filtered against a small denylist of known-noisy nodes (ads, analytics
beacons, live regions) so those don't count as a genuine change either.

Usage (mirrors the arm-before/read-after shape every click-audit call
site already uses for baseline/after screenshots):

    from agents.vision.dom_change_detector import arm, read_result

    arm(page, ignore_selectors)
    ... dispatch the click ...
    result = read_result(page, settle_wait_seconds=0.5)
    if result.armed:
        state_changed = result.mutated or result.url_changed

**Fallback, same single condition every other Phase-2/3 fallback in the
codebase uses:** when there's no live page at all (`dom_page is None`),
this module simply isn't reachable -- callers keep using
`agents/vision/assertions.py`'s existing pixel-hash-diff exactly as
before. `arm()`/`read_result()` also both degrade safely (return
`armed=False`, never raise) if `page.evaluate()` itself fails for any
reason (page closed mid-audit, navigation raced the observer install) --
callers treat that exactly like "no live page," falling back to
hash-diff for that one check rather than crashing the whole run.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

# Installs a MutationObserver on document.body, discarding any
# mutation whose target lives inside one of the (JS-injected)
# ignore_selectors -- filtered at record time, not after the fact, so
# a page with a constantly-ticking clock or ad iframe doesn't need its
# noise swept out of a result set after the fact.
_ARM_JS = """
(ignoreSelectors) => {
  window.__aura_mutations = [];
  window.__aura_url_before = location.href;
  if (window.__aura_observer) { try { window.__aura_observer.disconnect(); } catch (e) {} }
  const isIgnored = (node) => {
    if (!node || !node.closest) return false;
    for (const sel of ignoreSelectors) {
      try { if (node.closest(sel)) return true; } catch (e) { /* invalid selector -- skip it, don't fail the whole check */ }
    }
    return false;
  };
  window.__aura_observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      const t = m.target && m.target.nodeType === 1 ? m.target : (m.target && m.target.parentElement);
      if (isIgnored(t)) continue;
      window.__aura_mutations.push({
        type: m.type,
        tag: (t && t.tagName) || null,
        attr: m.attributeName || null,
      });
    }
  });
  window.__aura_observer.observe(document.body, { childList: true, attributes: true, subtree: true, characterData: true });
  return true;
}
"""

_READ_JS = """
() => {
  const raw = window.__aura_mutations || [];
  const urlAfter = location.href;
  const urlBefore = window.__aura_url_before;
  if (window.__aura_observer) { try { window.__aura_observer.disconnect(); } catch (e) {} }
  return { count: raw.length, urlBefore, urlAfter, sample: raw.slice(0, 8) };
}
"""


@dataclass
class MutationResult:
    armed: bool
    mutated: bool = False
    mutation_count: int = 0
    url_changed: bool = False
    url_before: str | None = None
    url_after: str | None = None
    sample_mutations: list[dict] = field(default_factory=list)
    error: str | None = None


def arm(page, ignore_selectors: list[str] | None = None) -> bool:
    """
    Installs the observer. Returns True if arming succeeded, False if
    it didn't (page not ready, evaluate() failed) -- callers should
    treat a False return the same as "no live page" for this one check
    and fall back to hash-diff, not raise.
    """
    try:
        page.evaluate(_ARM_JS, ignore_selectors or [])
        return True
    except Exception as e:
        import logging

        logging.getLogger(__name__).debug(
            "dom_change_detector.arm: page.evaluate failed (%s) -- callers fall back to hash-diff for this check.", e
        )
        return False


def read_result(page, settle_wait_seconds: float = 0.0) -> MutationResult:
    """
    Reads back the buffer armed by arm(). `settle_wait_seconds` is a
    short wait before reading (default: none -- most call sites already
    have their own settle wait, e.g. the screenshot capture itself, so
    this only adds one when the caller explicitly wants an additional
    one here rather than relying on that).
    """
    if settle_wait_seconds:
        time.sleep(settle_wait_seconds)
    try:
        raw = page.evaluate(_READ_JS)
    except Exception as e:
        return MutationResult(armed=False, error=str(e))
    return MutationResult(
        armed=True,
        mutated=raw["count"] > 0,
        mutation_count=raw["count"],
        url_changed=raw["urlAfter"] != raw["urlBefore"],
        url_before=raw["urlBefore"],
        url_after=raw["urlAfter"],
        sample_mutations=raw["sample"],
    )
