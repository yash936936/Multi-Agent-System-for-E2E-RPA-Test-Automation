"""
UI landmark audit — agents/vision/ui_audit.py

Classifies whatever OCR detects on a screenshot into the landmark regions
a professional QA tester would check by default (nav, hero, footer) and
flags text that looks like an interactive element (nav link / button),
purely from position-on-screen + common label vocabulary -- AURA has no
DOM access (vision-first, by design), so this is a heuristic, not a
semantic understanding of the page structure. It's deliberately
conservative: false negatives (missing a real nav item) are far less
costly here than false positives (flagging body text as "broken nav").

Two responsibilities, kept separate and independently testable:
  - classify_landmarks(): pure function, no I/O, given already-extracted
    OCR elements + page height -> which band each element falls in.
  - audit_screenshot(): the thin I/O wrapper that actually runs OCR via
    agents/vision/locator.py and calls classify_landmarks().

The live "click every nav item and see what breaks" behavior lives in
orchestrator/ui_audit_runner.py, which uses this module's classification
to decide *what* to click; this module only answers "what's on the page
and where."
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Band boundaries as a fraction of total page height. A typical page has
# a slim nav bar at the very top and a footer at the very bottom, with
# a hero section (large heading + primary CTA) directly below the nav.
# These are heuristic defaults, not exact -- real layouts vary, so the
# audit reports "no hero detected" honestly rather than guessing wrong.
_NAV_BAND_END = 0.10
_HERO_BAND_END = 0.45
_FOOTER_BAND_START = 0.88

_NAV_VOCAB = {
    "home", "about", "about us", "products", "services", "solutions",
    "pricing", "blog", "contact", "contact us", "support", "docs",
    "documentation", "resources", "careers", "company", "team", "faq",
    "login", "log in", "sign in", "sign up", "menu", "search", "cart",
}
_CTA_VOCAB = {
    "get started", "sign up", "sign in", "log in", "login", "subscribe",
    "learn more", "read more", "book now", "book a demo", "request demo",
    "contact us", "contact sales", "download", "try free", "try it free",
    "start free trial", "buy now", "shop now", "submit", "send", "join now",
    "explore", "discover more", "watch video", "see plans", "view pricing",
}
_FOOTER_VOCAB = {
    "privacy", "privacy policy", "terms", "terms of service", "terms of use",
    "cookie policy", "cookies", "copyright", "all rights reserved",
    "sitemap", "careers", "facebook", "twitter", "linkedin", "instagram",
    "youtube", "newsletter", "unsubscribe",
}


@dataclass
class UIElement:
    text: str
    cx: int
    cy: int
    band: str  # "nav" | "hero" | "body" | "footer"
    looks_interactive: bool
    # Scroll position (window.scrollY) the page was at when cx/cy were
    # captured -- 0 for OCR-sourced elements (always captured at whatever
    # scroll position the baseline screenshot was taken at, which callers
    # already handle) and for DOM-sourced elements captured without
    # scrolling. DOM-sourced elements captured below the fold (see
    # agents/vision/dom_extractor.py's to_ui_elements_full_page) need the
    # page scrolled back to this exact position before dispatching a
    # click at (cx, cy), since cx/cy are viewport-relative and only valid
    # at the scroll position they were measured at.
    scroll_y: int = 0


@dataclass
class LandmarkAudit:
    nav_elements: list[UIElement] = field(default_factory=list)
    hero_elements: list[UIElement] = field(default_factory=list)
    footer_elements: list[UIElement] = field(default_factory=list)
    body_elements: list[UIElement] = field(default_factory=list)

    @property
    def has_nav(self) -> bool:
        return len(self.nav_elements) > 0

    @property
    def has_footer(self) -> bool:
        return len(self.footer_elements) > 0

    @property
    def has_hero(self) -> bool:
        # A hero section needs *something* substantial in that band, not
        # just one stray word -- require either an interactive CTA, or at
        # least two text elements (heading + supporting copy), before
        # calling it a real hero section.
        return any(e.looks_interactive for e in self.hero_elements) or len(self.hero_elements) >= 2

    @property
    def interactive_elements(self) -> list[UIElement]:
        return [e for e in self.nav_elements + self.hero_elements + self.footer_elements + self.body_elements if e.looks_interactive]


_CONNECTOR_WORDS = {"a", "i", "an", "of", "to", "in", "on", "&"}
_VOWELS = set("aeiouy")


def _plausible_word(word: str) -> bool:
    """
    Rejects tokens that are almost certainly OCR noise rather than a real
    word: bare punctuation, single stray letters ("Q" from a clipped
    icon/logo), and consonant clusters with no vowel at all (e.g. "Prtly").
    This is intentionally cheap (no dictionary lookup) -- it only screens
    out shapes of string that a real English word/label essentially
    never takes, so it won't flag genuine short words like "Get" or "Buy".
    """
    stripped = word.strip("'\"-.,!?")
    if not stripped:
        return False
    if stripped in _CONNECTOR_WORDS:
        return True
    if not stripped.isalpha():
        return any(ch.isalpha() for ch in stripped)
    if len(stripped) == 1:
        return False  # single stray letters ("Q", "X") are near-always OCR noise
    if not any(ch in _VOWELS for ch in stripped):
        return False  # no vowel at all -- not a plausible English word/label
    return True


def _looks_interactive(text: str, vocab: dict[str, set[str]] | None = None) -> bool:
    """
    `vocab`: optional {"nav": set(...), "cta": set(...), "footer": set(...)}
    override, sourced from Policy.ocr_vocab() (Gap #2, docs/decisions.md
    D-079). Defaults to this module's own hardcoded
    _NAV_VOCAB/_CTA_VOCAB/_FOOTER_VOCAB sets when omitted, so every
    existing caller of this private helper is unaffected.
    """
    normalized = text.strip().lower()
    if not normalized:
        return False
    nav_vocab = vocab["nav"] if vocab else _NAV_VOCAB
    cta_vocab = vocab["cta"] if vocab else _CTA_VOCAB
    footer_vocab = vocab["footer"] if vocab else _FOOTER_VOCAB
    if normalized in nav_vocab or normalized in cta_vocab or normalized in footer_vocab:
        return True
    # Short (<=4 words), title-case-ish text is a common button/link
    # pattern ("Get Started", "Learn More", "Book a Demo") even when it
    # isn't in the fixed vocabulary above -- catches product-specific CTAs
    # without needing to enumerate every possible label.
    words = normalized.split()
    if not (1 <= len(words) <= 4 and text.strip()[:1].isupper()):
        return False
    # Every word must look like a plausible word, or the whole candidate
    # is almost certainly a merged/garbled OCR fragment (e.g. "Partly
    # clot", "Q Search") rather than a real nav item/button label.
    return all(_plausible_word(w) for w in words)


def classify_landmarks(
    elements: list[dict],
    page_height: int,
    band_boundaries: dict[str, float] | None = None,
    vocab: dict[str, set[str]] | None = None,
) -> LandmarkAudit:
    """
    Pure function: given OCR elements (as returned by
    agents.vision.locator.list_text_elements) and the page height in
    pixels, buckets each element into a landmark band and flags whether
    it looks like an interactive nav/button element.

    `band_boundaries`/`vocab`: optional overrides (Gap #2, docs/decisions.md
    D-079), sourced from Policy.band_boundaries()/Policy.ocr_vocab()
    by audit_screenshot() below. Both default to this module's own
    hardcoded constants when omitted, so every existing 2-arg call site
    (including this module's own test suite) is unaffected.
    """
    audit = LandmarkAudit()
    if page_height <= 0:
        return audit

    bounds = band_boundaries or {
        "nav_band_end": _NAV_BAND_END,
        "hero_band_end": _HERO_BAND_END,
        "footer_band_start": _FOOTER_BAND_START,
    }
    nav_cutoff = page_height * bounds["nav_band_end"]
    hero_cutoff = page_height * bounds["hero_band_end"]
    footer_cutoff = page_height * bounds["footer_band_start"]

    for el in elements:
        text = el.get("text", "")
        cy = el.get("cy", 0)
        interactive = _looks_interactive(text, vocab)

        if cy <= nav_cutoff:
            band = "nav"
        elif cy >= footer_cutoff:
            band = "footer"
        elif cy <= hero_cutoff:
            band = "hero"
        else:
            band = "body"

        element = UIElement(text=text, cx=el.get("cx", 0), cy=cy, band=band, looks_interactive=interactive)
        {"nav": audit.nav_elements, "hero": audit.hero_elements, "footer": audit.footer_elements, "body": audit.body_elements}[band].append(element)

    return audit


def audit_screenshot(screenshot_path: str, policy=None) -> LandmarkAudit:
    """
    I/O wrapper: runs OCR on a real screenshot and classifies the result.
    See classify_landmarks() for the pure logic.

    `policy`: optional Policy instance (Gap #2, docs/decisions.md
    D-079) supplying band_boundaries()/ocr_vocab() -- pass one in
    from a caller that already has one (e.g. ui_audit_runner.py, which
    builds a single Policy and reuses it across every screenshot in a
    run) to avoid constructing a fresh Policy()/BrainKnowledge.load() per
    call. Defaults to constructing its own Policy() when omitted, so
    existing single-arg callers keep working -- editing
    brain_knowledge/rules/discovery.yaml or bands.yaml now actually
    changes this function's behavior either way.
    """
    from agents.vision.locator import image_dimensions, list_text_elements
    from orchestrator.brain.policy import Policy

    policy = policy or Policy()

    elements = list_text_elements(screenshot_path)
    _, height = image_dimensions(screenshot_path)
    vocab = {"nav": policy.ocr_vocab("nav"), "cta": policy.ocr_vocab("cta"), "footer": policy.ocr_vocab("footer")}
    return classify_landmarks(elements, height, band_boundaries=policy.band_boundaries(), vocab=vocab)
