"""Merged test file: test_browser_hooks.py
Consolidated from: test_browser_hook.py, test_cross_browser.py, test_real_browser_fixtures.py, test_interact_no_display.py, test_smart_back.py, test_slideshow_recorder.py
All original test functions preserved 1:1. Colliding fixture/helper names
renamed with a source-file suffix to avoid silent shadowing across sections.
"""
from __future__ import annotations
import pytest
from tests.conftest_local_server import make_server, server_url
from tests.fixtures.pages import PLAIN_TALL_PAGE as TALL_PAGE
from tests.fixtures.pages import LENIS_TALL_PAGE as LENIS_PAGE
from config.settings import settings
from tests.fixtures.pages import FAKE_500_ERROR_PAGE, SPA_CLIENT_ROUTING_PAGE
import sys
from unittest.mock import MagicMock
from runtime.hooks.os_fallback import NoDisplayError, _pyautogui
from runtime.hooks.interact import dom_smart_back
import json
from runtime.hooks.video_recorder import SlideshowRecorder


# ============================================================================
# ---- from test_browser_hook.py ----
# ============================================================================
PAGE = b"""
<html><body><h1>Hello Phase C</h1><button>Click me</button></body></html>
"""


@pytest.fixture
def server():
    srv = make_server(PAGE)
    yield srv
    srv.shutdown()


@pytest.fixture(autouse=True)
def _reset_browser_session():
    from runtime.hooks import browser

    browser.close()
    yield
    browser.close()


def test_open_url_launches_real_chromium_and_navigates(server):
    from runtime.hooks import browser

    url = browser.open_url(server_url(server), wait_seconds=0.1)
    assert url == server_url(server)
    assert browser.has_active_page() is True

    page = browser.get_page()
    assert "Hello Phase C" in page.content()


def test_has_active_page_false_before_any_navigation():
    from runtime.hooks import browser

    assert browser.has_active_page() is False


def test_close_resets_session(server):
    from runtime.hooks import browser

    browser.open_url(server_url(server), wait_seconds=0.1)
    assert browser.has_active_page() is True

    browser.close()
    assert browser.has_active_page() is False


def test_dom_scroll_returns_false_when_no_active_page():
    """No live page yet -- dom_scroll must report failure (not raise) so
    callers like orchestrator/autoscan.py know to fall back to the
    OS-level os_fallback.scroll() path."""
    from runtime.hooks import browser

    assert browser.has_active_page() is False
    assert browser.dom_scroll(-600) is False


def test_normalize_url_adds_scheme():
    from runtime.hooks import browser

    assert browser.normalize_url("example.com") == "https://example.com"
    assert browser.normalize_url("https://example.com") == "https://example.com"


def test_open_url_no_display_raises_no_display_error(monkeypatch, server):
    from runtime.hooks import browser

    def boom(*a, **k):
        raise RuntimeError("no chromium here")

    monkeypatch.setattr("playwright.sync_api.sync_playwright", boom)

    with pytest.raises(browser.NoDisplayError):
        browser.open_url(server_url(server))


# AB1 (docs/decisions.md D-057 backlog): these now live in
# tests/fixtures/pages.py as PLAIN_TALL_PAGE/LENIS_TALL_PAGE, shared with
# tests/test_real_browser_fixtures.py rather than duplicated here.


@pytest.fixture(autouse=True)
def _force_headless(monkeypatch):
    # Regression tests below need a browser that actually launches in this
    # (headless, no-display) CI environment -- every pre-existing test in
    # this file uses the project's default headed launch, which requires
    # a real display and can't run here at all (see the Xvfb error on the
    # two pre-existing tests above). Forcing headless=True only for these
    # new tests lets them exercise a *real* Chromium + real scrollBy/Lenis
    # behavior in CI, rather than mocking page.evaluate and only testing
    # that the right string was passed.
    from config.settings import settings

    monkeypatch.setattr(settings, "playwright_headless", True)


