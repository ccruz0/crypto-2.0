# How to Use the Multi-Agent Operator System

**Version:** 1.1  
**Date:** 2026-03-15

---

## Overview

The multi-agent system routes Notion tasks to specialized analysis agents. Each agent produces a structured note (diagnosis, root cause, proposed fix) that humans review before any changes are applied.

---

## 1. How an Issue Gets Routed

Routing happens inside `select_default_callbacks_for_task` in `backend/app/services/agent_callbacks.py`:

1. **Explicit type check (highest priority):** If Notion Type is `bug`, `bugfix`, or `architecture investigation` → Bug Investigation pack.
2. **Agent routing:** `route_task(prepared_task)` in `agent_routing.py` matches keywords and task type:
   - **Telegram/Alerts:** `telegram`, `alert`, `notification`, `throttle`, `dedup`, `kill switch`, `chat_id`, etc.
   - **Execution/State:** `order`, `execution`, `sync`, `exchange`, `lifecycle`, `sl/tp`, etc.
   - Other agents (Trading Signal, System Health, Docs, Architecture) are scaffolded; they currently fall through to existing logic.
3. **Fallback:** Documentation, monitoring triage, bug investigation (keyword), strategy analysis, generic OpenClaw.

See [ROUTING_CONFIG.md](ROUTING_CONFIG.md) for the full keyword and type mapping.

---

## 2. How to Invoke an Agent

### Via Notion → Backend (automatic)

1. Create a Notion task with Type and Details that match an agent’s keywords.
2. The backend prepares the task and calls `select_default_callbacks_for_task`.
3. If the task routes to Telegram or Execution agent, the apply callback sends a prompt to OpenClaw.
4. OpenClaw returns structured output; the backend saves it under `docs/agents/telegram-alerts/` or `docs/agents/execution-state/`.

### Via Cursor (manual)

1. Open a task’s generated note (e.g. `docs/agents/telegram-alerts/notion-telegram-{task_id}.md`).
2. Use the **Cursor Patch Prompt** section as the basis for a Cursor request.
3. Example: “Apply the fix described in the Cursor Patch Prompt section of docs/agents/telegram-alerts/notion-telegram-xyz.md.”

### Via API (if exposed)

The Cursor Bridge (`POST /api/agent/cursor-bridge/run`) can run a task by `task_id`. If the task routes to an agent, the agent’s apply callback runs.

---

## 3. How to Review Agent Outputs

Each agent note follows the shared schema:

| Section | Purpose |
|---------|---------|
| Issue Summary | One-line description |
| Scope Reviewed | Files/modules checked |
| Confirmed Facts | Verified behavior |
| Mismatches | Expected vs actual |
| Root Cause | Likely cause |
| Proposed Minimal Fix | Concrete change |
| Risk Level | Low / Medium / High |
| Validation Plan | How to verify |
| Cursor Patch Prompt | Ready-to-paste Cursor instruction |

**Review checklist:**

1. Confirm **Scope Reviewed** covers the right modules.
2. Check **Root Cause** is plausible and supported by code.
3. Ensure **Proposed Minimal Fix** does not touch trading/order logic unless intended.
4. Use **Validation Plan** to test before marking deployed.
5. Use **Cursor Patch Prompt** in Cursor only after human approval.

---

## 4. How This Fits with OpenClaw and Cursor Today

```
Notion task
    ↓
Backend (prepare_task, select_default_callbacks_for_task)
    ↓
Agent routing (route_task)
    ↓
If Telegram/Execution: build_telegram_alerts_prompt / build_execution_state_prompt
    ↓
OpenClaw (LAB) — AI analysis
    ↓
Structured note saved to docs/agents/{agent}/
    ↓
Validation (sections, length, no fallback markers)
    ↓
Human review → Cursor (manual) or Cursor Bridge (API)
```

