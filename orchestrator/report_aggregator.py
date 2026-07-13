"""
Report aggregator.

Collects the stream of VisionActionResult and SkillRecord objects produced
during a run into the final RunReport object (schema from Phase 1). Actual
HTML/PDF rendering is built in Phase 6 (reports/render.py); here we only
produce the structured RunReport plus a path where a renderer can later
find the raw per-step data (JSON, run-scoped).
"""
from __future__ import annotations

import json
import time

from config.settings import settings
from orchestrator.schemas import RunReport, RunStatus, SkillRecord, VisionActionResult


class ReportAggregator:
    def __init__(self, run_id: str, total_steps: int) -> None:
        self.run_id = run_id
        self.total_steps = total_steps
        self._started_at = time.time()
        self._step_results: list[VisionActionResult] = []
        self._skills_learned: list[SkillRecord] = []
        self._escalated_step_ids: set[int] = set()

        self.run_dir = settings.reports_dir / f"run_{run_id}"
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def record_step_result(self, result: VisionActionResult) -> None:
        self._step_results.append(result)
        if result.escalate:
            self._escalated_step_ids.add(result.step_id)

    def get_results(self) -> list[VisionActionResult]:
        """Read-only snapshot of every step result recorded so far."""
        return list(self._step_results)

    def override_step_result(self, step_id: int, corrected: VisionActionResult) -> None:
        """
        Replaces a previously-recorded result for `step_id` with `corrected`.
        Used by RunEngine's bot-trigger/validation-leg cross-check (TRD
        §11.6, Roadmap Phase 21c): a CapabilityType.AUTOMATION_ANYWHERE
        trigger step's result is recorded optimistically as soon as the bot
        reports success, but the *actual* pass/fail verdict for that step
        can only be known once its grouped validation-leg steps (which run
        afterward, per the spec's own step order) have also been checked --
        so this lets RunEngine go back and correct the earlier record
        rather than needing to buffer/delay every step's recording.
        """
        for i, existing in enumerate(self._step_results):
            if existing.step_id == step_id:
                self._step_results[i] = corrected
                break
        if corrected.escalate:
            self._escalated_step_ids.add(step_id)
        else:
            self._escalated_step_ids.discard(step_id)

    def record_skill_learned(self, skill: SkillRecord) -> None:
        self._skills_learned.append(skill)

    def _determine_status(self) -> RunStatus:
        if self._escalated_step_ids:
            return RunStatus.ESCALATED
        failed = [r for r in self._step_results if r.assertion_passed is False]
        if failed:
            return RunStatus.FAILED
        if self._skills_learned:
            return RunStatus.PASSED_WITH_HEALING
        return RunStatus.PASSED

    def finalize(self) -> RunReport:
        duration = time.time() - self._started_at
        raw_path = self.run_dir / "raw_results.json"
        raw_path.write_text(
            json.dumps(
                {
                    "step_results": [json.loads(r.model_dump_json()) for r in self._step_results],
                    "skills_learned": [json.loads(s.model_dump_json()) for s in self._skills_learned],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        report = RunReport(
            run_id=self.run_id,
            status=self._determine_status(),
            total_steps=self.total_steps,
            self_healed_steps=len(self._skills_learned),
            escalated_steps=len(self._escalated_step_ids),
            duration_seconds=round(duration, 2),
            report_paths={"raw_json": str(raw_path)},  # html/pdf keys added in Phase 6
        )

        report_path = self.run_dir / "report.json"
        report_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return report
