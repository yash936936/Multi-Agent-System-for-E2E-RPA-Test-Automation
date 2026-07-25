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

# ---------------------------------------------------------------------------
# Phase 0 (docs/AURA_REARCHITECTURE_PLAN.md, docs/decisions.md D-069) --
# the real-HTML integration-test fixture tier. Every fixture below has a
# matching answer key in tests/fixtures/answer_keys.py; these are the
# ONLY fixtures in this file with a known-correct expected outcome for
# the *click-audit engine itself* (has_nav/has_hero/has_footer, which
# elements are truly clickable, which click is a real no-op) -- the
# fixtures above this point target narrower, already-fixed bugs
# (scroll direction, link-check hydration, the 500-page limitation).
# These target the class of bug D-067 found: "explore reports passed
# but nothing happened," which no mocked unit test could have caught,
# because the bug was in believing the wrong ground truth, not in a
# function's return value given a fixed input.
# ---------------------------------------------------------------------------

# A small but structurally complete marketing site:
#   - a real <nav> with two real links (About, Contact)
#   - a hero section (<h1> + a real CTA <button> that mutates the DOM
#     in place -- no navigation, so this also exercises Phase 4's
#     MutationObserver path once that lands)
#   - a footer with:
#       * a plain <h2> heading ("Get In Touch") -- must NOT be reported
#         clickable. This is the exact false-positive D-067 fixed.
#       * a real <a target="_blank"> link (id="linkedin-link") --
#         clicking it must be recognized as "opened in a new tab",
#         never as a silent no-op.
#       * a genuinely dead <button id="dead-button"> with no handler
#         at all -- clicking it must report state_changed=False, not
#         a false pass.
MARKETING_SITE_PAGE = b"""
<html><body style="margin:0;">
<nav style="height:60px;">
  <a href="/about">About</a>
  <a href="/contact" id="contact-link">Contact</a>
</nav>
<header style="height:400px;">
  <h1>Welcome to Acme Corp</h1>
  <button id="cta-button" onclick="document.getElementById('cta-result').textContent='Signed up!'">Sign Up</button>
  <p id="cta-result"></p>
</header>
<main style="height:2000px;"><p>Body content.</p></main>
<footer style="height:300px;">
  <h2>Get In Touch</h2>
  <a href="https://linkedin.com/company/acme" target="_blank" id="linkedin-link">LinkedIn</a>
  <button id="dead-button">Do Nothing</button>
</footer>
</body></html>
"""

# SPA-style click-driven mutation with no navigation at all -- the
# specific shape hash-diff can get right by accident but
# MutationObserver gets right by construction (Phase 4).
SPA_MUTATION_PAGE = b"""
<html><body style="margin:0; height:1200px;">
<nav style="height:60px;"><button id="menu-toggle" onclick="document.getElementById('menu').style.display='block'">Menu</button></nav>
<div id="menu" style="display:none;"><a href="/settings">Settings</a></div>
<main><h1>Dashboard</h1></main>
</body></html>
"""

# Icon-only nav: every control has a real accessible name (aria-label)
# but zero OCR-readable text -- only a live DOM scan can find these at
# all. Answer key expects has_nav=True here purely from the DOM path;
# an OCR-only pass on this fixture would report has_nav=False.
ICON_ONLY_NAV_PAGE = b"""
<html><body style="margin:0;">
<nav style="height:60px;">
  <button aria-label="Open search" id="search-icon" onclick="document.getElementById('search-result').textContent='Search opened'"></button>
  <button aria-label="Open menu" id="menu-icon"></button>
</nav>
<p id="search-result"></p>
<main style="height:1500px;"><h1>Icon-only nav test page</h1></main>
</body></html>
"""

