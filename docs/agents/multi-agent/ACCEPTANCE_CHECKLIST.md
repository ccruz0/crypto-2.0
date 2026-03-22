# Acceptance Checklist — Agent Run

**Version:** 1.1  
**Date:** 2026-03-22

A run is **good** only if all items below pass. Use this after each validation run.

---

## 0. Telegram `/task` vs agent-heavy commands

| Command | Backend behavior (ATP Control bot → `backend-aws`) |
|---------|------------------------------------------------------|
| **`/task &lt;text&gt;`** | **Direct Notion write only** (`create_notion_task_from_telegram_direct` → `create_notion_task`). **No OpenClaw, no LLM** in this path. |
| **`/investigate`**, **`/agent`** (when they register a task) | May use **`create_task_from_telegram_intent`** (compile + Notion + pipeline hooks). Agent execution is separate (scheduler / OpenClaw as configured). |

**Prod smoke:** see [TELEGRAM_TASK_PROD_VERIFICATION.md](../../runbooks/TELEGRAM_TASK_PROD_VERIFICATION.md).

---

## 1. Routing

| # | Check | Pass? |
|---|-------|-------|
| 1.1 | Correct agent was selected (`telegram_alerts` or `execution_state`) | ☐ |
| 1.2 | Routing reason is explicit in logs (`route_reason=task_type:telegram` or `keyword:alert`, etc.) | ☐ |
| 1.3 | No `agent_routing_init_failed` (if present, fallback was used) | ☐ |

---

## 2. Fallback Behavior

| # | Check | Pass? |
|---|-------|-------|
| 2.1 | If fallback used: `openclaw_fallback` log states reason (`not_configured`, `openclaw_error`, etc.) | ☐ |
| 2.2 | If fallback used: behavior is documented (template vs fail) | ☐ |
| 2.3 | No silent fall-through (wrong agent selected without log) | ☐ |

---

## 3. Output Schema

| # | Check | Pass? |
|---|-------|-------|
| 3.1 | All 9 required sections present: Issue Summary, Scope Reviewed, Confirmed Facts, Mismatches, Root Cause, Proposed Minimal Fix, Risk Level, Validation Plan, Cursor Patch Prompt | ☐ |
| 3.2 | `agent_output_validation: PASSED` in logs | ☐ |
| 3.3 | Artifact file exists and is ≥500 chars (body after `---`) | ☐ |

---

## 4. Content Quality

| # | Check | Pass? |
|---|-------|-------|
| 4.1 | **Root Cause** is concrete (cites code path, env var, or exchange behavior) | ☐ |
| 4.2 | **Proposed Minimal Fix** is specific (file paths, exact steps, or config keys) | ☐ |
| 4.3 | **Validation Plan** is actionable (commands, checks, or rollback steps) | ☐ |
| 4.4 | **Risk Level** contains LOW, MEDIUM, or HIGH with brief justification | ☐ |
| 4.5 | **Cursor Patch Prompt** is copy-pasteable and safe (no credential changes) | ☐ |

---

## 5. Agent-Specific

### Telegram and Alerts

| # | Check | Pass? |
|---|-------|-------|
| 5.1 | Scope Reviewed cites `telegram_notifier`, `alert_emitter`, or `signal_throttle` | ☐ |
| 5.2 | No tokens or secrets in output | ☐ |
| 5.3 | Proposed fix does not change production send logic without approval note | ☐ |

### Execution and State

| # | Check | Pass? |
|---|-------|-------|
| 5.4 | Scope Reviewed cites `exchange_sync`, `signal_monitor`, or `crypto_com_trade` | ☐ |
| 5.5 | Did not assume "missing from open orders" = canceled without exchange confirmation | ☐ |
| 5.6 | Proposed fix does not change order placement logic | ☐ |

---

## 6. Troubleshooting: No Response to /investigate or /agent

**HILOVIVO3.0 is alerts-only.** Use ATP Control (private group or direct chat) for commands.

If commands in ATP Control produce no response:

| # | Check | Action |
|---|-------|--------|
| 6.1 | **ATP Control** | Use a private group or direct chat — not HILOVIVO3.0. See [ATP_CONTROL_SETUP.md](../ATP_CONTROL_SETUP.md) |
| 6.2 | **Authorization** | Add group/user IDs to `TELEGRAM_AUTH_USER_ID`, `TELEGRAM_CHAT_ID`, or `TELEGRAM_ATP_CONTROL_CHAT_ID` (comma-separated lists supported). See [TELEGRAM_TASK_INTAKE.md](../../runbooks/TELEGRAM_TASK_INTAKE.md) |
| 6.3 | **Bot token** | AWS: `TELEGRAM_BOT_TOKEN` must be set. Local: `TELEGRAM_BOT_TOKEN_DEV` required (or polling is skipped) |
| 6.4 | **Logs** | Check `[TG][CHAT]`, `[TG][AUTH] decision=ALLOW\|DENY`, `[TG][TASK] intake`, `[TG][TASK] notion_create_*` for `/task` |

---

## Summary

- **Pass:** All checked items pass.
- **Fail:** Any unchecked item; document which and re-run or fix manually.