- **OpenClaw:** Hosted on LAB; receives prompts from ATP backend; returns structured text. No change to its hosting.
- **Cursor:** Used for applying fixes. Human copies the Cursor Patch Prompt or uses Cursor Bridge with `task_id`.
- **Trading:** Unchanged. Agents never place or cancel orders.

---

## 5. Artifact Locations

| Agent | Save subdir | File prefix |
|-------|-------------|-------------|
| Telegram and Alerts | `docs/agents/telegram-alerts/` | `notion-telegram` |
| Execution and State | `docs/agents/execution-state/` | `notion-execution` |
| Trading Signal | `docs/agents/trading-signal/` | `notion-signal` |
| System Health | `docs/agents/system-health/` | `notion-health` |
| Docs and Rules | `docs/agents/generated-notes/` | `notion-task` |
| Architecture | `docs/agents/architecture/` | `notion-arch` |

Each artifact: `{prefix}-{task_id}.md` and `{prefix}-{task_id}.sections.json`.

---

## 6. Example Issue-to-Agent Mappings

| Issue | Agent | Route Reason |
|-------|-------|--------------|
| "Alerts not being sent" | Telegram and Alerts | task_type:telegram or keyword:alert |
| "Duplicate alerts" | Telegram and Alerts | keyword:duplicate alert |
| "Throttle too aggressive" | Telegram and Alerts | keyword:throttle |
| "Order not in open orders" | Execution and State | task_type:order or keyword:order |
| "Exchange vs DB mismatch" | Execution and State | keyword:db mismatch |
| "Dashboard wrong state" | Execution and State | keyword:dashboard mismatch |

See [telegram-alerts/EXAMPLES.md](../telegram-alerts/EXAMPLES.md) and [execution-state/EXAMPLES.md](../execution-state/EXAMPLES.md) for full mappings and sample outputs.

**Live validation:** [LIVE_VALIDATION_RUNBOOK.md](LIVE_VALIDATION_RUNBOOK.md) — prerequisite checks, how to trigger tasks, logs, success/failure, rollback.  
**Acceptance checklist:** [ACCEPTANCE_CHECKLIST.md](ACCEPTANCE_CHECKLIST.md) — per-run pass criteria.  
**Real-world test tasks:** [REAL_WORLD_TEST_TASKS.md](REAL_WORLD_TEST_TASKS.md) — sanitized examples.

---

## 7. Failure and Fallback Behavior

### When agent routing cannot initialize

If imports fail (e.g. `agent_routing`, `openclaw_client` — missing `httpx`):

- **Log:** `agent_routing_init_failed error=... — falling through to next callback`
- **Behavior:** Task falls through to documentation, monitoring triage, bug investigation, or generic OpenClaw
- **Diagnostic:** Ensure `httpx` and OpenClaw deps are installed; check backend logs

### When OpenClaw is not configured

- **Log:** `openclaw_fallback reason=not_configured`
- **Behavior:** Agent tasks have no fallback → `{"success": False, "summary": "OPENCLAW_API_TOKEN not configured"}`
- **Fix:** Set `OPENCLAW_API_TOKEN` and `OPENCLAW_API_URL` in env

### When OpenClaw returns low-quality output

- **Apply:** Response fails quality gate (missing sections, too short, fallback markers) → retry or fail
- **Validate:** Agent output validator requires all 9 sections and meaningful content in Root Cause, Proposed Minimal Fix, Risk Level, Cursor Patch Prompt
- **Log:** `agent_output_validation: FAILED — missing required sections` or `critical sections empty or trivial`
- **Action:** Re-run task or improve prompt; check OpenClaw model/output

### When validation fails

- **Log:** `agent_output_validation: FAILED` with specific reason (missing sections, content too short, critical sections weak)
- **Summary:** Returns actionable message, e.g. "Agent output missing required sections: X, Y. Add each as '## X' with content or N/A."
- **Action:** Human reviews note, adds missing sections, or re-triggers agent
