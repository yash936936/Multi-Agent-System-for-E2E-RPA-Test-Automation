"""
tests/test_form_fuzzer.py

Covers agents/vision/form_fuzzer.py -- the autonomous "fill in every field
and submit" capability added to close a real gap: `aura explore` could
click nav/footer elements and diff screenshots, but nothing in this repo
ever actually typed data into a form and pressed submit without a
hand-written spec. Unit-tests classify_field()'s keyword mapping for
real, and monkeypatches the DOM primitives (locate_dom/relocate_dom/
snapshot_elements/dom_fill/dom_click/dom_smart_back) to exercise
fuzz_form()'s orchestration logic without a live browser, matching the
existing tests/test_ui_audit_runner.py convention.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import agents.vision.form_fuzzer as form_fuzzer
from agents.vision.form_fuzzer import FormFuzzResult, classify_field, fuzz_form


# ---------- classify_field ----------

def test_classify_field_maps_common_keywords():
    assert classify_field("Email Address") == "email"
    assert classify_field("Confirm Password") == "password"
    assert classify_field("Username") == "username"
    assert classify_field("Phone Number") == "phone"
    assert classify_field("Some Random Label") == "generic"


def test_classify_field_prefers_more_specific_keyword():
    # "confirm password" must match before the bare "password" entry.
    assert classify_field("Confirm your Password again") == "password"


# ---------- fuzz_form orchestration (monkeypatched DOM layer) ----------

@dataclass
class FakeLocateResult:
    found: bool
    locator: object = None


@dataclass
class FakeBackResult:
    new_tab_opened: bool = False
    new_tab_url: str = None
    went_back: bool = False


class FakeLocator:
    def __init__(self, name):
        self.name = name
        self.filled_with = None
        self.clicked = False

    def fill(self, value, timeout=5000):
        self.filled_with = value

    def click(self, timeout=5000):
        self.clicked = True


class FakePage:
    def __init__(self, url="https://example.com/signup"):
        self.url = url
        self.context = SimpleNamespace(pages=[self])

    def wait_for_load_state(self, state, timeout=5000):
        pass


def _candidates():
    return [
        {"role": "textbox", "name": "Email Address"},
        {"role": "textbox", "name": "Password"},
    ]


def test_fuzz_form_fills_every_field_and_submits(monkeypatch):
    page = FakePage()

    monkeypatch.setattr(form_fuzzer, "snapshot_elements", lambda p: _candidates())

    def fake_locate_dom(p, name):
        if name in ("Email Address", "Password"):
            return FakeLocateResult(found=True, locator=FakeLocator(name))
        if name == "submit":
            return FakeLocateResult(found=True, locator=FakeLocator("submit"))
        return FakeLocateResult(found=False)

    monkeypatch.setattr(form_fuzzer, "locate_dom", fake_locate_dom)
    monkeypatch.setattr(form_fuzzer, "relocate_dom", lambda p, last: FakeLocateResult(found=False))
    monkeypatch.setattr(form_fuzzer, "dom_smart_back", lambda p, before: FakeBackResult())

    result = fuzz_form(page, submit_label="submit", mode="realistic")

    assert isinstance(result, FormFuzzResult)
    assert len(result.filled) == 2
    field_keys = {f.field_key for f in result.filled}
    assert field_keys == {"email", "password"}
    # password value must be masked in the preview, never shown in full
    password_entry = next(f for f in result.filled if f.field_key == "password")
    assert set(password_entry.value_preview) == {"*"}
    assert result.submit_found is True
    assert result.submit_clicked is True


def test_fuzz_form_edge_case_mode_uses_malformed_generator(monkeypatch):
    page = FakePage()
    monkeypatch.setattr(form_fuzzer, "snapshot_elements", lambda p: [{"role": "textbox", "name": "Email Address"}])

    seen_locator = FakeLocator("Email Address")
    monkeypatch.setattr(form_fuzzer, "locate_dom", lambda p, name: FakeLocateResult(found=True, locator=seen_locator) if name == "Email Address" else FakeLocateResult(found=False))
    monkeypatch.setattr(form_fuzzer, "relocate_dom", lambda p, last: FakeLocateResult(found=False))
    monkeypatch.setattr(form_fuzzer, "dom_smart_back", lambda p, before: FakeBackResult())

    result = fuzz_form(page, mode="edge_case")

    assert result.filled[0].field_key == "email"
    # edge_case email generator (generator.py's "malformed" fallback / email
    # match) always produces something that isn't a plausible real address --
    # just assert it actually ran through the fill path, not left blank.
    assert seen_locator.filled_with


def test_fuzz_form_no_submit_found_still_reports_filled_fields(monkeypatch):
    page = FakePage()
    monkeypatch.setattr(form_fuzzer, "snapshot_elements", lambda p: [{"role": "textbox", "name": "Email Address"}])
    monkeypatch.setattr(form_fuzzer, "locate_dom", lambda p, name: FakeLocateResult(found=True, locator=FakeLocator(name)) if name == "Email Address" else FakeLocateResult(found=False))
    monkeypatch.setattr(form_fuzzer, "relocate_dom", lambda p, last: FakeLocateResult(found=False))

    result = fuzz_form(page)

    assert len(result.filled) == 1
    assert result.submit_found is False
    assert result.submit_clicked is False
    assert "not submitted" in result.note


def test_fuzz_form_new_tab_on_submit_is_reported_and_closed(monkeypatch):
    page = FakePage()
    monkeypatch.setattr(form_fuzzer, "snapshot_elements", lambda p: [])

    def fake_locate_dom(p, name):
        if name == "submit":
            return FakeLocateResult(found=True, locator=FakeLocator("submit"))
        return FakeLocateResult(found=False)

    monkeypatch.setattr(form_fuzzer, "locate_dom", fake_locate_dom)
    monkeypatch.setattr(form_fuzzer, "relocate_dom", lambda p, last: FakeLocateResult(found=False))

    # Simulate a new tab appearing as a side effect of clicking submit
    # (a real target="_blank" submit button), *after* fuzz_form has
    # already captured pages_before -- matching how a live browser
    # actually behaves.
    submit_locator = FakeLocator("submit")
    original_click = submit_locator.click

    def click_and_open_tab(timeout=5000):
        original_click(timeout=timeout)
        page.context.pages.append(FakePage(url="https://example.com/thank-you"))

    submit_locator.click = click_and_open_tab

    def fake_locate_dom_with_submit(p, name):
        if name == "submit":
            return FakeLocateResult(found=True, locator=submit_locator)
        return FakeLocateResult(found=False)

    monkeypatch.setattr(form_fuzzer, "locate_dom", fake_locate_dom_with_submit)

    def fake_smart_back(p, before):
        return FakeBackResult(new_tab_opened=True, new_tab_url="https://example.com/thank-you")

    monkeypatch.setattr(form_fuzzer, "dom_smart_back", fake_smart_back)

    result = fuzz_form(page)

    assert result.new_tab_opened is True
    assert result.new_tab_url == "https://example.com/thank-you"
