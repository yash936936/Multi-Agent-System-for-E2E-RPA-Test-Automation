"""
tests/test_scheduler.py

Regression coverage for a real bug found and fixed in this session:
Scheduler.add() previously generated job_id as
f"job_{test_id}_{len(self._jobs) + 1}" -- purely a function of the current
dict size. Removing a job and adding a new one for the same test_id could
reuse an id still held by another job, silently overwriting it in
self._jobs (and in the persisted registry) instead of creating a distinct
job. Fixed by switching to a uuid suffix, which is unique regardless of
add/remove history.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from orchestrator.scheduler import Scheduler


@pytest.fixture()
def scheduler(tmp_path: Path) -> Scheduler:
    return Scheduler(registry_path=tmp_path / "scheduled_jobs.json")


def test_job_ids_are_unique_even_after_remove_and_readd(scheduler: Scheduler):
    j1 = scheduler.add("0 2 * * *", "TC-A")
    j2 = scheduler.add("0 3 * * *", "TC-A")
    j3 = scheduler.add("0 4 * * *", "TC-A")

    scheduler.remove(j1.job_id)

    j4 = scheduler.add("0 5 * * *", "TC-A")

    all_ids = [j.job_id for j in scheduler.list()]
    assert len(all_ids) == len(set(all_ids)), "job ids must stay unique across add/remove cycles"

    # j2 and j3 must survive untouched -- the old len()-based scheme could
    # reuse either id for j4 and silently overwrite it.
    surviving_crons = {j.job_id: j.cron for j in scheduler.list()}
    assert surviving_crons[j2.job_id] == "0 3 * * *"
    assert surviving_crons[j3.job_id] == "0 4 * * *"
    assert surviving_crons[j3.job_id] == "0 4 * * *"
    assert j4.job_id != j3.job_id
    assert len(scheduler.list()) == 3


def test_many_add_remove_cycles_never_collide(scheduler: Scheduler):
    seen_ids: set[str] = set()
    for i in range(25):
        job = scheduler.add("0 2 * * *", "TC-SAME-ID")
        assert job.job_id not in seen_ids
        seen_ids.add(job.job_id)
        if i % 2 == 0:
            scheduler.remove(job.job_id)
            seen_ids.discard(job.job_id)
