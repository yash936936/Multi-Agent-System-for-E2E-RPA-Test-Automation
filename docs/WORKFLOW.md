# WORKFLOW.md
## AURA — Agent-to-Agent Operational Workflow

This document describes the runtime sequence of agent interactions, coordinated through the **Hermes Agent API**, for a single test-suite execution, including the self-healing feedback loop.

---

## 1. High-Level Flow

```
[Requirement Doc] 
      │
      ▼
┌──────────────────────┐
│ 1. Orchestrator boots     │  ← ingest doc, check skill memory for known patterns
│    & routes (Hermes Agent) │
└──────────┬────────────┘
           ▼
┌──────────────────────┐
│ 2. Planner Agent          │  → Structured Test Spec
└──────────┬────────────┘
           ▼
┌──────────────────────┐
│ 3. Data Synth Agent       │  → Synthetic + edge-case test data
└──────────┬────────────┘
           ▼
┌──────────────────────┐
│ 4. Vision Execution Loop  │  → per-step screenshot, interact, assert
└──────────┬────────────┘
           │  step fails?
           ▼ yes
┌──────────────────────┐
│ 5. Self-Healing Sub-loop  │
│    (Planner + Orchestrator)│
└──────────┬────────────┘
           ▼
┌──────────────────────┐
│ 6. Report Aggregation      │  → HTML/PDF + skill library update
└──────────────────────┘
```

---

## 2. Step-by-Step Sequence

### Step 0 — Session Bootstrap
- The Orchestrator starts up via the Hermes Agent API and registers the Planner, Vision, and Data Synth tools.
- Queries the local skill library for any skills matching the target application's identifier (e.g., `app_id: "internal-crm-v3"`).

### Step 1 — Requirement Ingestion & Spec Generation
1. Orchestrator receives the requirement document (Markdown/PDF/plain text) and issues a tool call to `Planner.generate_spec`.
2. Planner parses the doc and returns a structured **Test Spec** (see TRD §4.1) as a tool response.
3. Orchestrator validates the spec against schema; on validation failure, re-prompts the Planner once before escalating to the user.

### Step 2 — Synthetic Data Generation
1. Orchestrator issues a tool call to `DataSynth.generate` with the `data_requirements` field from the spec.
2. Data Synth generates realistic + boundary-case records.
3. Data is cached to `runtime/data_cache/<test_id>.json`.

### Step 3 — Skill Pre-Check
- Before invoking the Vision agent, the Orchestrator performs a similarity lookup against the skill library using the test spec's `target_description` fields.
- Any matching skill (e.g., "search full header bar, not just top-right corner") is injected into the Vision agent's tool-call context as a prior hint, reducing repeat failures.

### Step 4 — Vision Execution Loop
For each step in the test spec:
1. Orchestrator issues a tool call to `Vision.execute_step` with the current screenshot + step description + any injected skill hints.
2. Vision agent returns a target location, action type, and a **confidence score**.
3. **Confidence gate:**
   - `confidence ≥ 0.75` → runtime hook executes the action (click/type/scroll) immediately.
   - `confidence < 0.75` → action queued; Orchestrator routes to Step 5 (self-healing/diagnosis) *before* execution, treating low confidence as a soft failure.
4. Post-action screenshot captured; assertion checked against `expected_state`.
5. On assertion pass → proceed to next step.
6. On assertion fail → trigger Step 5.

### Step 5 — Self-Healing Sub-Loop
1. Orchestrator issues a tool call to `Planner.diagnose` with: failed step, screenshots (before/after), execution logs, and any network trace data.
2. Planner analyzes the failure and returns a **Diagnostic/Skill Record** (TRD §4.3) with a proposed fix.
3. Orchestrator evaluates the proposed fix:
   - If fix is a **retry strategy** (e.g., broaden search region, wait for animation to complete) → re-attempt the step via the Vision agent, up to the loop-guardrail retry limit.
   - If fix requires **spec correction** (e.g., step order was wrong) → Planner regenerates the affected spec segment.
4. **Loop guardrail check** (per TRD §5.4): if this is the 2nd identical failure → inject a warning into the tool result; if it reaches the hard-stop threshold (default: 5 identical failures) → halt the sub-loop and escalate the step to the human reviewer queue.
5. On successful resolution → the Diagnostic/Skill Record is persisted to the skill library, with `applied_count` incremented on future reuse.

### Step 6 — Report Aggregation
1. Once all steps complete (pass, self-healed, or escalated), the Orchestrator compiles the **Run Report** (TRD §4.4).
2. An HTML report is rendered with:
   - Pass/fail/self-healed/escalated counts
   - Before/after screenshot diffs for every healed step
   - Full tool-call/tool-response audit trace
   - Skill library delta (new skills learned this run)
3. The report is exported to PDF for stakeholder distribution.
4. If scheduled (unattended) run: a report summary is dispatched via the configured local notification channel — full report artifacts remain on local disk only.

---

## 3. Failure Handling Matrix

| Failure Type | Detection | Response |
|---|---|---|
| Low-confidence visual action | Confidence score < 0.75 | Escalate to Planner before execution |
| Element not found | Assertion fails, no matching region | Planner diagnose → skill search → retry |
| Same failure repeats (2×) | Loop guardrail `warn_after.exact_failure` | Inject warning, continue with modified strategy |
| Same failure repeats (5×) | Loop guardrail `hard_stop_after.exact_failure` | Hard stop, escalate to human queue |
| Spec/data schema mismatch | Validation error | Re-prompt Planner once, then escalate |
| Sub-agent unavailable mid-run | Tool call failure via Hermes Agent API | Orchestrator persists state, retries, or aborts gracefully |

---

## 4. Skill Library Lifecycle

```
New Failure → Diagnose → Propose Fix → Apply → Success? 
                                          │
                          ┌───────────────┴───────────────┐
                          ▼ yes                            ▼ no
                 Persist as Skill                 Discard / log for manual review
                 (confidence, signature)
                          │
                          ▼
        Future runs: similarity lookup surfaces skill
        automatically before Vision execution
```

Skills are stored in the `agentskills.io`-compatible format, making them portable and shareable across AURA deployments (e.g., a QA team can export a "known CSS regression" skill pack to another team testing the same internal app).
