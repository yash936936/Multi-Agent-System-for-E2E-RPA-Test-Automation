"""
tests/fixtures/pages.py

AB1 (docs/decisions.md D-057's backlog) -- canned HTML fixture pages for
the real-(headless-)browser test tier. Every bug found in this session
that mocked tests missed (dom_scroll's sign inversion, Lenis
interception, the nested-Playwright link-check failure) was only
visible against a real page in a real browser. These fixtures are the
shared, minimal reproduction of each such page shape, so future tests
don't need a live internet connection or a real deployed site to
exercise the same conditions.
"""
from __future__ import annotations

PLAIN_TALL_PAGE = b"""
<html><body style="height:5000px; margin:0;"><h1>Top of a tall page</h1></body></html>
"""

LENIS_TALL_PAGE = b"""
<html class="lenis"><body style="height:5000px; margin:0;">
<h1>Top of a Lenis-driven tall page</h1>
<script>
window.lenis = {
  scroll: 0, limit: 4400, animatedScroll: 0,
  scrollTo: function(y, opts) { this.scroll = y; this.animatedScroll = y; }
};
</script>
</body></html>
"""

# Simulates a React-Router-style SPA: the server-rendered/initial HTML is
# just a bare mount point (no <a href> at all, matching what a plain
# httpx.get() sees against a real client-rendered site before JS runs);
# "hydration" then injects the real nav/footer links into the DOM a
# moment later, same as the real portfolio site this was found against.
SPA_CLIENT_ROUTING_PAGE = b"""
<html><body>
<div id="root"></div>
<script>
setTimeout(function () {
  document.getElementById("root").innerHTML =
    '<nav><a href="/work">Work</a><a href="/about">About</a>' +
    '<a href="/contact">Contact</a></nav>' +
    '<footer><a href="/services/ai">Services</a>' +
    '<a href="https://github.com/example">GitHub</a></footer>';
}, 50);
</script>
</body></html>
"""

# A genuine error page with real, readable text on it -- used to track
# check_assertion's documented known limitation (docs/decisions.md
# D-056): the shape-based structural fallback can tell "nothing
# rendered" from "something rendered", but not yet "the RIGHT thing
# rendered" from "an error rendered". See
# tests/test_real_browser_fixtures.py's xfail(strict=True) test built on
# this fixture -- it exists so a future genuine fix to that limitation
# is caught (as an unexpected pass) rather than silently landing unnoticed.
FAKE_500_ERROR_PAGE = b"""
<html><body style="font-family: sans-serif; text-align: center; padding-top: 100px;">
<h1>500 Internal Server Error</h1>
<p>Something went wrong on our end. Please try again later.</p>
</body></html>
"""
