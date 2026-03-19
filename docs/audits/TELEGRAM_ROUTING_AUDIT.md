# Telegram Routing Audit

**Date:** 2025-03-19  
**Status:** Completed

## Bot Inventory (DO NOT CREATE NEW BOTS)

| Bot | Handle | Purpose |
|-----|--------|---------|
| ATP Control | @ATP_control_bot | development, code, tasks, investigations, approvals, needs revision, agent logs, orchestration |
| AWS Alerts | @AWS_alerts_hilovivo_bot | EC2/server, Docker/containers, health checks, auto-healing, infrastructure ONLY |
| Claw | @Claw_cruz_bot | control plane, user commands, /task /help, OpenClaw interaction, trigger system actions |
| HiloVivo 3.0 | @HILOVIVO30_bot | live trading, buy/sell alerts, SL/TP, execution errors, exchange responses, real money |

## Expected Routing

| Category | Destination | Env Vars |
|----------|--------------|----------|
| DEVELOPMENT | ATP Control | TELEGRAM_ATP_CONTROL_BOT_TOKEN, TELEGRAM_ATP_CONTROL_CHAT_ID |
| INFRA | AWS Alerts | TELEGRAM_ALERT_BOT_TOKEN, TELEGRAM_ALERT_CHAT_ID (or TELEGRAM_CHAT_ID_OPS) |
| CONTROL | Claw | (responses to user commands; chat_id from update) |
| TRADING | HiloVivo 3.0 | TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID_TRADING |

## Current Routing Map (Post-Fix)

### Module → Bot → Chat

| Module | Message Type | Category | Bot Used | Chat ID | Status |
|--------|--------------|----------|----------|---------|--------|
| **claw_telegram** | TASK, INVESTIGATION, PATCH, ERROR | DEV | ATP Control | TELEGRAM_ATP_CONTROL_CHAT_ID | ✅ Fixed |
| **telegram_notifier** (chat_destination=trading) | BUY/SELL, orders, SL/TP, reports | TRADING | HiloVivo 3.0 | TELEGRAM_CHAT_ID_TRADING | ✅ Correct |
| **telegram_notifier** (chat_destination=ops) | System alerts, stale data, scheduler down | INFRA | AWS Alerts | TELEGRAM_CHAT_ID_OPS | ✅ Correct |
| **infra/telegram_helper** | EC2/Docker health | INFRA | AWS Alerts | TELEGRAM_ALERT_* or TELEGRAM_CHAT_ID_OPS | ✅ Fixed |
| **scripts/aws/observability/telegram-alerts** | Prometheus/Alertmanager | INFRA | AWS Alerts | TELEGRAM_ALERT_* | ✅ Correct |

### Senders by Module

| Module | Sends | Destination |
|--------|-------|-------------|
| agent_telegram_approval | Task approvals, patch approvals | ATP Control (claw_telegram) |
| agent_telegram_policy | Task policy messages | ATP Control (claw_telegram) |
| agent_anomaly_detector | Anomaly alerts | ATP Control (claw_telegram) |
| agent_task_executor | Error messages | ATP Control (claw_telegram) |
| task_health_monitor | Stuck tasks, errors | ATP Control (claw_telegram) |
| notion_env | Notion errors, recovery | ATP Control (claw_telegram) |
| system_alerts | Stale data, stalled scheduler, market down | AWS Alerts (telegram_notifier ops) |
| signal_monitor | BUY/SELL signals, order created | HiloVivo 3.0 (telegram_notifier trading) |
| exchange_sync | Executed order, SL/TP, errors | HiloVivo 3.0 (telegram_notifier trading) |
| daily_summary | Daily/sell reports | HiloVivo 3.0 (telegram_notifier trading) |
| sl_tp_checker | SL/TP reminders | HiloVivo 3.0 (telegram_notifier trading) |
| tp_sl_order_creator | SL/TP creation | HiloVivo 3.0 (telegram_notifier trading) |
| scheduler | Hourly SL/TP check | HiloVivo 3.0 (telegram_notifier trading) |
| crypto_com_trade | Order failed, blocked | HiloVivo 3.0 (telegram_notifier trading) |
| infra/monitor_health | EC2/Docker health | AWS Alerts (telegram_helper) |
| scripts/aws/observability/telegram-alerts | Prometheus alerts | AWS Alerts |

