"""
aura init — aura/cli/init_cmd.py

First-time setup wizard from APPFLOW.md §2.1.3: target app type,
scheduled-run opt-in + local notification channel, compression policy.
Writes answers to config/local_config.json (gitignored) so later commands
(execute/schedule) can read them without re-prompting.
"""
from __future__ import annotations

import json

from rich.console import Console

from config.settings import settings

console = Console()

_CONFIG_PATH_NAME = "local_config.json"


def _config_path():
    return settings.project_root / "config" / _CONFIG_PATH_NAME


def load_local_config() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_local_config(config: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def run_init_wizard(non_interactive: bool = False) -> dict:
    settings.ensure_dirs()

    if non_interactive:
        config = {
            "target_app_type": "desktop",
            "scheduled_runs_enabled": False,
            "notification_channel": None,
            "compression_mode": settings.compression_mode,
        }
        save_local_config(config)
        console.print(f"[green]Wrote default config to {_config_path()}[/green] (non-interactive mode)")
        return config

    console.print("[bold]AURA setup wizard[/bold]\n")

    target_app_type = console.input("Target application type \\[desktop/web] (desktop): ").strip().lower() or "desktop"

    scheduled = console.input("Enable scheduled unattended runs? \\[y/N]: ").strip().lower() == "y"
    channel = None
    if scheduled:
        channel = console.input(
            "Local notification channel for run summaries \\[slack/email/telegram/none] (none): "
        ).strip().lower() or "none"
        if channel == "none":
            channel = None

    compression = console.input(
        f"Resource compression policy \\[max/balanced/off] ({settings.compression_mode}): "
    ).strip().lower() or settings.compression_mode

    config = {
        "target_app_type": target_app_type,
        "scheduled_runs_enabled": scheduled,
        "notification_channel": channel,
        "compression_mode": compression,
    }
    save_local_config(config)

    console.print(f"\n[green]Setup complete.[/green] Config written to {_config_path()}")
    console.print(
        "\nNext: drop a requirement doc into requirements_input/ and run "
        "[bold]aura execute <test_id>[/bold] (or run the login-flow example "
        "already there)."
    )
    return config
