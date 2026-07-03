from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from orchestrator.schemas import FixType, SkillRecord
from orchestrator.skill_store import SkillStore


@pytest.fixture()
def store() -> SkillStore:
    with tempfile.TemporaryDirectory() as tmp:
        yield SkillStore(db_path=Path(tmp) / "skills.db")


def make_skill(skill_id: str, signature: str, confidence: float = 0.87) -> SkillRecord:
    return SkillRecord(
        skill_id=skill_id,
        failure_signature=signature,
        root_cause="Button relocated after CSS update",
        proposed_fix="Broaden visual search region to full header bar",
        fix_type=FixType.RETRY_STRATEGY,
        confidence=confidence,
    )


def test_save_and_get_roundtrip(store: SkillStore):
    skill = make_skill("SKILL-001", "login_button_not_found_after_css_update")
    store.save(skill)
    fetched = store.get("SKILL-001")
    assert fetched is not None
    assert fetched.failure_signature == skill.failure_signature
    assert fetched.confidence == pytest.approx(0.87)


def test_save_upsert_updates_existing_record(store: SkillStore):
    skill = make_skill("SKILL-001", "login_button_not_found")
    store.save(skill)
    updated = make_skill("SKILL-001", "login_button_not_found", confidence=0.95)
    store.save(updated)
    fetched = store.get("SKILL-001")
    assert fetched.confidence == pytest.approx(0.95)
    assert len(store.all()) == 1


def test_increment_applied(store: SkillStore):
    store.save(make_skill("SKILL-001", "sig"))
    store.increment_applied("SKILL-001")
    store.increment_applied("SKILL-001")
    assert store.get("SKILL-001").applied_count == 2


def test_find_similar_ranks_closest_match_first(store: SkillStore):
    store.save(make_skill("SKILL-001", "login_button_not_found_after_css_update"))
    store.save(make_skill("SKILL-002", "submit_button_not_found_after_layout_change"))
    store.save(make_skill("SKILL-003", "checkout_field_missing_placeholder_text"))

    results = store.find_similar("login_button_not_found_after_update", top_k=2, min_ratio=0.3)
    assert len(results) >= 1
    top_record, top_ratio = results[0]
    assert top_record.skill_id == "SKILL-001"
    assert top_ratio > 0.5


def test_find_similar_respects_min_ratio_filter(store: SkillStore):
    store.save(make_skill("SKILL-001", "completely_unrelated_signature_xyz"))
    results = store.find_similar("login_button_not_found", top_k=3, min_ratio=0.9)
    assert results == []


def test_export_and_import_round_trip(store: SkillStore):
    store.save(make_skill("SKILL-001", "sig_a"), app_id="demo_login_app")
    store.save(make_skill("SKILL-002", "sig_b"), app_id="demo_login_app")
    exported = store.export_skills(app_id="demo_login_app")

    with tempfile.TemporaryDirectory() as tmp:
        new_store = SkillStore(db_path=Path(tmp) / "skills2.db")
        count = new_store.import_skills(exported, app_id="demo_login_app")
        assert count == 2
        assert len(new_store.all()) == 2
        assert new_store.get("SKILL-001").failure_signature == "sig_a"


def test_export_to_file_and_import_from_file(store: SkillStore):
    store.save(make_skill("SKILL-001", "sig_a"), app_id="demo_login_app")
    with tempfile.TemporaryDirectory() as tmp:
        export_path = Path(tmp) / "pack.json"
        store.export_to_file(export_path, app_id="demo_login_app")
        assert export_path.exists()

        new_store = SkillStore(db_path=Path(tmp) / "skills2.db")
        count = new_store.import_from_file(export_path, app_id="demo_login_app")
        assert count == 1


# --------------------------------------------------------------------------
# diff_snapshots (feature roadmap: review self-healing changes between runs)
# --------------------------------------------------------------------------

def test_diff_snapshots_detects_added_skill(store: SkillStore):
    before = store.export_skills()
    store.save(make_skill("SKILL-NEW", "sig_new"))
    after = store.export_skills()

    result = SkillStore.diff_snapshots(before, after)
    assert result["summary"]["added_count"] == 1
    assert result["added"][0]["skill_id"] == "SKILL-NEW"
    assert result["summary"]["removed_count"] == 0
    assert result["summary"]["changed_count"] == 0


def test_diff_snapshots_detects_removed_skill(store: SkillStore):
    store.save(make_skill("SKILL-GONE", "sig_gone"))
    before = store.export_skills()

    with tempfile.TemporaryDirectory() as tmp:
        empty_store = SkillStore(db_path=Path(tmp) / "empty.db")
        after = empty_store.export_skills()

    result = SkillStore.diff_snapshots(before, after)
    assert result["summary"]["removed_count"] == 1
    assert result["removed"][0]["skill_id"] == "SKILL-GONE"


def test_diff_snapshots_detects_confidence_and_applied_count_change(store: SkillStore):
    store.save(make_skill("SKILL-001", "sig_a", confidence=0.5))
    before = store.export_skills()

    store.increment_applied("SKILL-001")
    after = store.export_skills()

    result = SkillStore.diff_snapshots(before, after)
    assert result["summary"]["changed_count"] == 1
    change = result["changed"][0]
    assert change["skill_id"] == "SKILL-001"
    assert "applied_count" in change["changes"]
    assert change["changes"]["applied_count"]["before"] == 0
    assert change["changes"]["applied_count"]["after"] == 1


def test_diff_snapshots_reports_no_differences_for_identical_snapshots(store: SkillStore):
    store.save(make_skill("SKILL-001", "sig_a"))
    snapshot = store.export_skills()

    result = SkillStore.diff_snapshots(snapshot, snapshot)
    assert result["summary"] == {
        "added_count": 0,
        "removed_count": 0,
        "changed_count": 0,
        "unchanged_count": 1,
    }
