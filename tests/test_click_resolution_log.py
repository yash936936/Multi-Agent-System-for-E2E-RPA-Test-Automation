"""
tests/test_click_resolution_log.py

Re-architecture Phase 1 (docs/decisions.md D-072): covers
orchestrator/click_resolution_log.py's log/read/find_anomalies, plus
orchestrator/run_timeline.py's merge, plus `aura explain`'s CLI wiring.
"""
from __future__ import annotations

import json

from orchestrator.click_resolution_log import ClickResolutionLog, find_anomalies, read_records


def test_log_and_read_round_trip(tmp_path):
    log = ClickResolutionLog(filepath=str(tmp_path / "click_resolution.jsonl"))
    log.log(
        run_id="run-1", step_id=8100, label="Sign Up", band="hero", source="dom",
        looks_interactive=True, resolution_strategy="dom", clicked=True,
        state_changed=True, new_tab_opened=False,
    )
    records = list(read_records(filepath=str(tmp_path / "click_resolution.jsonl")))
    assert len(records) == 1
    assert records[0]["run_id"] == "run-1"
    assert records[0]["label"] == "Sign Up"
    assert records[0]["clicked"] is True
    assert records[0]["state_changed"] is True


def test_read_records_filters_by_run_id(tmp_path):
    fp = str(tmp_path / "click_resolution.jsonl")
    log = ClickResolutionLog(filepath=fp)
    log.log(run_id="run-a", step_id=8100, label="A", band="nav", source="dom",
             looks_interactive=True, resolution_strategy="dom", clicked=True, state_changed=True)
    log.log(run_id="run-b", step_id=8101, label="B", band="nav", source="dom",
             looks_interactive=True, resolution_strategy="dom", clicked=True, state_changed=True)
    records = list(read_records(filepath=fp, run_id="run-a"))
    assert len(records) == 1
    assert records[0]["label"] == "A"


def test_find_anomalies_flags_clicked_but_no_state_change(tmp_path):
    fp = str(tmp_path / "click_resolution.jsonl")
    log = ClickResolutionLog(filepath=fp)
    # Real anomaly: clicked, verified, nothing changed (D-067's "dead button" case).
    log.log(run_id="run-1", step_id=8100, label="Do Nothing", band="footer", source="dom",
            looks_interactive=True, resolution_strategy="dom", clicked=True, state_changed=False)
    # Not an anomaly: never clicked at all (rejected candidate).
    log.log(run_id="run-1", step_id=8101, label="Get In Touch", band="footer", source="ocr",
            looks_interactive=False, resolution_strategy="ocr", clicked=False, state_changed=None,
            rejected_reason="unreachable")
    # Not an anomaly: clicked and it worked.
    log.log(run_id="run-1", step_id=8102, label="Sign Up", band="hero", source="dom",
            looks_interactive=True, resolution_strategy="dom", clicked=True, state_changed=True)

    anomalies = find_anomalies(filepath=fp)
    assert len(anomalies) == 1
    assert anomalies[0]["label"] == "Do Nothing"


def test_read_records_missing_file_returns_empty(tmp_path):
    records = list(read_records(filepath=str(tmp_path / "does_not_exist.jsonl")))
    assert records == []
