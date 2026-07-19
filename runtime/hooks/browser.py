"""
Browser navigation & session — runtime/hooks/browser.py

Phase C (Roadmap §3 / TRD §10): this module used to only shell out to the
system's default browser via the stdlib `webbrowser` module (decisions.md
D-002/D-005). It now launches and *owns* a real, persistent Playwright
Chromium browser context for the duration of a run, so that:

- `agents/vision/dom_locator.py` can resolve click/type targets against a
  live accessibility tree instead of guessing from OCR'd pixels, and
- `agents/capability/link_checker.py` can see JS-injected links on
  client-rendered pages as a direct byproduct of the same browser session.

The OCR/pixel pipeline (agents/vision/locator.py + runtime/hooks/interact.py)
is **not removed** -- it remains the fallback path for targets Playwright
genuinely cannot see (native desktop apps, no accessibility tree available),
per TRD §10 / decisions.md D-019. This module is only the *primary* path's
browser-session owner now.

Like capture.py/interact.py, Playwright is imported lazily so this module
(and anything importing it) stays importable in environments where
Playwright/its browser binaries aren't installed -- NoDisplayError is
raised (not a bare exception) in that case, same contract as before.

Phase Q (decisions.md D-038) added Playwright native trace-file capture,
parallel to (and independent of) Phase I2's video recording: when
settings.record_trace is True, context.tracing.start(screenshots=True,
snapshots=True) is called once per context and context.tracing.stop(path=...)
at close(), finalizing a self-contained .zip viewable in Playwright's own
trace viewer (see get_last_trace_path()).

Phase S (decisions.md D-040): NoDisplayError is now the one shared class
from runtime.errors, not a module-local lookalike -- see runtime/errors.py.
"""
from __future__ import annotations

import logging
import time

from config.settings import PLAYWRIGHT_BROWSER_CHOICES, settings
from runtime.errors import NoDisplayError

_logger = logging.getLogger(__name__)

__all__ = ["NoDisplayError"]  # re-exported for existing `from runtime.hooks.browser import NoDisplayError` call sites


def normalize_url(url: str) -> str:
    """Adds an https:// scheme if the caller passed a bare domain."""
    url = (url or "").strip()
    if not url:
        raise ValueError("normalize_url requires a non-empty url")
    if "://" not in url:
        url = f"https://{url}"
    return url


def _normalize_url(url: str) -> str:
    # Kept as a private alias for internal call sites in this module.
    return normalize_url(url)


