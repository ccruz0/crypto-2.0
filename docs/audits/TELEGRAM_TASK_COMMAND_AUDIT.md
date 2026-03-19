# Telegram /task Command Audit — ATP Control vs ATP Control Alerts

## Executive Summary

This audit identifies all Telegram bots, tokens, routes, and code paths that can process `/task` in ATP. It standardizes the behavior and adds logging for troubleshooting.

**Key findings:**
- **Single poller**: Only `backend-aws` polls Telegram (process_telegram_commands → get_telegram_updates).
- **Single /task path**: `/task` is handled exclusively by `_handle_task_command()` in `telegram_commands.py`.
- **ATP Control vs ATP Control Alerts**: Same channel. "ATP Control Alerts" is the channel name; @ATP_control_bot is the bot. Both refer to the same destination.
- **ATP Alerts** (TELEGRAM_CHAT_ID_TRADING): Different channel — alerts-only. Commands are rejected with a clear message.
- **Old "low impact" message**: Not in current source. Stale deployed code. Deploy current codebase to fix.

---

## 1. Bot/Token/Handler Inventory

### 1.1 ATP Control (Command Channel)

| Attribute | Value |
|-----------|-------|
| **Bot** | @ATP_control_bot |
| **Token env var** | TELEGRAM_ATP_CONTROL_BOT_TOKEN |
| **Fallback token** | TELEGRAM_CLAW_BOT_TOKEN → TELEGRAM_BOT_TOKEN |
| **Chat ID env var** | TELEGRAM_ATP_CONTROL_CHAT_ID |
| **Runtime/container** | backend-aws (Docker Compose profile `aws`) |
| **Polling** | process_telegram_commands() in scheduler.py |
| **Supports /task** | Yes |

### 1.2 ATP Control Alerts (Same as ATP Control)

| Attribute | Value |
|-----------|-------|
| **Bot** | @ATP_control_bot |
| **Channel name** | "ATP Control Alerts" |
| **Note** | Same bot and channel as ATP Control. The channel is named "ATP Control Alerts" in Telegram. |

### 1.3 ATP Alerts (Trading Alerts Only)

| Attribute | Value |
|-----------|-------|
| **Bot** | @HILOVIVO30_bot |
| **Token env var** | TELEGRAM_BOT_TOKEN (used for sending alerts) |
| **Chat ID env var** | TELEGRAM_CHAT_ID_TRADING |
| **Runtime/container** | backend-aws (sends via telegram_notifier) |
| **Receives commands** | No — alerts-only. Commands are rejected. |
| **Supports /task** | No |

### 1.4 AWS Alerts (Infra Only)

| Attribute | Value |
|-----------|-------|
| **Bot** | @AWS_alerts_hilovivo_bot |
| **Token env var** | TELEGRAM_ALERT_BOT_TOKEN |
| **Chat ID env var** | TELEGRAM_ALERT_CHAT_ID / TELEGRAM_CHAT_ID_OPS |
| **Runtime/container** | infra/telegram_helper, scripts |
| **Receives commands** | No — send-only |

### 1.5 Claw (Control Plane)

| Attribute | Value |
|-----------|-------|
| **Bot** | @Claw_cruz_bot |
| **Token env var** | TELEGRAM_CLAW_BOT_TOKEN |
| **Fallback** | Used when TELEGRAM_ATP_CONTROL_BOT_TOKEN not set |
| **Note** | When Claw chat_id = ATP Control, same channel can receive both. |

---

## 2. Polling / Webhook Paths

| Path | Service | Token source | Used for /task? |
|------|---------|--------------|-----------------|
| `get_telegram_updates()` | backend-aws | get_telegram_token() | Yes |
| `process_telegram_commands()` | scheduler (backend-aws) | Same | Yes |
| `handle_telegram_update()` | telegram_commands | Same | Yes |
| Webhook | None (deleted on startup) | N/A | No |

**Token source priority (get_telegram_token):**
1. TELEGRAM_BOT_TOKEN
2. TELEGRAM_BOT_TOKEN_DEV
3. TELEGRAM_ATP_CONTROL_BOT_TOKEN
4. TELEGRAM_CLAW_BOT_TOKEN
5. Interactive popup

---

## 3. Code Paths for /task

| File | Function | Role |
|------|----------|------|
| `telegram_commands.py` | `handle_telegram_update()` | Routes text to handler |
| `telegram_commands.py` | Router (lines ~5280–5315) | Matches `/task` → handler_name="task" |
| `telegram_commands.py` | `_handle_task_command()` | Canonical handler |

**agent_telegram_commands.py** does NOT handle `/task`. It handles `/investigate` and `/agent` only.

---

## 4. Old "Low Impact" Message

**Exact text:** `"This task has low impact and was not created"`

**Source:** Not in current source. The task_compiler was updated to never reject creation; low-impact tasks are created with status=backlog and priority=low.

