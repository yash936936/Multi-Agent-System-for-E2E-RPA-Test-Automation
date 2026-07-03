# APPFLOW.md
## AURA — End-User Application Flow

This document describes AURA from the perspective of the human user (QA engineer / RPA developer), covering the CLI/TUI and optional dashboard experience. All orchestration behind these flows runs through the **Hermes Agent API**.

---

## 1. User Journey Overview

```
Install → Configure → Upload Requirement → Review Generated Spec →
Run Suite → Monitor Live → Review Report → Approve/Reject Healed Steps →
Schedule Recurring Runs
```

---

## 2. Detailed Flow

### 2.1 Installation & First-Run Setup
1. User installs the Hermes Agent framework:
   ```bash
   curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
   ```
2. `hermes setup` wizard runs, connecting the Hermes Agent API to the user's chosen local runtime.
3. AURA's own setup wizard (`aura init`) registers the Planner, Vision, and Data Synth tools with the Hermes Agent API and asks:
   - Target application type (desktop / web)
   - Whether to enable scheduled unattended runs and, if so, which local notification channel to use.
   - How aggressively to compress/release sub-agent resources between calls (default: maximum compression, on-demand only).

### 2.2 Requirement Upload
1. User places a requirement doc (Markdown, PDF, or plain text) into `requirements/` or drags it into the AURA TUI.
2. AURA displays: *"Ingesting requirement... Planner Agent generating test spec"*.
3. Progress streams live in the TUI via the Hermes Agent API's native streaming tool output.

### 2.3 Spec Review (Human Checkpoint)
1. The generated Test Spec is rendered as a readable checklist (not raw JSON) in the TUI:
   ```
   TC-LOGIN-001: Verify login flow
     [ ] Step 1: Click "Login" button (top-right)
     [ ] Step 2: Enter username (synthetic data: "jane.doe@example.com")
     [ ] Step 3: Assert dashboard visible
   ```
2. The user can edit/approve/reject individual steps before execution — this is the primary human-in-the-loop checkpoint (nothing executes against the live application without explicit approval).
3. On approval, the user runs `aura execute TC-LOGIN-001` or `aura execute --all`.

### 2.4 Live Execution Monitoring
1. The TUI shows live step-by-step progress:
   ```
   ▶ Step 1/20: Click "Login" button       [Vision tool: dispatching...] 
   ▶ Step 1/20: Click "Login" button       [confidence: 0.94 ✓ executed]
   ▶ Step 2/20: Enter username              [executing...]
   ⚠ Step 7/20: Assert dashboard visible    [FAILED — self-healing...]
   ✓ Step 7/20: Assert dashboard visible    [healed via skill SKILL-2026-0417]
   ```
2. The user may interrupt-and-redirect at any point (a native Hermes Agent API feature) — e.g., pause the run to manually inspect a screenshot.
3. Low-confidence actions pause briefly with an inline prompt: *"Vision agent 62% confident — approve this click? [y/N/skip]"* (configurable to fully autonomous mode for CI pipelines).

### 2.5 Self-Healing Notification
1. When a step is auto-healed, the TUI surfaces a concise diff: before-screenshot vs. after-screenshot, plus the one-line root cause ("Login button relocated to header center").
2. The user can accept the healing (skill persists) or reject it (skill discarded, step marked as a true failure for manual triage).

### 2.6 Report Review
1. On run completion, AURA opens (or links to) the generated HTML report:
   - Summary card: `18 passed · 3 self-healed · 1 escalated · 6m52s`
   - Expandable per-step detail with screenshots, confidence scores, and tool-call audit trace.
   - "Skills learned this run" section listing new entries added to the skill library.
2. A downloadable PDF is available for stakeholder/compliance sign-off.

### 2.7 Escalation Handling
1. Steps that hit the loop-guardrail hard-stop appear in a dedicated **"Needs Review"** queue.
2. The user can:
   - Manually re-record the correct action (teaches the Vision agent a ground-truth interaction, stored as a high-confidence skill).
   - Mark the underlying application behavior as a genuine bug (auto-drafts a bug report using the Planner agent, with repro steps and screenshots attached).

### 2.8 Scheduling Recurring Runs
1. User runs `aura schedule add "0 2 * * *" TC-SUITE-REGRESSION` (wraps the Hermes Agent API's native scheduler).
2. Nightly runs execute unattended; only a summary notification (pass/fail counts) is relayed via the configured local channel — full report and screenshots remain local.
3. The user reviews the accumulated "Needs Review" queue each morning.

### 2.9 Skill Library Management (Optional Advanced Flow)
1. `aura skills list` shows all learned skills with confidence and reuse counts.
2. `aura skills export --app internal-crm-v3 > crm_skills.json` allows sharing a skill pack with another QA team/environment running the same application, without sharing any actual test data or screenshots — only the abstracted failure signature and fix strategy.

---

## 3. UI Surfaces Summary

| Surface | Purpose |
|---|---|
| **TUI (primary)** | Live run monitoring, spec approval, interrupt-and-redirect |
| **HTML Report** | Post-run detailed review, stakeholder sharing |
| **PDF Export** | Compliance/audit sign-off artifact |
| **CLI commands** | `aura init`, `aura execute`, `aura schedule`, `aura skills` |
| **Notification relay (optional)** | Local channel — summary-only |

---

## 4. Guiding UX Principle

Every autonomous action AURA takes is **inspectable and reversible before it touches the live application under test**: spec approval, confidence gating, and the healed-step accept/reject checkpoint together ensure the human QA engineer stays the final authority, even as the system becomes more autonomous over time.
