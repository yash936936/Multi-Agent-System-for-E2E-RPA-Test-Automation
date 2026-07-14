"""
Tests for aura/cli/explore_cmd.py's link-check opt-in behavior.

Previously `explore()` always passed `page_url` to `run_exploration()`
(link_check_scope defaulting to "all"), so the real HTTP-level link check
ran on every `aura explore <url>` call whether or not it was asked for.
It's opt-in now via `check_links` (CLI: --check-links); link_scope only
has any effect when check_links is True.
"""
from __future__ import annotations

import pytest

from aura.cli import explore_cmd
from orchestrator.ui_audit_runner import UIAuditReport


@pytest.fixture(autouse=True)
def _stub_environment(monkeypatch, tmp_path):
    # Isolate from any real browser/display/network and from the repo's
    # own reports/ directory. reports_dir is a read-only property, so
    # patch it at the class level rather than the instance.
    from config.settings import Settings, settings

    monkeypatch.setattr(settings, "human_action_poll_interval_seconds", 0)
    monkeypatch.setattr(Settings, "reports_dir", property(lambda self: tmp_path))
    monkeypatch.setattr("runtime.hooks.browser.open_url", lambda *a, **k: None)
    monkeypatch.setattr("runtime.hooks.capture.capture_screenshot", lambda rid, idx: str(tmp_path / "shot.png"))
    monkeypatch.setattr(
        "orchestrator.autoscan.run_autoscan",
        lambda provider, run_id: type("R", (), {"all_issues": [], "reached_bottom": True, "display_unavailable": False})(),
    )


def test_explore_does_not_link_check_by_default(monkeypatch):
    captured = {}

    def fake_run_exploration(provider, run_id, max_elements=25, requirement_prompt=None, page_url=None, link_check_scope=None):
        captured["page_url"] = page_url
        captured["link_check_scope"] = link_check_scope
        return UIAuditReport(has_nav=True, has_hero=False, has_footer=True, checked=[], page_issues=[])

    monkeypatch.setattr("orchestrator.ui_audit_runner.run_exploration", fake_run_exploration)

    explore_cmd.explore("https://example.com")

    # No --check-links passed -> page_url must be None so run_exploration
    # never performs the real HTTP link check at all.
    assert captured["page_url"] is None


def test_explore_link_checks_when_explicitly_requested(monkeypatch):
    captured = {}

    def fake_run_exploration(provider, run_id, max_elements=25, requirement_prompt=None, page_url=None, link_check_scope=None):
        captured["page_url"] = page_url
        captured["link_check_scope"] = link_check_scope
        return UIAuditReport(has_nav=True, has_hero=False, has_footer=True, checked=[], page_issues=[])

    monkeypatch.setattr("orchestrator.ui_audit_runner.run_exploration", fake_run_exploration)

    explore_cmd.explore("https://example.com", check_links=True, link_scope="footer")

    assert captured["page_url"] == "https://example.com"
    assert captured["link_check_scope"] == "footer"


def test_explore_json_report_records_whether_link_check_was_requested(monkeypatch, tmp_path):
    def fake_run_exploration(provider, run_id, max_elements=25, requirement_prompt=None, page_url=None, link_check_scope=None):
        return UIAuditReport(has_nav=False, has_hero=False, has_footer=False, checked=[], page_issues=[])

    monkeypatch.setattr("orchestrator.ui_audit_runner.run_exploration", fake_run_exploration)

    explore_cmd.explore("https://example.com")

    report_files = list(tmp_path.rglob("report.json"))
    assert len(report_files) == 1
    import json

    data = json.loads(report_files[0].read_text())
    assert data["link_check_requested"] is False
    assert data["link_check_scope"] is None
