"""
tests/test_smart_back.py

Covers runtime/hooks/interact.dom_smart_back() -- the Playwright-aware,
tab-aware "return to where we were" primitive added to fix a real gap:
the old OS-level browser_back() (Alt+Left) has no notion of a new tab,
so a target="_blank" link (very common in real nav bars/footers) was
indistinguishable from "click did nothing."

These tests use plain fake objects standing in for Playwright's
Page/BrowserContext, not a real browser -- dom_smart_back() only touches
`page.context.pages`, `page.go_back()`, `page.bring_to_front()`, and each
extra page's `.url`/`.close()`/`.wait_for_load_state()`, so faking that
surface is enough to exercise the real branching logic without needing a
live Chromium binary (which this sandbox's network egress restrictions
block -- see docs/STATUS.md's documented Chromium-download gap).
"""
from __future__ import annotations

from runtime.hooks.interact import dom_smart_back


class FakePage:
    def __init__(self, context, url: str = "https://example.com/"):
        self.context = context
        self.url = url
        self.go_back_called = False
        self.go_back_raises = False
        self.brought_to_front = False
        self.closed = False

    def go_back(self, wait_until="commit", timeout=5000):
        self.go_back_called = True
        if self.go_back_raises:
            raise RuntimeError("no back history")

    def bring_to_front(self):
        self.brought_to_front = True

    def wait_for_load_state(self, state, timeout=5000):
        pass

    def close(self):
        self.closed = True


class FakeContext:
    def __init__(self):
        self.pages: list[FakePage] = []


def _build(url_for_new_tab: str | None = None):
    ctx = FakeContext()
    original = FakePage(ctx, url="https://example.com/")
    ctx.pages.append(original)
    if url_for_new_tab is not None:
        new_tab = FakePage(ctx, url=url_for_new_tab)
        ctx.pages.append(new_tab)
    return ctx, original


def test_no_new_tab_calls_go_back():
    ctx, original = _build()
    result = dom_smart_back(original, pages_before=1)

    assert result.new_tab_opened is False
    assert result.went_back is True
    assert original.go_back_called is True


def test_go_back_failure_does_not_raise():
    ctx, original = _build()
    original.go_back_raises = True

    result = dom_smart_back(original, pages_before=1)

    assert result.went_back is False
    assert result.new_tab_opened is False


def test_new_tab_detected_closed_and_original_refocused():
    ctx, original = _build(url_for_new_tab="https://external-site.example/pricing")

    result = dom_smart_back(original, pages_before=1)

    assert result.new_tab_opened is True
    assert result.new_tab_url == "https://external-site.example/pricing"
    assert original.go_back_called is False  # never falls through to go_back() once a new tab is detected
    assert original.brought_to_front is True
    new_tab = ctx.pages[1]
    assert new_tab.closed is True


def test_multiple_new_tabs_all_closed():
    ctx, original = _build(url_for_new_tab="https://a.example/")
    ctx.pages.append(FakePage(ctx, url="https://b.example/"))

    result = dom_smart_back(original, pages_before=1)

    assert result.new_tab_opened is True
    assert all(p.closed for p in ctx.pages[1:])
