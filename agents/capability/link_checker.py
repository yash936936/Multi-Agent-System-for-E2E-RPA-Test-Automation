"""
Link checker — agents/capability/link_checker.py

Real, HTTP-level broken-link detection. This did not exist anywhere in
AURA before: the vision-only pipeline (agents/vision/*) has no DOM access
by design (decisions.md D-002/D-005), so it could click things and watch
pixels change, but it could never answer "does this link's target actually
resolve" -- a click-and-diff check on a broken link that still renders SOME
page (e.g. a custom 404 template) looks identical to a working navigation,
so it silently passed regardless of whether the destination was real.

This adapter closes that gap the honest way: it makes a real HTTP request
to fetch the page HTML (no browser/JS rendering -- same "no DOM automation"
posture as the rest of AURA, just enough network I/O to read anchor tags),
extracts every <a href> target, optionally scoped to content inside a
<footer>...</footer> region, and issues a real HEAD (falling back to GET
if HEAD is rejected) request against each one. Anything that doesn't come
back 2xx/3xx is reported as broken with its actual status code or error.

Registered under CapabilityType.LINK_CHECK and dispatched the same way as
every other capability (api/db/email/etc.) via a CAPABILITY_CHECK TestStep
-- see orchestrator/capability_adapter.py's default_registry().
"""
from __future__ import annotations

import logging
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urljoin

import httpx

from orchestrator.schemas import CapabilityCheckInput, CapabilityCheckResult, CapabilityType

# Hrefs that aren't real navigable links and shouldn't be flagged as
# "broken" just because they don't resolve over HTTP.
_SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "#")