def test_dom_scroll_moves_page_downward_on_a_plain_tall_page(server=None):
    """
    Regression test for the actual reported bug: --scroll-test ran its
    full iteration budget but the page never visibly moved off the hero
    section. Root cause: dom_scroll's delta_y follows this codebase's
    pyautogui-based convention (negative = scroll down, matching
    os_fallback.scroll()), but was passed straight through to
    window.scrollBy(), which uses the OPPOSITE native sign (positive Y =
    down). Starting at scrollY=0, a "scroll down" call became
    scrollBy(0, negative), which clamps to 0 and never moves at all --
    confirmed directly against a real headless page before this fix.
    """
    from runtime.hooks import browser

    srv = make_server(TALL_PAGE)
    try:
        browser.open_url(server_url(srv), wait_seconds=0.1)
        before = browser.get_scroll_position()
        assert before is not None
        y0, remaining0 = before
        assert y0 == 0

        ok = browser.dom_scroll(-600)  # "scroll down" in this codebase's convention
        assert ok is True

        y1, remaining1 = browser.get_scroll_position()
        assert y1 > y0, "page should have moved DOWN (scrollY increased), not stayed at the top"
        assert remaining1 < remaining0
    finally:
        browser.close()
        srv.shutdown()


def test_dom_scroll_moves_page_downward_on_a_lenis_driven_page():
    """
    Regression test for the Lenis-specific half of the same bug: a
    Lenis-powered page (`<html class="lenis">`, as on the real portfolio
    site this was found on) intercepts native scrolling entirely, so even
    a correctly-signed window.scrollBy() is a silent no-op. dom_scroll()
    must detect window.lenis and drive it directly via lenis.scrollTo().
    """
    from runtime.hooks import browser

    srv = make_server(LENIS_PAGE)
    try:
        browser.open_url(server_url(srv), wait_seconds=0.1)
        before = browser.get_scroll_position()
        assert before is not None
        y0, remaining0 = before
        assert y0 == 0

        ok = browser.dom_scroll(-600)
        assert ok is True

        y1, remaining1 = browser.get_scroll_position()
        assert y1 > y0, "Lenis scroll position should have advanced, not stayed at 0"
        assert remaining1 < remaining0
    finally:
        browser.close()
        srv.shutdown()


def test_get_click_point_in_page_does_not_shift_x_by_scrollbar_width():
    """
    Regression test: get_click_point_in_page() previously added
    `outerWidth - innerWidth` (normally the vertical scrollbar's width,
    on the content area's *right* edge) into the *left*-offset
    calculation, contradicting its own documented "no left/right chrome"
    assumption. This silently shifted every OCR-dispatched click's x
    coordinate to the right by roughly a scrollbar's width (amplified by
    devicePixelRatio) -- easily enough to miss a real button while
    `_dispatch_ocr` still reported success, since no exception was ever
    raised. A real browser + CDP session isn't available in this
    environment, so this exercises the pure coordinate math via a
    directly-constructed `_BrowserSession` with mocked page/context/CDP
    internals instead.
    """
    from runtime.hooks.browser import _BrowserSession

    class FakeCdpSession:
        def send(self, method):
            assert method == "Browser.getWindowForTarget"
            return {"bounds": {"left": 100, "top": 50}}

    class FakeContext:
        def new_cdp_session(self, page):
            return FakeCdpSession()

    class FakePage:
        def evaluate(self, script):
            if "devicePixelRatio" in script:
                return 1
            if "outerWidth - window.innerWidth" in script:
                # Simulates a vertical scrollbar: outer is 17px wider
                # than inner, entirely on the content's right edge.
                return 17
            if "outerHeight - window.innerHeight" in script:
                # Simulates a title bar + toolbar, all on top.
                return 80
            raise AssertionError(f"unexpected evaluate() call: {script!r}")

    session = _BrowserSession()
    session._page = FakePage()
    session._context = FakeContext()

    from config.settings import settings

    assert settings.playwright_browser == "chromium"

    # Click at the screen point that should land at content-relative
    # (10, 20): window left=100 (no left chrome to add) + 10 -> 110,
    # window top=50 + chrome 80 (top-only) + 20 -> 150.
    result = session.get_click_point_in_page(110, 150)
    assert result == (10, 20), (
        f"expected (10, 20) with no x-shift from the scrollbar-width chrome value, got {result}"
    )

