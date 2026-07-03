# AURA — Autonomous Unified RPA Agent

**Autonomous Offline Multi-Agent System for End-to-End RPA Test Automation**
*Orchestrated via the Hermes Agent API*

> Prepared by: Prakhar Doneria · Focus: AI Agents, Software Engineering, Autonomous Testing, RPA

---

## 1. What is AURA?

AURA is a fully **offline, privacy-preserving multi-agent QA system** that plans, generates, executes, self-heals, and reports on RPA test suites without ever touching the cloud. It replaces brittle DOM-locator automation with **vision-first, agent-orchestrated testing** — bots that "see" the screen the way a human QA engineer would, and reason about failures instead of just throwing a stack trace.

The system is coordinated end-to-end through the **[Hermes Agent](https://hermes-agent.nousresearch.com) API** — an open-source, tool-calling, memory-persistent orchestration layer that dispatches work to specialized sub-agents, remembers past failures as reusable "skills," and can recover from stuck loops instead of failing silently. No fixed hardware profile is assumed — the system is designed to be **compressed and optimized as aggressively as technically possible** so its footprint can be tuned to whatever the host machine can spare.

---

## 2. Why This Matters

Traditional RPA scripts break the moment a `div` ID changes or a button moves 4px. QA teams spend more time **maintaining** bots than the bots save. AURA's pitch:

- **Zero cloud reliance** — all orchestration and inference run locally through the Hermes Agent API; no source code, credentials, or business data ever leaves the machine.
- **Visual, not DOM-based** — the vision sub-agent reads the screen like a human, so cosmetic/DOM changes don't break tests.
- **Self-healing** — failures feed back into the orchestrator's memory as diagnosed "skills" so the same class of failure is auto-corrected next run.
- **Minimal footprint by design** — every sub-agent is invoked on demand and released immediately after use, with resource usage compressed as far as the runtime allows rather than being tied to any assumed hardware baseline.

---

## 3. Agent Roster

| Agent | Role | Invocation |
|---|---|---|
| **Orchestrator** | Routes tasks, maintains memory/skills, enforces loop guardrails, aggregates reports | Hermes Agent API (native) |
| **Planner & Auditor** | Converts requirements → structured test specs; root-cause diagnosis | Hermes Agent tool call |
| **Vision Execution Core** | Screen-based UI understanding, coordinate-based interaction, visual assertions | Hermes Agent tool call |
| **Synthetic Data Generator** | Generates realistic + edge-case mock data | Hermes Agent tool call |

The three sub-agents are exposed to the Orchestrator purely as **tools** behind the Hermes Agent API — the Orchestrator only needs each tool's name, input schema, and output contract, never the details of what answers the call underneath. This keeps the system fully swappable and lets each sub-agent's implementation be compressed or resized independently without touching the orchestration logic.

---

## 4. Repository Structure

```
aura/
├── README.md            ← you are here
├── PRD.md                ← product requirements
├── TRD.md                ← technical/architecture spec
├── WORKFLOW.md           ← agent-to-agent operational workflow
├── APPFLOW.md             ← end-user / UI application flow
├── orchestrator/          ← Hermes Agent config, skills, memory store
├── agents/
│   ├── planner/            ← spec-generation & diagnosis tool definitions
│   ├── vision/               ← screenshot pipeline & interaction tool definitions
│   └── data_synth/            ← mock data generator tool definitions
├── runtime/               ← OS hooks, screenshot capture, click dispatch
├── reports/                ← self-healing logs, HTML/PDF test reports
└── config/                 ← Hermes Agent tool registry, compression policy
```

---

## 5. Key Improvements Over the Original Proposal

1. **Hermes Agent API replaces the static Python state handler** — real tool-calling, a structured request/response protocol, and persistent cross-run memory (skills) instead of a hard-coded loop.
2. **Self-healing skill library** — every diagnosed failure becomes a reusable "skill" (compatible with the open [agentskills.io](https://agentskills.io) standard) so recurring UI regressions are fixed automatically on subsequent runs.
3. **Loop guardrails** — stuck-agent detection (repeated identical failures, no-progress loops) with configurable warn/hard-stop thresholds, preventing runaway retries on flaky UIs.
4. **RAG-based regression memory** — historical failure/fix pairs are indexed locally and retrieved to speed up root-cause diagnosis.
5. **Confidence-gated visual actions** — the vision agent emits a confidence score per interaction; low-confidence actions are escalated to the planner instead of executed blind.
6. **Structured HTML/PDF reporting layer** — auto-generated per-run reports with before/after screenshots, diffs, and self-healing changelogs.
7. **Scheduled/unattended runs** — the Hermes Agent's built-in scheduler enables nightly regression sweeps with report delivery to local-network channels, fully offline-capable.
8. **Maximal compression, no assumed baseline** — every sub-agent is loaded/unloaded on demand and shrunk as far as technically possible, so the same architecture scales down to constrained machines without redesign.

---

## 6. Quick Start (Planned)

```bash
# 1. Install the Hermes Agent orchestration layer
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
hermes setup   # connect Hermes Agent to your chosen local inference runtime

# 2. Register the AURA sub-agent tools with Hermes Agent
hermes tools register ./agents/planner
hermes tools register ./agents/vision
hermes tools register ./agents/data_synth

# 3. Launch AURA
python aura/main.py --spec ./requirements/login_flow.md --target ./target_app
```

---

## 7. Documentation Map

- **[PRD.md](./PRD.md)** — problem, personas, goals, success metrics, scope
- **[TRD.md](./TRD.md)** — architecture, orchestration protocol, data schemas
- **[WORKFLOW.md](./WORKFLOW.md)** — agent-by-agent operational sequence, including self-healing loop
- **[APPFLOW.md](./APPFLOW.md)** — user-facing flow from requirement upload to final report

---

## 8. License & Data Handling

MIT-licensed reference implementation. No telemetry; no data leaves the host machine, satisfying regulated/air-gapped QA environments.
