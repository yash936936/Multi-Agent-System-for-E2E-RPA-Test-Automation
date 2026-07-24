"""
config/logging_setup.py

AF2 (docs/decisions.md, Phase AF): every module in this codebase already
does `logging.getLogger(__name__)` -- a grep across the tree turns up
dozens of call sites (planner, browser hook, capability_router, vision
executor, and more) -- but nothing anywhere ever called
`logging.basicConfig()` or attached a handler to the root logger. Python's
behavior for an unconfigured logger hierarchy is: only WARNING-and-above
records are ever emitted at all (via the last-resort handler, to
stderr), and none of it is persisted to a file. Every INFO-level message
like "Planner.generate_spec: retrying HermesAgentBackend after
validation/backend failure" was real, useful diagnostic information that
existed for a split second on a scrolling terminal and then was gone --
not recoverable, not greppable, not part of any audit trail.

configure_logging() fixes this once, centrally, called exactly once from
aura/main.py's main() before any subcommand runs:
  - attaches a RotatingFileHandler to the root logger, writing structured
    JSON lines to logs/aura.log (rotates at 10MB, keeps 5 backups, so a
    long-running scheduled/unattended AURA instance can't silently fill a
    disk)
  - also keeps a lightweight stream handler on stderr for interactive use,
    at WARNING+ only, so normal `aura execute` runs aren't flooded with
    every DEBUG/INFO line on screen -- the full detail still goes to the
    file
  - level is controlled by settings.log_level (AURA_LOG_LEVEL), applied to
    the file handler; the console handler stays at WARNING regardless, so
    turning up file-log verbosity for debugging never spams the terminal

Idempotent: safe to call more than once (e.g. from a test, or if a
subcommand calls it defensively) -- does nothing on the second call,
since a root logger that already has a handler installed by this module
is left alone rather than accumulating duplicate handlers (which would
otherwise duplicate every log line once per call).
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import traceback
from pathlib import Path
from typing import Any

_SENTINEL_ATTR = "_aura_configured"


class _JsonFormatter(logging.Formatter):
    """
    One JSON object per line -- deliberately not human-prose formatted,
    so logs/aura.log is greppable/jq-able for exactly the kind of
    after-the-fact question AB2's assertion_audit_log.py and AE2's
    aura audit-report already answer for assertion evidence, but for
    every other log line in the system too (which backend was tried,
    which capability adapter ran, what failed and why).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info))
        # Any extra= fields passed to logger.info(..., extra={...}) ride
        # along automatically -- record.__dict__ includes them, and this
        # filters out only the standard LogRecord attributes.
        standard_attrs = {
            "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
            "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "created", "msecs", "relativeCreated", "thread", "threadName",
            "processName", "process", "taskName",
        }
        for key, value in record.__dict__.items():
            if key not in standard_attrs and key not in payload:
                try:
                    json.dumps(value)  # only include JSON-serializable extras
                    payload[key] = value
                except (TypeError, ValueError):
                    payload[key] = repr(value)
        return json.dumps(payload)


def configure_logging(log_dir: str | Path = "logs", filename: str = "aura.log") -> None:
    root = logging.getLogger()

    if getattr(root, _SENTINEL_ATTR, False):
        return  # already configured this process -- don't double-attach handlers

    from config.settings import settings  # deferred import: avoids import-cycle risk at module load time

    level_name = (settings.log_level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    os.makedirs(log_dir, exist_ok=True)
    file_path = Path(log_dir) / filename

    file_handler = logging.handlers.RotatingFileHandler(
        file_path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(_JsonFormatter())

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    root.setLevel(min(level, logging.WARNING))
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    setattr(root, _SENTINEL_ATTR, True)