# ============================================================================
# ---- from test_cross_browser.py ----
# ============================================================================
PAGE = b"""
<html><body><h1>Hello Phase I</h1><button>Click me</button></body></html>
"""


@pytest.fixture
def server__cross_browser():
    srv = make_server(PAGE)
    yield srv
    srv.shutdown()


@pytest.fixture(autouse=True)
def _reset_browser_session_and_settings():
    from runtime.hooks import browser

    browser.close()
    original_engine = settings.playwright_browser
    original_video = settings.record_video
    original_trace = settings.record_trace
    yield
    browser.close()
    settings.playwright_browser = original_engine
    settings.record_video = original_video
    settings.record_trace = original_trace


def test_default_engine_is_chromium_and_still_works(server__cross_browser):
    """Baseline: unchanged default behavior for anyone not opting into I1."""
    from runtime.hooks import browser

    assert settings.playwright_browser == "chromium"
    url = browser.open_url(server_url(server__cross_browser), wait_seconds=0.1)
    assert url == server_url(server__cross_browser)
    page = browser.get_page()
    assert "Hello Phase I" in page.content()


def test_invalid_engine_name_raises_no_display_error_without_touching_playwright():
    """
    An invalid settings.playwright_browser value must fail with a clear,
    typed NoDisplayError -- not a raw AttributeError from
    getattr(playwright_instance, bogus_name) deep inside the try block.
    """
    from runtime.hooks import browser

    settings.playwright_browser = "not_a_real_browser"

    with pytest.raises(browser.NoDisplayError) as exc_info:
        browser.get_page()

    assert "not_a_real_browser" in str(exc_info.value)
    assert "chromium" in str(exc_info.value)  # lists valid choices


def test_firefox_engine_selected_launches_firefox_not_chromium(monkeypatch):
    """
    Verifies the actual dispatch logic (getattr(playwright, engine_name))
    picks the configured engine, using a mock Playwright instance so this
    doesn't depend on the firefox browser binary actually being
    downloaded in this sandbox (it may not be -- same class of
    environment-dependent gap as Chromium's own download restriction
    noted throughout docs/STATUS.md).
    """
    from unittest.mock import MagicMock
    from runtime.hooks import browser

    settings.playwright_browser = "firefox"

    fake_page = MagicMock()
    fake_context = MagicMock()
    fake_context.new_page.return_value = fake_page
    fake_browser = MagicMock()
    fake_browser.new_context.return_value = fake_context
    fake_firefox_engine = MagicMock()
    fake_firefox_engine.launch.return_value = fake_browser
    fake_chromium_engine = MagicMock()

    fake_playwright_instance = MagicMock()
    fake_playwright_instance.firefox = fake_firefox_engine
    fake_playwright_instance.chromium = fake_chromium_engine

    fake_sync_playwright_cm = MagicMock()
    fake_sync_playwright_cm.start.return_value = fake_playwright_instance

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright", lambda: fake_sync_playwright_cm
    )

    page = browser.get_page()

    assert page is fake_page
    # headless defaults to settings.playwright_headless (False), not a
    # hardcoded True -- see config/settings.py's Phase W gap-closure note
    # on why OCR needs the page actually visible on screen.
    fake_firefox_engine.launch.assert_called_once_with(
        headless=settings.playwright_headless, args=["--start-maximized"]
    )
    fake_chromium_engine.launch.assert_not_called()