## Mismatches Fixed

1. **claw_telegram → ATP Control**: Added TELEGRAM_ATP_CONTROL_BOT_TOKEN and TELEGRAM_ATP_CONTROL_CHAT_ID. Task/approval messages now route to ATP Control. Fallback to TELEGRAM_CLAW_* for backward compatibility.

2. **infra/telegram_helper → AWS Alerts**: Now prefers TELEGRAM_ALERT_BOT_TOKEN + TELEGRAM_ALERT_CHAT_ID (same as Alertmanager). Fallback to TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID_OPS.

3. **system_alerts.py**: Fixed indentation bug in _send_system_alert().

## Env Vars Reference

```bash
# ATP Control (@ATP_control_bot) - tasks, approvals, investigations
# Set TELEGRAM_ATP_CONTROL_BOT_TOKEN and TELEGRAM_ATP_CONTROL_CHAT_ID in env

# Fallback (backward compat): TELEGRAM_CLAW_BOT_TOKEN, TELEGRAM_CLAW_CHAT_ID

# HiloVivo 3.0 - trading: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID_TRADING

# AWS Alerts - infra: TELEGRAM_CHAT_ID_OPS, TELEGRAM_ALERT_BOT_TOKEN, TELEGRAM_ALERT_CHAT_ID
```

## Structured Logging

Every message logs:

```
[TELEGRAM_ROUTE] category=DEV|INFRA|TRADING destination=ATP_CONTROL|AWS_ALERTS|HILOVIVO30 ...
```

- **claw_telegram**: `[TELEGRAM_ROUTE] category=DEV destination=ATP_CONTROL bot=ATP_control_bot message_type=TASK source_module=...`
- **telegram_notifier**: `[TELEGRAM_ROUTE] category=TRADING|INFRA destination=HILOVIVO30|AWS_alerts ...`
- **infra/telegram_helper**: `[TELEGRAM_ROUTE] category=INFRA destination=AWS_ALERTS ...`

## Validation Scenarios

| Scenario | Expected Channel | Verify |
|----------|------------------|--------|
| Task investigation complete | ATP Control | `[TELEGRAM_ROUTE] category=DEV destination=ATP_CONTROL` |
| Approval / needs revision | ATP Control | `[TELEGRAM_ROUTE] category=DEV destination=ATP_CONTROL` |
| EC2/Docker failure | AWS Alerts | `[TELEGRAM_ROUTE] category=INFRA destination=AWS_ALERTS` |
| /task command response | Claw (reply to user) | Handled by telegram_commands reply flow |
| Buy/sell alert | HiloVivo 3.0 | `[TELEGRAM_ROUTE] category=TRADING destination=HILOVIVO30` |

## Files Modified

- `backend/app/core/config.py` - Added TELEGRAM_ATP_CONTROL_*
- `backend/app/services/claw_telegram.py` - Prefer ATP Control, add structured logging
- `backend/app/services/system_alerts.py` - Fix _send_system_alert indentation
- `backend/app/services/telegram_notifier.py` - Add [TELEGRAM_ROUTE] logging
- `infra/telegram_helper.py` - Route to AWS Alerts, add structured logging
- `ops/inventory_env_vars.py` - Document new env vars

## Missing Config Checklist

- [ ] Set TELEGRAM_ATP_CONTROL_BOT_TOKEN and TELEGRAM_ATP_CONTROL_CHAT_ID for task/approval messages
- [ ] Set TELEGRAM_ALERT_BOT_TOKEN and TELEGRAM_ALERT_CHAT_ID for infra scripts (or use TELEGRAM_CHAT_ID_OPS)
- [ ] Ensure TELEGRAM_CHAT_ID_TRADING = HiloVivo 3.0 channel
- [ ] Ensure TELEGRAM_CHAT_ID_OPS = AWS Alerts channel
