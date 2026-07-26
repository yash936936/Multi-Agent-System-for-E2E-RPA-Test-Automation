"""
tests/test_dom_change_detector.py

Phase 4 (docs/decisions.md D-077). Unit tests for
agents/vision/dom_change_detector.py's arm()/read_result() against a
fake Playwright-shaped page, plus the graceful-degradation contract
(arm/read failures never raise -- they report armed=False so callers
fall back to hash-diff for that one check).
"""
from __future__ import annotations

from agents.vision.dom_change_detector import arm, read_result


class FakePage:
    def __init__(self, arm_result=True, read_result_value=None, raise_on_arm=False, raise_on_read=False):
        self._arm_result = arm_result
        self._read_result_value = read_result_value or {"count": 0, "urlBefore": "http://x", "urlAfter": "http://x", "sample": []}
        self._raise_on_arm = raise_on_arm
        self._raise_on_read = raise_on_read
        self.arm_calls = []
        self.read_calls = 0

    def evaluate(self, js, arg=None):
        if "__aura_mutations = []" in js:  # the arm script
            if self._raise_on_arm:
                raise RuntimeError("page closed mid-arm")
            self.arm_calls.append(arg)
            return self._arm_result
        else:  # the read script
            if self._raise_on_read:
                raise RuntimeError("page navigated away, no __aura_mutations in this document")
            self.read_calls += 1
            return self._read_result_value


def test_arm_passes_ignore_selectors_through_and_returns_true_on_success():
    page = FakePage()
    ok = arm(page, ["[data-ad]", ".analytics-beacon"])
    assert ok is True
    assert page.arm_calls == [["[data-ad]", ".analytics-beacon"]]


def test_arm_defaults_to_empty_list_when_no_selectors_given():
    page = FakePage()
    arm(page)
    assert page.arm_calls == [[]]


def test_arm_degrades_to_false_on_exception_never_raises():
    page = FakePage(raise_on_arm=True)
    assert arm(page) is False


def test_read_result_reports_mutated_true_when_mutations_recorded():
    page = FakePage(read_result_value={"count": 3, "urlBefore": "http://x", "urlAfter": "http://x", "sample": [{"type": "childList", "tag": "DIV"}]})
    result = read_result(page)
    assert result.armed is True
    assert result.mutated is True
    assert result.mutation_count == 3
    assert result.url_changed is False
    assert len(result.sample_mutations) == 1


def test_read_result_reports_url_changed_independent_of_mutation_count():
    """A real navigation with zero recorded DOM mutations (the observer's
    document context got destroyed before anything else was recorded)
    must still count as a real change via url_changed."""
    page = FakePage(read_result_value={"count": 0, "urlBefore": "http://x/a", "urlAfter": "http://x/b", "sample": []})
    result = read_result(page)
    assert result.mutated is False
    assert result.url_changed is True


def test_read_result_degrades_to_unarmed_on_exception_never_raises():
    page = FakePage(raise_on_read=True)
    result = read_result(page)
    assert result.armed is False
    assert result.error is not None
    assert result.mutated is False  # safe default, not an exception propagating up


def test_read_result_respects_settle_wait(monkeypatch):
    slept = {}
    monkeypatch.setattr("agents.vision.dom_change_detector.time.sleep", lambda s: slept.setdefault("seconds", s))
    page = FakePage()
    read_result(page, settle_wait_seconds=0.5)
    assert slept["seconds"] == 0.5
