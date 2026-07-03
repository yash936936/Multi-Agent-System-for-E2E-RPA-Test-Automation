"""
Scheduler — orchestrator/scheduler.py

Thin wrapper over APScheduler's BackgroundScheduler giving us the
`aura schedule add "<cron>" <test_id>` surface from APPFLOW.md §2.8.
Persists scheduled-job definitions to a small JSON file (not the live
APScheduler job store) so `aura schedule list` works even without a
running process — the actual job execution binds to run_engine.run()
once Phase 5 exists; for now callers pass any zero-arg callable.

Nightly/unattended runs post summary-only notifications (pass/fail counts),
never a full report — this is decisions.md D-002, kept here as a comment
so whoever wires up the notification channel in Phase 6 doesn't violate it.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings


@dataclass
class ScheduledJob:
    job_id: str
    cron: str
    test_id: str


class Scheduler:
    def __init__(self, registry_path: Path | None = None) -> None:
        self.registry_path = registry_path or (settings.memory_dir / "scheduled_jobs.json")
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._scheduler = BackgroundScheduler()
        self._jobs: dict[str, ScheduledJob] = self._load()

    def _load(self) -> dict[str, ScheduledJob]:
        if not self.registry_path.exists():
            return {}
        raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        return {j["job_id"]: ScheduledJob(**j) for j in raw}

    def _persist(self) -> None:
        self.registry_path.write_text(
            json.dumps([j.__dict__ for j in self._jobs.values()], indent=2),
            encoding="utf-8",
        )

    def add(self, cron: str, test_id: str, runnable: Callable[[], None] | None = None) -> ScheduledJob:
        """
        cron: standard 5-field cron string, e.g. "0 2 * * *" for nightly at 2am.
        runnable: zero-arg callable to invoke (typically run_engine.run bound
                  to test_id) — optional so `aura schedule add` works before
                  Phase 5's run engine exists; job just won't fire yet.
        """
        # NOT f"job_{test_id}_{len(self._jobs) + 1}" -- that scheme collides
        # (and silently overwrites an existing job in self._jobs) as soon as
        # a job is removed and a new one added for the same test_id, since
        # the dict length can repeat a previously-issued suffix. A uuid
        # suffix is monotonically unique regardless of add/remove history.
        job_id = f"job_{test_id}_{uuid.uuid4().hex[:8]}"
        job = ScheduledJob(job_id=job_id, cron=cron, test_id=test_id)
        self._jobs[job_id] = job
        self._persist()

        if runnable is not None:
            trigger = CronTrigger.from_crontab(cron)
            self._scheduler.add_job(runnable, trigger=trigger, id=job_id)

        return job

    def remove(self, job_id: str) -> bool:
        existed = job_id in self._jobs
        self._jobs.pop(job_id, None)
        self._persist()
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
        return existed

    def list(self) -> list[ScheduledJob]:
        return list(self._jobs.values())

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
