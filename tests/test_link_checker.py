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
