"""
orchestrator/brain/router.py

Given an `Intent`, calls into the right *existing* subsystems in the
right order. This module does not reimplement `RunEngine`,
`ui_audit_runner`, `spec_generator`, or the capability adapters --
those stay exactly what they are; the Router's only job is coordination.
See docs/AURA_BRAIN_ARCHITECTURE.md §2.3.

**Phase B1 scope:** only the "explore" intent is migrated end-to-end
here (moved out of `aura/cli/explore_cmd.py`, which becomes a thin
Intent-building + rendering adapter -- see that file's new docstring).
The other intent kinds (`execute_spec`, `execute_prompt`,
`execute_interactive`, `ui_audit`, `capability_check`) are deliberately
left unmigrated with a clear `NotImplementedError` rather than a
half-working duplicate of `execute_cmd.py`'s logic -- B1's goal is one
complete, correct migrated slice proving the pattern, not five
incomplete ones. Migrating those is B1's direct follow-on work, not
B2's (B2 is rule extraction, a different concern).
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from orchestrator.brain.intent import Intent
from orchestrator.brain.policy import Policy


@dataclass
class BrainResult:
    run_id: str
    kind: str
    data: dict[str, Any] = field(default_factory=dict)


class Router:
    def __init__(self, policy: Policy):
        self.policy = policy

    def resolve(self, intent: Intent) -> BrainResult:
        handler = getattr(self, f"_handle_{intent.kind}", None)
        if handler is None:
            raise NotImplementedError(
                f"AuraBrain: intent kind {intent.kind!r} is not yet migrated onto the Brain "
                "(Phase B1 only migrated 'explore' -- see orchestrator/brain/router.py's module "
                "docstring). The CLI/API entrypoint for this intent should keep calling its "
                "existing subsystem functions directly until this is migrated."
            )
        return handler(intent)

    # ------------------------------------------------------------------
    # explore
    # ------------------------------------------------------------------
    def _handle_explore(self, intent: Intent) -> BrainResult:
        """
        Moved verbatim (same call sequence, same defaults) from
        `aura/cli/explore_cmd.py::explore()` as it existed before this
        migration -- this is a coordination move, not a behavior change.
        Rendering (console output, JSON report writing) stays in
        `explore_cmd.py`; this returns the data that rendering needs.
        """
        from config.settings import settings
        from runtime.hooks import browser
        from runtime.hooks.browser import normalize_url
        from runtime.hooks.capture import capture_screenshot

        url = intent.get("url")
        max_elements = intent.get("max_elements", 25)
        prompt = intent.get("prompt")
        scroll_scan = intent.get("scroll_scan", True)
        check_links = intent.get("check_links", False)
        link_scope = intent.get("link_scope", "all")

        run_id = f"explore_{uuid.uuid4().hex[:8]}"
        normalized = normalize_url(url)

        open_error: str | None = None
        try:
            browser.open_url(normalized)
        except Exception as e:  # noqa: BLE001 - surfaced to the caller either way
            open_error = str(e)

        time.sleep(settings.human_action_poll_interval_seconds)

        def provider(rid: str, index: int) -> str:
            # Deliberately does NOT catch NoDisplayError here -- see
            # explore_cmd.py's original note, preserved: run_autoscan and
            # run_exploration each wrap their own calls to this provider in
            # runtime.errors.display_guard(), which only works if the error
            # propagates out of the provider uncaught.
            return str(capture_screenshot(rid, index))

        autoscan_report = None
        if scroll_scan:
            from orchestrator.autoscan import run_autoscan

            autoscan_report = run_autoscan(provider, run_id=run_id)

        from orchestrator.ui_audit_runner import run_exploration

        report = run_exploration(
            provider,
            run_id=run_id,
            max_elements=max_elements,
            requirement_prompt=prompt,
            page_url=normalized if check_links else None,
            link_check_scope=link_scope,
        )

        return BrainResult(
            run_id=run_id,
            kind="explore",
            data={
                "normalized_url": normalized,
                "open_error": open_error,
                "autoscan_report": autoscan_report,
                "report": report,
                "prompt": prompt,
                "check_links": check_links,
                "link_scope": link_scope,
            },
        )