def test_real_firefox_binary_not_installed_fails_gracefully_not_a_crash(server__cross_browser, monkeypatch):
    """
    Selecting an engine whose launch fails for any reason (binary not
    installed, launch error, etc.) must fail as a clean NoDisplayError,
    not an unhandled exception -- confirms the existing
    except-wrap-into-NoDisplayError behavior still covers the
    engine-selection code path.

    Deliberately does NOT depend on whether Firefox's binary actually
    happens to be installed on the machine running this suite. The
    original version of this test asserted real launch failure for
    firefox specifically, on the assumption that only Chromium is ever
    installed -- true in a fresh sandbox, but not a safe assumption for a
    developer machine where `playwright install` (with no engine
    argument, or run more than once over time) may have pulled in
    Firefox too, silently invalidating the test's premise without
    touching the code under test at all (see: this exact failure showing
    up on a real Windows run once Firefox became available there).
    Monkeypatching the launch call itself tests the actual contract --
    "launch failure of any kind becomes NoDisplayError" -- independent of
    ambient machine state.
    """
    from runtime.hooks import browser

    def _boom(*args, **kwargs):
        raise RuntimeError("Executable doesn't exist -- simulated missing browser binary")

    session = browser._session
    monkeypatch.setattr(session, "_playwright", None)
    monkeypatch.setattr(session, "_browser", None)
    monkeypatch.setattr(session, "_context", None)
    monkeypatch.setattr(session, "_page", None)

    import playwright.sync_api as pw_api

    class _FakeEngine:
        launch = staticmethod(_boom)

    class _FakePlaywrightContext:
        chromium = _FakeEngine()
        firefox = _FakeEngine()
        webkit = _FakeEngine()

    class _FakeSyncPlaywright:
        def start(self):
            return _FakePlaywrightContext()

    monkeypatch.setattr(pw_api, "sync_playwright", lambda: _FakeSyncPlaywright())
    settings.playwright_browser = "firefox"

    with pytest.raises(browser.NoDisplayError):
        browser.open_url(server_url(server__cross_browser), wait_seconds=0.1)


def test_record_video_produces_a_real_video_file_on_close(server__cross_browser):
    """
    Phase I2: with settings.record_video on, a real Playwright video file
    must exist on disk after browser.close() -- finalized only once the
    page is closed, which is exactly what close() now does before tearing
    the rest of the session down.
    """
    import os
    from runtime.hooks import browser

    settings.record_video = True
    browser.open_url(server_url(server__cross_browser), wait_seconds=0.1)
    assert browser.has_active_page() is True

    browser.close()

    video_path = browser.get_last_video_path()
    assert video_path is not None
    assert os.path.exists(video_path)
    assert os.path.getsize(video_path) > 0


def test_record_video_off_by_default_produces_no_video_path(server__cross_browser):
    from runtime.hooks import browser

    assert settings.record_video is False
    browser.open_url(server_url(server__cross_browser), wait_seconds=0.1)
    browser.close()

    assert browser.get_last_video_path() is None


def test_record_trace_produces_a_real_trace_file_on_close(server__cross_browser):
    """
    Phase Q (decisions.md D-038): with settings.record_trace on, a real
    Playwright trace .zip must exist on disk after browser.close() --
    unlike video, tracing.stop(path=...) both finalizes and writes the
    file in one call, but it has to run before the context itself is
    torn down, which is exactly what close() now does first.
    """
    import os
    import zipfile
    from runtime.hooks import browser

    settings.record_trace = True
    browser.open_url(server_url(server__cross_browser), wait_seconds=0.1)
    assert browser.has_active_page() is True

    browser.close()

    trace_path = browser.get_last_trace_path()
    assert trace_path is not None
    assert os.path.exists(trace_path)
    assert os.path.getsize(trace_path) > 0
    assert zipfile.is_zipfile(trace_path)


