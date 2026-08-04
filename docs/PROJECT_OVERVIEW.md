# AURA — Autonomous Unified RPA Agent

**Offline multi-agent system for RPA/UI test automation.**

## 1. What AURA is

AURA plans, generates, executes, self-heals, and reports on QA test suites. It locates UI elements via the DOM (accessibility tree, primary path) or OCR-on-screenshot (fallback, no DOM available) instead of relying only on brittle fixed selectors.

The orchestration/dispatch layer is an in-repo kernel (`orchestrator/kernel.py`) with no required external services. An optional integration with a real [Hermes Agent](https://github.com/NousResearch/hermes-agent) instance exists for anyone who already runs one and wants its memory/skill recall (`orchestrator/hermes_client.py`, `AURA_PLANNER_BACKEND=hermes_agent`) — off by default.

## 2. Core behavior

- **Offline by default** — the heuristic parser and local `.gguf` LLM planner backends make no network calls. The optional `cloud_llm` backend (any OpenAI-compatible HTTP endpoint) only activates if you set `AURA_PLANNER_BACKEND=cloud_llm` and `cloud_llm_base_url`. Capability adapters (API/DB/email/file/cloud-storage checks) are network- or filesystem-facing by design when configured to be — see `docs/README.md#configuration-env`.
- **DOM-first, OCR fallback** — `agents/vision/dom_locator.py` resolves elements via the accessibility tree when a live Playwright page exists; `runtime/hooks/os_fallback.py` + OCR is the fallback for native desktop apps or the no-URL `--interactive` case.
- **Self-healing** — a failed step's diagnosis is stored as a `SkillRecord` (`orchestrator/skill_store.py`) keyed by `failure_signature`; on later runs, matching skills are retrieved via `difflib`-based text similarity (`find_similar()`) before a step is attempted. No embedding model or network call is involved. Skills export/import in an `agentskills.io`-compatible JSON format.
- **Loop guardrails** — configurable warn/hard-stop thresholds on repeated identical failures and no-progress loops (`orchestrator/guardrails.py`).
- **Confidence-gated actions** — the vision agent's `execute_step` reports a confidence score per action; below `vision_confidence_threshold` (default `0.75`), the step is escalated instead of executed (`config/settings.py`).
- **HTML/PDF reporting** — per-run reports rendered via Jinja2 templates (`reports/`).
- **Scheduled runs** — `aura schedule add "<cron>" <test_id>` wraps `APScheduler` (`orchestrator/scheduler.py`); nightly runs post a summary-only notification, not the full report.
- **Resource use is not tied to a fixed hardware baseline** — sub-agents run on demand per call rather than staying resident.

## 3. Agent roster

| Agent | Role | Where |
|---|---|---|
| Orchestrator | Task routing, memory/skills, guardrails, report aggregation | `orchestrator/kernel.py` |
| Planner & Auditor | Requirement → structured test spec; root-cause diagnosis | `agents/planner/` |
| Vision Execution Core | Element location, interaction, visual assertions | `agents/vision/` |
| Synthetic Data Generator | Realistic + edge-case mock data | `agents/data_synth/` |

## 4. Repository structure

```
AURA-QA-Testing-Automation/
├── docs/                 ← PRD.md, TRD.md, WORKFLOW.md, APPFLOW.md, README.md, this file
├── aura/                 ← CLI entry point (aura/main.py) and command implementations (aura/cli/)
├── orchestrator/         ← kernel, run engine, healing loop, skill store, scheduler
├── agents/
│   ├── planner/            ← spec generation & diagnosis
│   ├── vision/              ← screenshot/DOM pipeline & interaction
│   ├── data_synth/          ← mock data generator
│   └── capability/          ← API/DB/Email/File/Excel/PDF/Cloud/Workflow adapters
├── runtime/hooks/        ← OS hooks, screenshot capture, click dispatch
├── reports/              ← HTML/PDF report rendering
├── config/               ← settings.py, tool registry
├── api/                  ← FastAPI service layer (preview — see docs/README.md)
├── webui/                ← static web dashboard served by api/main.py
└── tests/                ← pytest suite
```

## 5. Quick start

See `docs/README.md` for the maintained install and run instructions (`aura init`, `aura execute requirements_input\example_login_flow.md`, `aura execute --all`).

## 6. Documentation map

- **[PRD.md](./PRD.md)** — problem, personas, goals, scope
- **[TRD.md](./TRD.md)** — architecture, data schemas
- **[WORKFLOW.md](./WORKFLOW.md)** — agent-by-agent operational sequence
- **[APPFLOW.md](./APPFLOW.md)** — user-facing flow from requirement upload to report

## 7. License & data handling

MIT-licensed. No telemetry. Network calls only occur where explicitly configured (see §2).
