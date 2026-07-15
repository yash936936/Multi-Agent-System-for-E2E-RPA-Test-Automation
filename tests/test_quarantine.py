"""
Tests for Phase H2's quarantine store (orchestrator/quarantine_store.py)
and the `aura execute --all` skip-check wiring in aura/main.py.
"""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from orchestrator import quarantine_store


@pytest.fixture(autouse=True)
def _isolated_quarantine_file(tmp_path, monkeypatch):
    """Every test gets its own quarantine.json so tests can't see each
    other's state (or the real project's, if one exists on disk)."""
    fake_path = tmp_path / "quarantine.json"
    monkeypatch.setattr(quarantine_store, "_store_path", lambda: fake_path)
    yield fake_path


def test_quarantine_then_is_quarantined():
    assert quarantine_store.is_quarantined("TC-FLAKY-001") is False
    quarantine_store.quarantine("TC-FLAKY-001", reason="intermittent timing failure")
    assert quarantine_store.is_quarantined("TC-FLAKY-001") is True


def test_quarantine_is_idempotent_and_updates_reason():
    quarantine_store.quarantine("TC-FLAKY-001", reason="first reason")
    quarantine_store.quarantine("TC-FLAKY-001", reason="updated reason")
    entries = quarantine_store.list_quarantined()
    assert entries["TC-FLAKY-001"]["reason"] == "updated reason"
    assert len(entries) == 1


def test_unquarantine_removes_entry_and_reports_false_if_absent():
    quarantine_store.quarantine("TC-FLAKY-001")
    assert quarantine_store.unquarantine("TC-FLAKY-001") is True
    assert quarantine_store.is_quarantined("TC-FLAKY-001") is False
    # Removing something not present returns False, doesn't raise.
    assert quarantine_store.unquarantine("TC-NEVER-QUARANTINED-001") is False


def test_list_quarantined_empty_by_default():
    assert quarantine_store.list_quarantined() == {}


def test_quarantine_file_is_valid_json_on_disk(_isolated_quarantine_file):
    quarantine_store.quarantine("TC-FLAKY-001", reason="x")
    data = json.loads(_isolated_quarantine_file.read_text(encoding="utf-8"))
    assert "TC-FLAKY-001" in data


def test_corrupt_quarantine_file_degrades_to_empty_not_crash(_isolated_quarantine_file):
    _isolated_quarantine_file.parent.mkdir(parents=True, exist_ok=True)
    _isolated_quarantine_file.write_text("{not valid json", encoding="utf-8")
    assert quarantine_store.list_quarantined() == {}


def test_infer_test_id_matches_heading():
    from agents.planner.spec_generator import infer_test_id

    assert infer_test_id("# Login Flow\n\nsome body text") == "TC-LOGIN-FLOW-001"
    assert infer_test_id("no heading at all") == "TC-GENERATED-001"