def test_record_trace_off_by_default_produces_no_trace_path(server__cross_browser):
    from runtime.hooks import browser

    assert settings.record_trace is False
    browser.open_url(server_url(server__cross_browser), wait_seconds=0.1)
    browser.close()

    assert browser.get_last_trace_path() is None


def test_record_video_and_record_trace_are_independent(server__cross_browser):
    """Toggling one must not implicitly toggle or suppress the other."""
    from runtime.hooks import browser

    settings.record_video = False
    settings.record_trace = True
    browser.open_url(server_url(server__cross_browser), wait_seconds=0.1)
    browser.close()

    assert browser.get_last_video_path() is None
    assert browser.get_last_trace_path() is not None

# ============================================================================
# ---- from test_real_browser_fixtures.py ----
# ============================================================================
@pytest.fixture(autouse=True)
def _force_headless__real_browser_fixtures(monkeypatch):
    # Same rationale as tests/test_browser_hook.py's fixture of the same
    # name: lets these tests launch a real Chromium in a headless/no-
    # display CI environment instead of requiring a real display.
    from config.settings import settings

    monkeypatch.setattr(settings, "playwright_headless", True)


def test_link_check_finds_client_injected_links_via_live_page_html():
    """
    AB1 regression test for D-055's real bug, now exercised against an
    actual browser + actual server instead of mocks: a plain httpx GET
    against a client-rendered SPA sees no <a href> at all (the page's
    real HTML is just a bare mount point) -- but once a real browser has
    hydrated the page, LinkCheckAdapter.run() with live_page_html must
    find the real, JS-injected links rather than reporting 0.
    """
    from agents.capability.link_checker import LinkCheckAdapter
    from orchestrator.schemas import CapabilityCheckInput, CapabilityType
    from runtime.hooks import browser

    srv = make_server(SPA_CLIENT_ROUTING_PAGE)
    try:
        url = server_url(srv)
        browser.open_url(url, wait_seconds=0.3)  # let the setTimeout hydration actually run
        live_html = browser.get_page().content()
        browser.close()

        adapter = LinkCheckAdapter()
        result = adapter.run(
            CapabilityCheckInput(
                capability=CapabilityType.LINK_CHECK,
                target=url,
                params={"scope": "all", "live_page_html": live_html},
            )
        )

        assert result.evidence["used_live_page"] is True
        assert result.evidence["rendered_via_playwright"] is False
        # The pre-hydration HTML the plain httpx GET would see has zero
        # <a href> tags -- only the hydrated DOM (captured via live_page_html)
        # has the real /work, /about, /contact, /services/ai, github links.
        assert result.evidence["checked"] >= 4
    finally:
        srv.shutdown()


