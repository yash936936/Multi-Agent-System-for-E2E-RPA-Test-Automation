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

from html.parser import HTMLParser
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


def _check_one(client: httpx.Client, url: str) -> dict:
    try:
        resp = client.head(url, follow_redirects=True, timeout=10.0)
        # Some servers (real-world, not hypothetical -- plenty of CDNs and
        # frameworks) reject HEAD with 405 even though GET works fine.
        # Retry with GET before concluding the link is actually broken.
        if resp.status_code == 405:
            resp = client.get(url, follow_redirects=True, timeout=10.0)
        return {"url": url, "status_code": resp.status_code, "ok": 200 <= resp.status_code < 400, "error": None}
    except httpx.RequestError as e:
        return {"url": url, "status_code": None, "ok": False, "error": str(e)}


class LinkCheckAdapter:
    """
    params:
        url: page to scan (falls back to `target` if omitted)
        scope: "footer" | "nav" | "all" (default "all")
        max_links: safety cap on how many links get live-checked (default 40)
    expected: unused -- pass/fail is purely "did every in-scope link resolve"
    """

    capability_type: CapabilityType = CapabilityType.LINK_CHECK

    def run(self, payload: CapabilityCheckInput) -> CapabilityCheckResult:
        url = (payload.params.get("url") or payload.target or "").strip()
        scope = (payload.params.get("scope") or "all").lower()
        max_links = int(payload.params.get("max_links", 40))

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
                    return CapabilityCheckResult(
                        capability=self.capability_type,
                        passed=False,
                        confidence=1.0,
                        evidence={
                            "url": url,
                            "scope": scope,
                            "checked": 0,
                            "message": f"No navigable <a href> links found in scope='{scope}' on this page.",
                        },
                        escalate=False,
                    )

                results = [_check_one(client, link["resolved_url"]) for link in links[:max_links]]

        except httpx.HTTPStatusError as e:
            return self._fail(f"Could not load {url}: HTTP {e.response.status_code}")
        except httpx.RequestError as e:
            return self._fail(f"Could not reach {url}: {e}")

        broken = [r for r in results if not r["ok"]]
        passed = len(broken) == 0

        evidence = {
            "url": url,
            "scope": scope,
            "checked": len(results),
            "broken_count": len(broken),
            "broken_links": broken,
            "all_results": results,
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
