"""
Playwright-native interaction — runtime/hooks/interact.py

Phase 3 (docs/decisions.md D-076): this module used to be a thin
`pyautogui` wrapper (OS-absolute-pixel-space click/type/scroll). That
OS-level path has moved to `runtime/hooks/os_fallback.py` -- the one
deliberately-isolated fallback module, used only when no live
Playwright page exists (see that module's docstring for exactly when
and why). Every function remaining in *this* module is
Playwright-native: viewport-space, dispatched through a live `Page`/
`Locator`, no coordinate translation involved at all.

Phase S (decisions.md D-040): NoDisplayError is now the one shared class
from runtime.errors, not a module-local lookalike -- see runtime/errors.py.
"""
from __future__ import annotations

from runtime.errors import NoDisplayError

__all__ = ["NoDisplayError"]  # re-exported for existing `from runtime.hooks.interact import NoDisplayError` call sites


def dom_click(locator) -> None:
    """
    Click primitive for the Playwright DOM-locator path (Phase C / TRD §10)
    -- dispatches through a resolved Locator's own .click(), never a raw
    OS coordinate, for browser targets. Errors are re-raised as
    NoDisplayError so agents/vision/executor.py can fall back to the
    pixel/OCR path using the same contract as the rest of this module.
    """
    try:
        locator.click(timeout=5000)
    except Exception as e:  # pragma: no cover - exercised only against a real/mocked browser
        raise NoDisplayError(f"Playwright click failed: {e}") from e


def dom_fill(locator, text: str) -> None:
    """Type primitive for the Playwright DOM-locator path -- fills via the Locator, not OS keystrokes."""
    try:
        locator.click(timeout=5000)
        locator.fill(text or "", timeout=5000)
    except Exception as e:  # pragma: no cover - exercised only against a real/mocked browser
        raise NoDisplayError(f"Playwright fill failed: {e}") from e


def dom_scroll_into_view(locator) -> None:
    """Scroll primitive for the Playwright DOM-locator path -- per TRD §10, scroll_into_view + wheel, not blind OS scroll."""
    try:
        locator.scroll_into_view_if_needed(timeout=5000)
    except Exception as e:  # pragma: no cover - exercised only against a real/mocked browser
        raise NoDisplayError(f"Playwright scroll_into_view failed: {e}") from e


def dom_smart_back(page, pages_before: int, url_before: str | None = None):
    """
    Playwright-aware "return to where we were" primitive (decisions.md
    D-044) -- fixes a real, verified gap: browser_back()'s OS-level
    Alt+Left has no notion of a new tab. A meaningful fraction of nav/
    footer links use target="_blank" -- when one of those is clicked,
    Alt+Left is sent to whichever window/tab has OS focus (which may not
    even be AURA's own browser) and does nothing useful in the new tab
    either way (it has no back history). The old click-audit loop had no
    way to detect this had happened; it just recorded whatever the next
    screenshot showed, which after a new-tab click is frequently still a
    picture of the *original* page (nothing on it visibly changed), so a
    target="_blank" link that worked perfectly got reported as "no
    visible change after click" -- a false "possibly non-functional" flag
    on a working element. Independently verified against
    alibaba/page-agent's ActionResult handling (docs/external_repos.md
    Batch 6, item 4): "explicit handling for edge cases like
    target=\"_blank\" anchors (reports 'opened in a new tab' rather than
    silently doing nothing)" -- same problem, same fix shape.

    Behavior:
      1. If the click opened one or more new tabs (context.pages grew
         past pages_before), record the new tab's URL, close every tab
         after the original, and bring the original back into focus.
         AURA does not follow the new tab deeper -- the click-audit loop
         tests *this* page's elements one at a time, not every external
         site a link points to.
      2. Otherwise, only navigate back if the click actually navigated
         this same page away from where it was (url_before given and
         page.url now differs from it). A click on a non-functional
         element -- the exact case this audit exists to catch -- causes
         no navigation and no new tab; previously this branch called
         page.go_back() unconditionally regardless, which for a target
         with real prior browser history (e.g. AURA's own initial
         navigation to the page under test) silently navigated the
         *whole page* away to whatever came before it. That off-target
         navigation then made the before/after screenshot hash differ
         for a reason that had nothing to do with the click, so a click
         that did genuinely nothing got reported as a passing, visible
         state change. When url_before isn't supplied (older call sites),
         this preserves the previous unconditional go_back() behavior.

    Returns a small result object (new_tab_opened, new_tab_url, went_back)
    so callers can report "opened in a new tab" explicitly instead of
    folding it into an ambiguous state_changed=True/False verdict.
    """
    from dataclasses import dataclass

    @dataclass
    class SmartBackResult:
        new_tab_opened: bool = False
        new_tab_url: str | None = None
        went_back: bool = False

    context = page.context
    result = SmartBackResult()

    if len(context.pages) > pages_before:
        for extra in context.pages[pages_before:]:
            try:
                extra.wait_for_load_state("commit", timeout=5000)
            except Exception:
                pass  # best-effort only -- still report/close it below even if the wait timed out
            try:
                result.new_tab_url = extra.url
            except Exception:
                pass
            try:
                extra.close()
            except Exception:
                pass  # tab may already be closing -- not fatal, the original tab is what matters next
        result.new_tab_opened = True
        try:
            page.bring_to_front()
        except Exception:
            pass
        return result

    if url_before is not None:
        try:
            navigated_away = page.url != url_before
        except Exception:
            navigated_away = False  # can't tell -- treat as "nothing to undo" rather than risk an off-target go_back()
        if not navigated_away:
            return result

    try:
        page.go_back(wait_until="commit", timeout=5000)
        result.went_back = True
    except Exception:
        pass  # no back history, or navigation didn't happen -- caller's next locate() simply fails closed, same contract as the OS-level path
    return result