def test_link_check_falls_back_to_its_own_playwright_render_when_no_live_page_given():
    """
    Companion test clarifying the actual contract: when there's no
    already-open browser session to reuse (live_page_html not supplied),
    LinkCheckAdapter's own standalone Playwright render is exactly what's
    supposed to run -- and it works fine in that isolated case, since
    D-055's bug was specifically about a SECOND sync_playwright()
    instance conflicting with an already-active one, not about the
    standalone fallback being broken in general.
    """
    from agents.capability.link_checker import LinkCheckAdapter
    from orchestrator.schemas import CapabilityCheckInput, CapabilityType

    srv = make_server(SPA_CLIENT_ROUTING_PAGE)
    try:
        url = server_url(srv)
        adapter = LinkCheckAdapter()
        result = adapter.run(
            CapabilityCheckInput(
                capability=CapabilityType.LINK_CHECK,
                target=url,
                params={"scope": "all"},  # no live_page_html supplied
            )
        )
        assert result.evidence["used_live_page"] is False
        assert result.evidence["rendered_via_playwright"] is True
        assert result.evidence["checked"] >= 4
    finally:
        srv.shutdown()


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Tracked known limitation (docs/decisions.md D-056): the shape-based "
        "structural fallback in check_assertion() can tell 'nothing rendered' "
        "from 'something rendered', but not yet 'the right thing rendered' "
        "from 'an error rendered'. This test is expected to fail (xfail) "
        "until that's fixed -- if it ever unexpectedly passes, pytest will "
        "flag it (strict=True) as a signal to remove this marker and treat "
        "the limitation as closed."
    ),
)
def test_known_limitation_error_page_is_not_yet_detected_as_a_failed_assertion():
    """
    Real end-to-end reproduction of D-056's documented gap: a genuine
    500-error page, OCR'd for real (no mocks), against a sentence-shaped
    assertion describing successful load. Today this incorrectly passes,
    because the fallback only checks "is there readable text at all" --
    an error page has plenty. Kept as a real, running test (not just
    prose in decisions.md) specifically so a future fix is caught
    automatically instead of silently landing unnoticed.
    """
    from agents.vision.assertions import check_assertion
    from runtime.hooks import browser

    srv = make_server(FAKE_500_ERROR_PAGE)
    try:
        browser.open_url(server_url(srv), wait_seconds=0.1)
        from runtime.hooks.capture import capture_screenshot

        screenshot_path = capture_screenshot("aa1_known_limitation_run", 1)
        passed = check_assertion(
            screenshot_path,
            "The dashboard page has fully loaded and is displaying correctly.",
        )
        # Documents today's actual (wrong) behavior: this assertion
        # currently passes on an error page. The assert below is
        # deliberately the "bad" outcome -- xfail(strict=True) above is
        # what turns "this test's assertion holds" into a visible,
        # tracked gap rather than a silent false positive.
        assert passed is False
    finally:
        browser.close()
        srv.shutdown()

# ============================================================================
# ---- from test_interact_no_display.py ----
# ============================================================================
def test_pyautogui_systemexit_from_mouseinfo_becomes_no_display_error(monkeypatch):
    """
    Simulates mouseinfo's sys.exit(...) call by making the `pyautogui`
    import itself raise SystemExit, and asserts it's converted into
    NoDisplayError instead of propagating and killing the process.
    """
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyautogui":
            sys.exit("NOTE: You must install tkinter on Linux to use MouseInfo.")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(NoDisplayError):
        _pyautogui()


def test_pyautogui_generic_import_error_still_becomes_no_display_error(monkeypatch):
    """The pre-existing ImportError/other-Exception path must keep working."""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pyautogui":
            raise ImportError("no module named pyautogui")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(NoDisplayError):
        _pyautogui()


def test_pyautogui_success_path_unaffected(monkeypatch):
    """When pyautogui imports fine, _pyautogui() should return it, FAILSAFE set."""
    fake_pyautogui = MagicMock()
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pyautogui)

    result = _pyautogui()

    assert result is fake_pyautogui
    assert fake_pyautogui.FAILSAFE is True

# ============================================================================
# ---- from test_smart_back.py ----
# ============================================================================
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

# ============================================================================
# ---- from test_slideshow_recorder.py ----
# ============================================================================
def test_finalize_returns_none_with_no_frames(tmp_path, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)
    recorder = SlideshowRecorder()
    assert recorder.finalize("run123") is None


def test_add_frame_and_finalize_writes_honest_manifest(tmp_path, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "project_root", tmp_path)
    recorder = SlideshowRecorder()
    recorder.add_frame("/some/path/step_1.png", 1)
    recorder.add_frame("/some/path/step_2.png", 2)

    assert recorder.frame_count == 2

    manifest_path = recorder.finalize("run123")
    assert manifest_path is not None

    data = json.loads(open(manifest_path, encoding="utf-8").read())
    assert data["kind"] == "slideshow"
    assert "not continuous video" in data["note"]
    assert data["frame_count"] == 2
    assert data["frames"][0]["step_id"] == 1
    assert data["frames"][0]["screenshot_path"] == "/some/path/step_1.png"
    assert data["frames"][1]["step_id"] == 2
