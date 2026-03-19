# Telegram Routing (ATP Control, Claw, HiloVivo, AWS Alerts)

**Goal:** Zero cross-channel noise. Each channel must be pure.

## Routing (per TELEGRAM_ROUTING_AUDIT.md)

| Destination | Content | Env Vars |
|-------------|---------|----------|
| **ATP Control** (@ATP_control_bot) | Tasks, investigations, approvals, needs revision, agent logs | `TELEGRAM_ATP_CONTROL_BOT_TOKEN`, `TELEGRAM_ATP_CONTROL_CHAT_ID` |
| **Claw** (@Claw_cruz_bot) | Control plane, user commands, /task /help, OpenClaw (responses) | (replies to user chat) |
| **HiloVivo 3.0** (@HILOVIVO30_bot) | Trading alerts (buy/sell), execution, SL/TP, reports | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID_TRADING` |
| **AWS Alerts** (@AWS_alerts_hilovivo_bot) | EC2/Docker, health, anomalies, scheduler down | `TELEGRAM_CHAT_ID_OPS`, `TELEGRAM_ALERT_*` |

## Message Tags

All Claw messages are prefixed with:
- `[TASK]` — approvals, stuck tasks, daily summary
- `[INVESTIGATION]` — investigation complete, OpenClaw reports
- `[PATCH]` — deploy approval, needs-revision
- `[ERROR]` — Notion degraded, validation failed, manual attention

## Configuration

```bash
# ATP Control (task-system channel) - preferred
# Set TELEGRAM_ATP_CONTROL_BOT_TOKEN and TELEGRAM_ATP_CONTROL_CHAT_ID in env

# Fallback: TELEGRAM_CLAW_BOT_TOKEN, TELEGRAM_CLAW_CHAT_ID
```

**Important:** Approval callbacks (Approve/Deny) are sent to the same bot that delivered the approval message. Set `TELEGRAM_ATP_CONTROL_*` to ATP Control for task approvals; the poller must receive updates from that bot.

## Sources Routed to ATP Control (via claw_telegram)

| Module | Message Type |
|--------|--------------|
| agent_telegram_approval | TASK, INVESTIGATION, PATCH |
| notion_env | TASK, ERROR |
| agent_task_executor | ERROR |
| agent_anomaly_detector | TASK |
| agent_telegram_policy | TASK |
| task_health_monitor | TASK, ERROR |

## Structured Logs

```
[TELEGRAM_ROUTE] category=DEV destination=ATP_CONTROL bot=ATP_control_bot message_type=TASK source_module=agent_telegram_approval sent=True message_id=123
```

## Validation

1. Create a task → message appears in ATP Control
2. Investigation update → appears in ATP Control
3. Needs revision / recovery → appears in ATP Control
4. Buy/sell alert → appears ONLY in HiloVivo 3.0
5. No task-related message should appear in HiloVivo 3.0
