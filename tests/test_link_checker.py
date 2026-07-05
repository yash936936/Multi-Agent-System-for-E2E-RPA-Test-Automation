from __future__ import annotations

import httpx

from agents.capability.link_checker import LinkCheckAdapter
from orchestrator.schemas import CapabilityCheckInput, CapabilityType

PAGE_HTML = """
<html>
<body>
  <nav><a href="/about">About</a> <a href="/pricing">Pricing</a></nav>
  <main><a href="/blog">Blog</a></main>
  <footer>
    <a href="/services/design">Design</a>
    <a href="/services/dead-link">Broken Service</a>
    <a href="mailto:hello@example.com">Email us</a>
    <a href="#top">Back to top</a>
  </footer>
</body>
</html>
"""


def _patch_client(monkeypatch, handler):
    real_client_cls = httpx.Client
    transport = httpx.MockTransport(handler)

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return real_client_cls(*args, **kwargs)

    monkeypatch.setattr("agents.capability.link_checker.httpx.Client", fake_client)


def _make_client_factory(monkeypatch):
    """Patches httpx.Client construction inside link_checker to use a MockTransport."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.rstrip("/") == "https://example.com":
            return httpx.Response(200, text=PAGE_HTML)
        if url.endswith("/services/dead-link"):
            return httpx.Response(404, text="Not Found")
        if url.endswith(("/about", "/pricing", "/blog", "/services/design")):
            return httpx.Response(200, text="ok")
        return httpx.Response(404, text="Not Found")

    _patch_client(monkeypatch, handler)


def test_footer_scope_flags_the_broken_service_link(monkeypatch):
    _make_client_factory(monkeypatch)
    adapter = LinkCheckAdapter()

    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.LINK_CHECK,
            target="",
            params={"url": "https://example.com/", "scope": "footer"},
        )
    )

    assert result.passed is False
    assert result.evidence["checked"] == 2  # /services/design + /services/dead-link (mailto/# excluded)
    assert result.evidence["broken_count"] == 1
    assert result.evidence["broken_links"][0]["url"].endswith("/services/dead-link")
    assert result.evidence["broken_links"][0]["status_code"] == 404


def test_footer_scope_passes_when_all_links_resolve(monkeypatch):
    html_all_good = PAGE_HTML.replace(
        '<a href="/services/dead-link">Broken Service</a>', '<a href="/services/consulting">Consulting</a>'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.rstrip("/") == "https://example.com":
            return httpx.Response(200, text=html_all_good)
        return httpx.Response(200, text="ok")

    _patch_client(monkeypatch, handler)

    adapter = LinkCheckAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.LINK_CHECK,
            target="",
            params={"url": "https://example.com/", "scope": "footer"},
        )
    )

    assert result.passed is True
    assert result.evidence["broken_count"] == 0


def test_nonexistent_footer_reports_no_links_found_not_a_silent_pass(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body><a href='/about'>About</a></body></html>")

    _patch_client(monkeypatch, handler)

    adapter = LinkCheckAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.LINK_CHECK,
            target="",
            params={"url": "https://example.com/", "scope": "footer"},
        )
    )

    # No <footer> on the page at all -- this must be reported as a
    # findable, explained failure, not silently treated as "nothing to
    # check, so it passes."
    assert result.passed is False
    assert result.evidence["checked"] == 0


def test_missing_url_fails_with_clear_error():
    adapter = LinkCheckAdapter()
    result = adapter.run(
        CapabilityCheckInput(capability=CapabilityType.LINK_CHECK, target="", params={})
    )
    assert result.passed is False
    assert "url" in result.evidence["error"].lower()


def test_default_scope_is_all_not_footer(monkeypatch):
    """
    Regression test: run_exploration()/explore_cmd previously hardcoded
    scope="footer" at the call site, so nav/body links (e.g. the "About"
    link in <nav>, outside any <footer>) were silently never checked.
    Omitting `scope` entirely must check every link on the page.
    """
    _make_client_factory(monkeypatch)

    adapter = LinkCheckAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.LINK_CHECK,
            target="",
            params={"url": "https://example.com/"},  # no scope given
        )
    )

    # PAGE_HTML has 4 real navigable links total (nav: /about, /pricing;
    # main: /blog; footer: /services/design) plus one broken footer link,
    # plus mailto:/# which are correctly excluded -- 5 checkable links.
    assert result.evidence["scope"] == "all"
    assert result.evidence["checked"] == 5
    assert result.passed is False  # /services/dead-link is still broken
    assert result.evidence["broken_count"] == 1


def test_redirect_chain_is_reported_for_redirected_links(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.rstrip("/") == "https://example.com":
            return httpx.Response(200, text='<html><body><a href="/old-page">Old</a></body></html>')
        if url.endswith("/old-page"):
            return httpx.Response(301, headers={"location": "/new-page"})
        if url.endswith("/new-page"):
            return httpx.Response(200, text="ok")
        return httpx.Response(404)

    _patch_client(monkeypatch, handler)

    adapter = LinkCheckAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.LINK_CHECK,
            target="",
            params={"url": "https://example.com/", "scope": "all"},
        )
    )

    assert result.passed is True  # redirect to a working page is still "ok"
    assert result.evidence["redirected_count"] == 1
    redirected = result.evidence["redirected_links"][0]
    assert redirected["redirected"] is True
    assert redirected["final_url"].endswith("/new-page")
    assert redirected["redirect_chain"][0]["status_code"] == 301


def test_client_rendered_page_gets_an_honest_no_links_message(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        # Typical Next.js server-rendered shell before JS hydrates --
        # no <a href> present anywhere in the raw HTML AURA fetches.
        return httpx.Response(200, text='<html><body><div id="__next"></div></body></html>')

    _patch_client(monkeypatch, handler)

    adapter = LinkCheckAdapter()
    result = adapter.run(
        CapabilityCheckInput(
            capability=CapabilityType.LINK_CHECK,
            target="",
            params={"url": "https://example.com/", "scope": "all"},
        )
    )

    assert result.passed is False
    assert result.evidence["client_rendered_suspected"] is True
    assert "client-rendered" in result.evidence["message"].lower()
