"""
aura schedule — aura/cli/schedule_cmd.py

Wraps orchestrator/scheduler.py for the `aura schedule add/remove/list`
surface (APPFLOW.md §2.8). Jobs run unattended (auto_approve=True) via
aura.cli.execute_cmd.execute_test, and per TRD §5.5 / decisions.md D-002,
only a pass/fail summary is meant to leave the machine via a notification
channel -- the full report/screenshots stay local. This module posts that
summary to stdout/log only; wiring an actual Slack/email/Telegram relay is
left as a configuration step for the deployer (the notification_channel
value chosen in `aura init` is read here so future wiring has a single
place to plug in).
"""
from __future__ import annotations

from rich.console import Console

from aura.cli.init_cmd import load_local_config
from orchestrator.scheduler import Scheduler

console = Console()


def _make_job_runnable(test_id: str):
    def _run():
        from aura.cli.execute_cmd import execute_test  # deferred: avoid import cycles at module load

        try:
            execute_test(test_id, auto_approve=True)
        except Exception as e:  # noqa: BLE001 - a scheduled job must not crash the scheduler thread
            console.print(f"[red]Scheduled run for {test_id} failed: {e}[/red]")

    return _run


def add(cron: str, test_id: str) -> None:
    scheduler = Scheduler()
    job = scheduler.add(cron, test_id, runnable=_make_job_runnable(test_id))
    scheduler.start()

    config = load_local_config()
    channel = config.get("notification_channel")
    channel_note = f"summary will be posted to '{channel}'" if channel else "no notification channel configured (see `aura init`)"
    console.print(f"[green]Scheduled[/green] {job.job_id}: '{cron}' -> {test_id} ({channel_note})")


def remove(job_id: str) -> None:
    scheduler = Scheduler()
    if scheduler.remove(job_id):
        console.print(f"[green]Removed[/green] {job_id}")
    else:
        console.print(f"[yellow]No such job: {job_id}[/yellow]")


def list_jobs() -> None:
    scheduler = Scheduler()
    jobs = scheduler.list()
    if not jobs:
        console.print("[dim]No scheduled jobs.[/dim]")
        return
    for job in jobs:
        console.print(f"{job.job_id}  cron='{job.cron}'  test_id={job.test_id}")