class _AnchorExtractor(HTMLParser):
    """
    Stdlib-only HTML parsing (no new dependency like BeautifulSoup) that
    records every <a href="..."> found, tagging each with whether it falls
    inside a <footer> element so scope="footer" can filter accurately even
    across malformed/unclosed tags in real-world markup.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict] = []
        self._footer_depth = 0
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        self._depth += 1
        if tag == "footer":
            self._footer_depth += 1
        if tag == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href")
            if href:
                self.anchors.append(
                    {
                        "href": href.strip(),
                        "text": "",
                        "in_footer": self._footer_depth > 0,
                        "_idx": len(self.anchors),
                    }
                )

    def handle_endtag(self, tag):
        if tag == "footer" and self._footer_depth > 0:
            self._footer_depth -= 1
        self._depth = max(0, self._depth - 1)

    def handle_data(self, data):
        if self.anchors and data.strip():
            self.anchors[-1]["text"] = (self.anchors[-1]["text"] + " " + data.strip()).strip()[:80]


def _extract_links(html: str, base_url: str, scope: str) -> list[dict]:
    parser = _AnchorExtractor()
    parser.feed(html)

    links = []
    seen = set()
    for a in parser.anchors:
        href = a["href"]
        if scope == "footer" and not a["in_footer"]:
            continue
        if any(href.lower().startswith(s) for s in _SKIP_SCHEMES):
            continue
        absolute = urljoin(base_url, href)
        if not absolute.startswith(("http://", "https://")):
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append({"href": href, "resolved_url": absolute, "text": a["text"]})
    return links


# Telltale root-element markers left behind by client-side frameworks even
# after JS has rendered content into them -- present in the raw (JS-free)
# HTML AURA actually fetches, which is exactly the case where "no <a href>
# found" doesn't mean "no links," it means "this page's links don't exist
# until a browser runs JavaScript that AURA's plain HTTP fetch never runs."
_SPA_ROOT_MARKERS = ('id="root"', "id='root'", 'id="__next"', "id='__next'", "id=\"app\"", "id='app'", "ng-version")


def _looks_client_rendered(html: str) -> bool:
    lowered = html.lower()
    return any(marker.lower() in lowered for marker in _SPA_ROOT_MARKERS)


def _check_one(client: httpx.Client, url: str) -> dict:
    try:
        resp = client.head(url, follow_redirects=True, timeout=10.0)
        # Some servers (real-world, not hypothetical -- plenty of CDNs and
        # frameworks) reject HEAD with 405 even though GET works fine.
        # Retry with GET before concluding the link is actually broken.
        if resp.status_code == 405:
            resp = client.get(url, follow_redirects=True, timeout=10.0)
        # httpx populates resp.history with every intermediate redirect
        # response when follow_redirects=True -- surface that chain
        # explicitly rather than silently landing on the final URL, so a
        # link that "works" only because it got 301'd somewhere else
        # entirely is visible, not indistinguishable from a direct hit.
        redirect_chain = [
            {"status_code": r.status_code, "from_url": str(r.url), "to_url": r.headers.get("location", "")}
            for r in resp.history
        ]
        return {
            "url": url,
            "status_code": resp.status_code,
            "ok": 200 <= resp.status_code < 400,
            "error": None,
            "redirected": bool(redirect_chain),
            "final_url": str(resp.url) if redirect_chain else None,
            "redirect_chain": redirect_chain,
        }
    except httpx.RequestError as e:
        return {"url": url, "status_code": None, "ok": False, "error": str(e), "redirected": False, "final_url": None, "redirect_chain": []}


def _render_with_playwright(url: str, timeout_ms: int = 15_000) -> Optional[str]:
    """
    Headless Playwright page load used only as a fallback when the plain
    HTTP fetch above finds no links and the page looks client-rendered
    (per TRD §10 point 4 / docs/external_repos.md Batch 1 & 2: wait past
    navigation commit, then a best-effort network-idle wait, before
    reading back the fully-rendered HTML). Returns None (never raises) if
    Playwright/its browser binaries aren't available or the render fails
    for any reason -- callers treat that exactly like "couldn't render",
    falling back to the existing honest client-rendered message rather
    than crashing a capability check over an optional enhancement.
    """
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        logging.getLogger(__name__).debug("_render_with_playwright: Playwright not importable (%s)", e)
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="commit", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:
                    pass  # best-effort only, same posture as runtime/hooks/browser.py
                html = page.content()
                return html
            finally:
                browser.close()
    except Exception as e:
        # AA3 (docs/decisions.md D-057): this exact silent swallow (no
        # logging at all) is what let D-055's nested-sync-Playwright bug
        # go undetected for so long -- when a run's own browser session
        # was already active, this always failed with "It looks like you
        # are using Playwright Sync API inside the asyncio loop", and
        # nothing surfaced that anywhere. Now logged so a repeated
        # failure here is visible instead of just quietly degrading to
        # "0 links found."
        logging.getLogger(__name__).warning("_render_with_playwright: render failed (%s)", e)
        return None


class LinkCheckAdapter:
    """
    params:
        url: page to scan (falls back to `target` if omitted)
        scope: "footer" | "nav" | "all" (default "all")
        max_links: safety cap on how many links get live-checked (default 40)
        live_page_html: optional -- already-hydrated HTML from a live
            browser session (e.g. runtime.hooks.browser.get_page().content())
            that the caller already has open. When given, this is used
            directly to find JS-injected links on client-rendered pages
            instead of trying to launch a second Playwright instance.
            Callers such as `aura execute --ui-audit` and `aura explore`
            keep their own Playwright session alive for the whole run
            (to drive OCR screenshots), and Playwright's sync API forbids
            starting a second sync_playwright() instance in the same
            thread -- _render_with_playwright() below fails silently in
            that situation every time. Passing the live page's HTML
            avoids that conflict entirely, and is strictly better anyway
            since it costs zero extra page loads.
    expected: unused -- pass/fail is purely "did every in-scope link resolve"
    """

    capability_type: CapabilityType = CapabilityType.LINK_CHECK

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        url = (payload.params.get("url") or payload.target or "").strip()
        scope = (payload.params.get("scope") or "all").lower()
        max_links = int(payload.params.get("max_links", 40))
        live_page_html = payload.params.get("live_page_html")

        if not url:
            return self._fail("Missing 'url' (or 'target') to scan for links")

        try:
            with httpx.Client(timeout=15.0, headers={"User-Agent": "AURA-LinkChecker/1.0"}) as client:
                page_resp = client.get(url, follow_redirects=True)
                page_resp.raise_for_status()
                links = _extract_links(page_resp.text, str(page_resp.url), scope)

                if not links:
                    # Scope produced nothing to check -- this is itself a
                    # meaningful, reportable finding (e.g. "footer" scope
                    # but the page has no <footer> element at all), not a
                    # silent pass.
                    client_rendered = _looks_client_rendered(page_resp.text)
                    rendered_html = None
                    used_live_page = False
                    if client_rendered:
                        if live_page_html:
                            # Reuse the caller's already-hydrated page --
                            # no second Playwright instance, no conflict.
                            rendered_html = live_page_html
                            used_live_page = True
                        else:
                            # TRD §10 point 4: this is exactly the gap a
                            # headless Playwright render closes -- try it
                            # before concluding there's really nothing here.
                            rendered_html = _render_with_playwright(str(page_resp.url))
                        if rendered_html:
                            links = _extract_links(rendered_html, str(page_resp.url), scope)

                    if links:
                        results = [_check_one(client, link["resolved_url"]) for link in links[:max_links]]
                        return self._build_result(url, scope, results, rendered_via_playwright=(not used_live_page), used_live_page=used_live_page)

                    message = f"No navigable <a href> links found in scope='{scope}' on this page."
                    if client_rendered:
                        if rendered_html is None:
                            message += (
                                " This page looks client-rendered (React/Next.js/Angular-style root element detected) "
                                "-- if its links/footer are injected by JavaScript after load, a plain HTTP fetch "
                                "genuinely can't see them. AURA attempted a headless Playwright render to check for "
                                "JS-injected links, but Playwright/its browser binaries weren't available or the "
                                "render failed, so this is a real coverage limit for this run, not a false pass."
                            )
                        elif used_live_page:
                            message += (
                                " This page looks client-rendered, and AURA used the already-open live browser "
                                "page's rendered HTML to check for JS-injected links, but it still had no "
                                f"navigable links in scope='{scope}'."
                            )
                        else:
                            message += (
                                " This page looks client-rendered, and AURA rendered it with a headless Playwright "
                                "browser to check for JS-injected links, but the rendered page still had no "
                                f"navigable links in scope='{scope}'."
                            )
                    return CapabilityCheckResult(
                        capability=self.capability_type,
                        passed=False,
                        confidence=1.0,
                        evidence={
                            "url": url,
                            "scope": scope,
                            "checked": 0,
                            "broken_count": 0,
                            "client_rendered_suspected": client_rendered,
                            "rendered_via_playwright": rendered_html is not None and not used_live_page,
                            "used_live_page": used_live_page,
                            "message": message,
                        },
                        escalate=False,
                    )

                results = [_check_one(client, link["resolved_url"]) for link in links[:max_links]]

        except httpx.HTTPStatusError as e:
            return self._fail(f"Could not load {url}: HTTP {e.response.status_code}")
        except httpx.RequestError as e:
            return self._fail(f"Could not reach {url}: {e}")

        return self._build_result(url, scope, results)

    def _build_result(self, url: str, scope: str, results: list[dict], rendered_via_playwright: bool = False, used_live_page: bool = False) -> CapabilityCheckResult:
        broken = [r for r in results if not r["ok"]]
        redirected = [r for r in results if r["redirected"]]
        passed = len(broken) == 0

        evidence = {
            "url": url,
            "scope": scope,
            "checked": len(results),
            "broken_count": len(broken),
            "broken_links": broken,
            "redirected_count": len(redirected),
            "redirected_links": redirected,
            "all_results": results,
            "rendered_via_playwright": rendered_via_playwright,
            "used_live_page": used_live_page,
            "message": (
                f"All {len(results)} link(s) in scope='{scope}' resolved successfully."
                if passed
                else f"{len(broken)} of {len(results)} link(s) in scope='{scope}' are broken."
            ),
        }

        return CapabilityCheckResult(
            capability=self.capability_type,
            passed=passed,
            confidence=1.0,
            evidence=evidence,
            escalate=False,
        )

    def _fail(self, msg: str) -> CapabilityCheckResult:
        return CapabilityCheckResult(
            capability=self.capability_type,
            passed=False,
            confidence=1.0,
            evidence={"error": msg},
            escalate=False,
        )
