# AURA Conventions

Small, easy-to-get-backwards conventions that are otherwise only
documented as scattered docstrings/comments next to the code that uses
them. Collected here once (Phase AC1, decisions.md D-059) so a future
change doesn't have to rediscover them by tracing a bug back to source —
which is exactly how the scroll-sign bug below was found (D-039/D-041).

This file documents *conventions*, not architecture. For the "why" behind
a subsystem's design, see `docs/TRD.md` and `docs/decisions.md`.

---

## 1. Scroll direction sign

`delta_y` in this codebase's own scroll calls follows a **pyautogui-style
convention, not the native DOM one**:

- **Negative `delta_y` means "scroll down."** Positive means "scroll up."
- This matches `pyautogui.scroll()`'s own sign (which `runtime/hooks/interact.py`'s
  `scroll()` passes straight through), and is why `orchestrator/autoscan.py`'s
  default `scroll_amount=-600` and `agents/vision/executor.py`'s `SCROLL`
  handler passing `-300` both mean "scroll down."
- **Native DOM scrolling uses the opposite sign**: `window.scrollBy(0, +N)`
  scrolls down. `runtime/hooks/browser.py`'s `dom_scroll(delta_y)` takes
  the pyautogui-convention `delta_y` and internally negates it
  (`native_dy = -delta_y`) before calling into the page — **any new
  DOM-scrolling code must do the same conversion**, or "scroll down" will
  silently no-op at the top of the page (clamped at `scrollY=0`) instead
  of raising an error, on every site, Lenis-driven or not.
- `dom_scroll()` also prefers a page's own `window.lenis` instance over
  plain `window.scrollBy()` when present — Lenis and similar JS-driven
  virtual-scroll libraries own scrolling via CSS transforms, so
  `window.scrollBy()` is a silent no-op on such pages regardless of sign.

**Rule of thumb:** if you're writing a new caller of `dom_scroll()`,
`interact.scroll()`, or `autoscan`'s scroll loop, pass negative to scroll
down. If you're writing new code that talks to the DOM directly
(`window.scrollBy`, `scrollTo`, etc.), the sign you want is the opposite
of what you'd pass to those.

---

## 2. Coordinate spaces

AURA has (at least) three coordinate spaces in play, and mixing them up
sends clicks to the wrong place with no exception raised. This is real:
see `runtime/hooks/browser.py`'s `get_click_point_in_page()` docstring
for the actual bug (an OCR/screen click landing on the OS taskbar) this
was written to fix.

| Space | Origin / units | Produced by | Consumed by |
|---|---|---|---|
| **OS / physical screen pixels** | top-left of the physical monitor, device pixels (not CSS pixels) | `runtime/hooks/capture.py`'s `mss` full-monitor screenshot; OCR's `(x, y)` result is an offset *into that image* | `runtime/hooks/interact.py`'s `pyautogui.moveTo/click` — expects absolute OS coordinates |
| **Browser window CSS pixels** | top-left of the *page viewport* (below browser chrome), CSS pixels, DPI-independent | `window.devicePixelRatio`, `outerWidth/innerWidth` deltas read from the page | Playwright's `page.mouse` — its coordinate space |
| **DOM / accessibility-tree targets** | no pixel coordinate at all — resolved by role/name, not position | `agents/vision/dom_locator.py`'s `locate_dom()`/`relocate_dom()` | `page.locator(...).click()` directly, bypassing pixel math entirely |

**A raw OS-pixel `(x, y)` from OCR is never directly usable as a Playwright
`page.mouse` coordinate**, and vice versa. To go from OS pixels to page
CSS pixels: use `get_click_point_in_page()`, which uses one CDP call
(`Browser.getWindowForTarget` — already in the same physical-pixel space
`mss` uses) to find the browser window's on-screen bounds, subtracts
chrome size (`outerWidth/Height - innerWidth/Height`, both CSS pixels
read from the page), and divides the remaining offset by
`devicePixelRatio` once to land in CSS pixels.

**Known simplification:** this assumes standard top-only browser chrome
(title bar / tabs / address bar). A window with left/right chrome (an
undocked DevTools panel, a browser sidebar) violates this and isn't
guaranteed correct — which is exactly why the function fails soft into
`None` rather than ever returning a guessed-wrong point silently. Prefer
the DOM path (no pixel math needed at all) whenever a live page and an
accessibility tree are available; the OS-pixel path is a fallback for
targets with no DOM (native desktop apps).

---

## 3. Confidence & similarity thresholds

Every threshold below is a *default*, overridable via `config/settings.py`
or `.env` unless noted. They live in different places because they gate
different things — collected here so a new one doesn't have to be
independently rediscovered/tuned:

| Threshold | Value | Where | Gates |
|---|---|---|---|
| `vision_confidence_threshold` | **0.75** | `config/settings.py` (TRD §5.3) | The main confidence gate in `agents/vision/executor.py`'s `execute_step`. Below this, `escalate=True` and no interaction is dispatched — the healing loop decides next steps. Applies to OCR-path *and* DOM-path locate confidence alike (Phase U dual verification, D-043). |
| `RELOCATE_MIN_RATIO` | **0.40** | `agents/vision/dom_locator.py` | The *relaxed* threshold used only by `relocate_dom()`'s self-heal pass (Scrapling-style DOM relocate, D4Vinci/Scrapling's own default) — deliberately looser than the main gate above, since this is a last-resort re-match after structure drift, not a first-pass locate. Returns the best match(es) and logs the top score even on failure, and returns *ties* rather than silently guessing when multiple candidates share the top score. |
| Capability-adapter confidence | **1.0 / 0.5 / 0.0** | each `agents/capability/*_adapter.py` | Not a single tunable — most adapters report `confidence=1.0` on pass, `0.0` on hard failure/error. A few (e.g. `db_adapter.py`, `excel_adapter.py`) report `0.5` for a "ran but degraded/partial" outcome rather than a clean binary. Treat `1.0`/`0.0` as the norm and `0.5` as adapter-specific nuance, not a generic "half confidence" convention. |
| Diagnoser heuristic confidence | **0.3 – 0.7** | `agents/planner/diagnoser.py` | Fixed per-heuristic-branch values (not derived from any measurement) reflecting how directly each parsing rule maps prose to an action; an LLM-backed parse response's own `confidence` field is used when present, defaulting to `0.6` if the model omits it. |

**Rule of thumb:** if you're adding a new locate/match path, gate it
against `vision_confidence_threshold` (import from `config.settings`,
don't hardcode `0.75`) unless it's explicitly a relaxed self-heal pass
like `relocate_dom()`, in which case document why your ratio differs from
both `0.75` and `0.40` rather than picking a third number silently.

---

## 4. Verification evidence (Phase AA convention)

Every step's trace entry (D-057) carries `verification_source`
(`ocr` / `dom` / `capability_adapter` / `none_required`) and a
`raw_evidence` blob — not just the derived pass/fail boolean. If you add
a new verification path, populate both; a trace entry with a boolean but
no `raw_evidence` is exactly the class of gap D-054–D-056 found by
reading source, not by reading the trace. `tests/test_trace_exhaustiveness.py`
(AA2) enforces every `ActionType` fills this in — extend it alongside any
new action type.

---

*Additions welcome — if you find yourself re-deriving a convention from
a docstring buried three files deep, it belongs here instead.*