class _BrowserSession:
    """
    Owns one Playwright instance + persistent Chromium browser context for
    the lifetime of a run. Deliberately module-level/singleton-ish (via the
    module functions below) rather than passed explicitly through every
    call site in orchestrator/run_engine.py and agents/vision/executor.py --
    those call sites already don't carry a "browser handle" through their
    existing signatures, and threading one through every layer is a much
    larger refactor than Phase C's scope. Tests reset this via close().
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._last_video_path: str | None = None
        self._last_trace_path: str | None = None
        self._tracing_started = False

    def get_page(self):
        if self._page is not None:
            return self._page

        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:  # pragma: no cover - exercised only without the package
            raise NoDisplayError(f"Playwright is not installed: {e}") from e

        engine_name = settings.playwright_browser
        if engine_name not in PLAYWRIGHT_BROWSER_CHOICES:
            raise NoDisplayError(
                f"settings.playwright_browser is '{engine_name}', which isn't a valid Playwright "
                f"engine. Valid choices: {', '.join(PLAYWRIGHT_BROWSER_CHOICES)}."
            )

        try:
            if self._playwright is None:
                self._playwright = sync_playwright().start()
            if self._browser is None:
                engine = getattr(self._playwright, engine_name)
                self._browser = engine.launch(headless=settings.playwright_headless)
            if self._context is None:
                context_kwargs = {}
                if settings.record_video:
                    # Phase I2 (decisions.md D-030): Playwright records the
                    # whole context's video natively -- no per-action code
                    # needed beyond passing this dir. The file is only
                    # finalized on disk once the page/context is closed
                    # (see get_last_video_path()).
                    settings.videos_dir.mkdir(parents=True, exist_ok=True)
                    context_kwargs["record_video_dir"] = str(settings.videos_dir)
                self._context = self._browser.new_context(**context_kwargs)
            if settings.record_trace and not self._tracing_started:
                # Phase Q (decisions.md D-038): Playwright's tracing API is
                # per-context, not per-page, so this starts once per
                # context -- same lifecycle granularity as record_video's
                # context_kwargs above, just via the start()/stop() API
                # instead of a constructor kwarg (tracing has no
                # context-creation-time equivalent). screenshots+snapshots
                # both on, matching the roadmap's exact spec, so the trace
                # is fully self-contained (viewable in Playwright's trace
                # viewer without needing the original page).
                try:
                    self._context.tracing.start(screenshots=True, snapshots=True)
                    self._tracing_started = True
                except Exception:
                    pass  # advisory only -- never block page creation on trace setup
            self._page = self._context.new_page()
            return self._page
        except NoDisplayError:
            raise
        except Exception as e:  # pragma: no cover - exercised only without a browser binary
            self.close()
            raise NoDisplayError(f"Could not launch a Playwright {engine_name} browser: {e}") from e

    def has_active_page(self) -> bool:
        return self._page is not None

    def get_last_video_path(self) -> str | None:
        """Path to the most recently finalized video file, if any (set by close())."""
        return self._last_video_path

    def get_last_trace_path(self) -> str | None:
        """Path to the most recently finalized Playwright trace .zip, if any (set by close())."""
        return self._last_trace_path

    def close(self) -> None:
        # Always clear first -- a stale path from a *previous* session
        # (e.g. an earlier run that had recording on) must not leak into
        # this one's answer just because the field was never overwritten.
        self._last_video_path = None
        self._last_trace_path = None

        # Capture the video path (if recording) before the page object is
        # closed and dereferenced -- Playwright only finalizes the video
        # file to disk once its owning page is closed, and page.video is
        # None afterward, so this has to happen in this exact order.
        if settings.record_video and self._page is not None:
            try:
                video = self._page.video
                if video is not None:
                    # Headed Chromium's video recorder is CDP-screencast
                    # based and attaches slightly after first paint --
                    # measurably later than headless's software path. A
                    # page that opens and closes within ~0.1s (this is a
                    # real gap seen on a real Windows/headed run, not
                    # theoretical) can beat that attach, leaving `video`
                    # non-None but with nothing ever actually recorded to
                    # back it. A small settle delay here costs nothing in
                    # the (far more common) longer-running real-run case.
                    time.sleep(0.3)
                    self._page.close()
                    self._last_video_path = str(video.path())
                    self._page = None
            except Exception:
                _logger.warning(
                    "Vision browser session: settings.record_video was on but "
                    "the video file path could not be resolved at close() -- "
                    "get_last_video_path() will report None this run.",
                    exc_info=True,
                )

        # Phase Q (decisions.md D-038): unlike video (finalized on page
        # close), tracing.stop(path=...) both finalizes *and* writes the
        # trace .zip in one call -- but it must be called on a still-open
        # context, so this has to happen before the context.close() loop
        # below tears it down.
        if self._tracing_started and self._context is not None:
            try:
                settings.traces_dir.mkdir(parents=True, exist_ok=True)
                trace_path = settings.traces_dir / f"trace_{int(time.time() * 1000)}.zip"
                self._context.tracing.stop(path=str(trace_path))
                self._last_trace_path = str(trace_path)
            except Exception:
                pass  # advisory only -- never let trace bookkeeping break teardown
            finally:
                self._tracing_started = False

        for obj, closer in (
            (self._page, "close"),
            (self._context, "close"),
            (self._browser, "close"),
            (self._playwright, "stop"),
        ):
            if obj is not None:
                try:
                    getattr(obj, closer)()
                except Exception:
                    pass
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None


_session = _BrowserSession()


def get_page(new: bool = False):
    """
    Returns the run's persistent Playwright Page, launching the browser on
    first call. Raises NoDisplayError if Playwright/its browser binaries
    aren't available -- callers (agents/vision/executor.py) treat that the
    same way as any other "no display" condition and fall back to the
    pixel/OCR path.
    """
    if new:
        _session._page = None
    return _session.get_page()


def has_active_page() -> bool:
    """True once a Playwright page has been successfully created this run."""
    return _session.has_active_page()


def get_last_video_path() -> str | None:
    """Path to the most recently finalized Playwright-recorded video, if settings.record_video was on."""
    return _session.get_last_video_path()


def get_last_trace_path() -> str | None:
    """Path to the most recently finalized Playwright trace .zip, if settings.record_trace was on."""
    return _session.get_last_trace_path()


def close() -> None:
    """Tears down the browser/context/playwright singleton. Call at run end and in test teardown."""
    _session.close()


def open_url(url: str, wait_seconds: float = 2.5, new_window: bool = False) -> str:
    """
    Navigates the run's persistent Playwright page to `url`.

    Uses `wait_until="commit"` (per docs/external_repos.md Batch 1's
    Playwright navigate.ts finding: don't block on full load, just on
    navigation commit) plus a best-effort network-idle wait so
    JS-rendered content (and JS-injected links, per link_checker.py's
    upgrade) has a chance to settle before the next screenshot/locate step.

    Returns the normalized URL that was opened, same contract as before.
    """
    normalized = _normalize_url(url)

    page = get_page(new=new_window)

    try:
        page.goto(normalized, wait_until="commit", timeout=30_000)
        try:
            page.wait_for_load_state("networkidle", timeout=max(1000, int(wait_seconds * 1000) + 4000))
        except Exception:
            # Best-effort only -- some pages (long-polling, websockets,
            # analytics beacons) never truly go network-idle. Not fatal.
            pass
    except NoDisplayError:
        raise
    except Exception as e:
        raise NoDisplayError(f"Could not navigate to {normalized!r}: {e}") from e

    # Small additional settle time mirrors the old webbrowser-based
    # behavior's `wait_seconds` contract for callers/tests that rely on it.
    #
    # Headed mode (settings.playwright_headless=False, the default -- see
    # config/settings.py's Phase W gap-closure note) needs a floor on top
    # of whatever wait_seconds a caller passes: mss (runtime/hooks/
    # capture.py) captures the *real* compositor output, and real OS-level
    # window creation + GPU compositing has genuine, variable paint
    # latency that headless never had to account for. A caller tuned for
    # headless's near-zero latency (e.g. a test passing wait_seconds=0.1)
    # can otherwise race a still-unpainted window often enough to be a
    # real, observed intermittent failure -- confirmed on a real Windows
    # run where the same test passed 6/6 once and then failed once out
    # of 15 shortly after, the signature of a timing race rather than a
    # logic bug. 0.35 was chosen empirically as comfortably above ordinary
    # compositor paint latency without meaningfully slowing headless
    # (unaffected) or already-slower (>0.35s) callers.
    settle_floor = 0.35 if not settings.playwright_headless else 0.0
    time.sleep(max(settle_floor, min(wait_seconds, 1.0)))
    return normalized