**If still seen in production:**
- Stale deployed code (old version of task_compiler that had a rejection path)
- Deploy current codebase to fix

**Reference:** `docs/runbooks/TASK_IMPACT_CLASSIFIER_FIX.md`, `docs/runbooks/TELEGRAM_TASK_FLOW_FIX_REPORT.md`

---

## 5. ATP Control vs ATP Control Alerts — Architecture

| Question | Answer |
|----------|--------|
| **Separate bot?** | No. Same bot: @ATP_control_bot |
| **Separate token?** | No. Same token: TELEGRAM_ATP_CONTROL_BOT_TOKEN |
| **Separate runtime/container?** | No. Same backend-aws |
| **Separate command handler?** | No. Same telegram_commands.py |

**ATP Control** and **ATP Control Alerts** refer to the same channel. The channel is named "ATP Control Alerts" in Telegram. Commands are authorized via TELEGRAM_ATP_CONTROL_CHAT_ID.

**Different behaviors observed** (unknown command vs low-impact message) can be caused by:
1. **Duplicate pollers** — Two processes polling with same token; one has old code. See `docs/runbooks/DUPLICATE_TELEGRAM_POLLERS_FIX.md`.
2. **Stale deployment** — Old container image still running.

---

## 6. Standardization Changes

### 6.1 /task Only in ATP Control

- **ATP Control** (TELEGRAM_ATP_CONTROL_CHAT_ID): Full support for `/task`.
- **ATP Alerts** (TELEGRAM_CHAT_ID_TRADING): Rejects with: "ATP Alerts is alerts-only. Use ATP Control for /task commands."

### 6.2 Single Canonical Handler

`_handle_task_command()` in `telegram_commands.py` is the only handler. No other code path processes `/task`.

### 6.3 Logging Added

| Log prefix | Fields |
|------------|--------|
| `[TG][UPDATE]` | update_id, chat_id, update_type, token_source |
| `[TG][ROUTER]` | selected_handler, text_lower, cmd_lower, update_id, chat_id, token_source |
| `[TG][TASK]` | handler=task path=_handle_task_command update_id, chat_id, token_source |
| `[TG][TASK][DEBUG]` | raw_text, normalized_cmd, handler, update_id, chat_id, token_source |

`token_source` = `get_telegram_token_source()` → TELEGRAM_BOT_TOKEN | TELEGRAM_BOT_TOKEN_DEV | TELEGRAM_ATP_CONTROL_BOT_TOKEN | TELEGRAM_CLAW_BOT_TOKEN | interactive_prompt

---

## 7. Final Matrix

| Bot/Chat name | Token/env var | Runtime/container | Supports /task? | Current behavior | Fixed behavior |
|---------------|---------------|-------------------|-----------------|------------------|----------------|
| **ATP Control** | TELEGRAM_ATP_CONTROL_BOT_TOKEN (or TELEGRAM_CLAW_BOT_TOKEN, TELEGRAM_BOT_TOKEN) | backend-aws | Yes | Canonical _handle_task_command | Same; logging added |
| **ATP Control Alerts** | Same as ATP Control | Same | Yes | Same as ATP Control | Same; logging added |
| **ATP Alerts** | TELEGRAM_BOT_TOKEN (used for sending) | backend-aws | No | Auth deny | "ATP Alerts is alerts-only. Use ATP Control for /task commands." |
| **AWS Alerts** | TELEGRAM_ALERT_BOT_TOKEN | infra scripts | No | No command handling | N/A |
| **Claw** | TELEGRAM_CLAW_BOT_TOKEN | Same as ATP Control when fallback | Yes (when same channel) | Same as ATP Control | Same |

---

## 8. Verification

1. **Single poller:** `docker compose --profile aws logs backend-aws --tail=100 | grep "Telegram poller started"`
2. **No duplicate pollers:** `RUN_TELEGRAM_POLLER=false` on canary.
3. **Token source:** `TELEGRAM_ATP_CONTROL_BOT_TOKEN` or `TELEGRAM_BOT_TOKEN` in secrets/runtime.env.
4. **Send /task in ATP Control:** Should see `[TG][TASK] handler=task path=_handle_task_command` and `[TG][TASK][DEBUG]` in logs.
5. **Send /task in ATP Alerts:** Should see `[TG][AUTH][DENY]` and "Use ATP Control for /task commands."

### 8.1 Logs to Check

```bash
# Bot identity and routing
grep "\[TG\]\[UPDATE\]" logs/*.log
grep "\[TG\]\[ROUTER\]" logs/*.log
grep "\[TG\]\[TASK\]" logs/*.log
grep "token_source=" logs/*.log
```

## 9. Files Changed

- `backend/app/utils/telegram_token_loader.py` — Added `get_telegram_token_source()`
- `backend/app/services/telegram_commands.py` — Added `[TG][UPDATE]`, `[TG][ROUTER]`, `[TG][TASK]` logging with token_source; updated ATP Alerts deny message
