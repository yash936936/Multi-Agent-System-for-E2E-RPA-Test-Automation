"""
tests/fixtures/answer_keys.py

Machine-readable expected outcomes for the Phase 0 fixtures in
tests/fixtures/pages.py (MARKETING_SITE_PAGE, SPA_MUTATION_PAGE,
ICON_ONLY_NAV_PAGE). One dict per fixture; tests/integration/ reads
these instead of hardcoding expectations inline, so the answer key is
reviewable/diffable on its own and reusable across multiple test files
(e.g. a future `aura explain` rendering test can assert against the
same key).
"""
from __future__ import annotations

MARKETING_SITE_ANSWER_KEY = {
    "has_nav": True,
    "has_hero": True,
    "has_footer": True,
    # Element ids that must NOT be reported as a real, correctly-passing
    # click -- the footer heading is text, not a control at all, so it
    # shouldn't even appear as a clicked candidate.
    "must_not_be_clickable_text": "Get In Touch",
    # The dead button: clicking it must be attempted (it's a real
    # <button>, so it's a legitimate candidate) but must report
    # state_changed=False -- this is the exact "passed but nothing
    # happened" bug class from D-067.
    "dead_button_id": "dead-button",
    "dead_button_expected_state_changed": False,
    # The LinkedIn link: a real target="_blank" anchor. Must be
    # recognized as opening a new tab, not silently reported as a no-op
    # AND not reported as a same-page state change either.
    "new_tab_link_id": "linkedin-link",
    "new_tab_link_expected_new_tab_opened": True,
    # The CTA button: a real same-page DOM mutation with no navigation.
    # Must report state_changed=True.
    "working_button_id": "cta-button",
    "working_button_expected_state_changed": True,
}

SPA_MUTATION_ANSWER_KEY = {
    "has_nav": True,
    "menu_toggle_id": "menu-toggle",
    "menu_toggle_expected_state_changed": True,
    "menu_toggle_expected_url_changed": False,
}

ICON_ONLY_NAV_ANSWER_KEY = {
    # Only reachable via a live DOM scan -- no OCR-readable nav text
    # exists on this page at all.
    "has_nav": True,
    "search_icon_id": "search-icon",
    "search_icon_expected_state_changed": True,
}
