# Telegram Channel Routing

## Overview

Four distinct channels. See `docs/audits/TELEGRAM_ROUTING_AUDIT.md` for full audit.

| Canal | Bot | Env Vars | Contenido |
|-------|-----|----------|-----------|
| **ATP Alerts** (trading) | @ATP_ALERTS_bot | TELEGRAM_CHAT_ID_TRADING | Señales BUY/SELL, órdenes, SL/TP, reportes |
| **AWS Alerts** (ops/infra) | @AWS_alerts_hilovivo_bot | TELEGRAM_CHAT_ID_OPS, TELEGRAM_ALERT_* | Health, EC2/Docker, anomalías |
| **ATP Control** (dev/tasks) | @ATP_control_bot | TELEGRAM_ATP_CONTROL_* | Tasks, approvals, investigations |
| **Claw** (commands) | @Claw_cruz_bot | (reply to user) | /task /help, OpenClaw responses |

### /task and OpenClaw (production pitfall)

- **`/task` must be handled by `backend-aws`** (`create_notion_task_from_telegram_direct`). It must **not** go to OpenClaw’s agent, which mounts the ATP repo **read-only** at `~/.openclaw/workspace` and may reply with “edit failed / read-only filesystem”.
- **Cause:** Telegram delivers updates to **one** consumer per bot token. If `backend-aws` polls `TELEGRAM_BOT_TOKEN` (trading bot) while you message **@ATP_control_bot**, the platform never sees `/task`; OpenClaw (or another host) that holds **TELEGRAM_ATP_CONTROL_BOT_TOKEN** may answer instead.
- **Fix (code):** On AWS, `get_telegram_token()` **prefers `TELEGRAM_ATP_CONTROL_BOT_TOKEN` for polling** when set, while `telegram_notifier` still uses `TELEGRAM_BOT_TOKEN` for ATP Alerts / channel posts.
- **Ops:** Ensure **only one** process polls the ATP Control bot. If OpenClaw is registered for the same token (webhook or polling), disable it there or use a **separate** bot for OpenClaw — otherwise expect **409 getUpdates conflict** on the backend.

### OpenClaw on LAB (duplicate consumer)

- **Intended sole poller for `/task` → Notion:** `backend-aws` on PROD with `TELEGRAM_ATP_CONTROL_BOT_TOKEN` and `RUN_TELEGRAM_POLLER=true`.
- **Duplicate source:** OpenClaw on LAB used to load `secrets/runtime.env` (often containing prod `TELEGRAM_*`) and could enable `channels.telegram` with the same token → second `getUpdates` client → 409, stray OpenClaw/read-only messages, extra “Unknown command”.
- **Fix (repo):** `docker-compose.openclaw.yml` sets empty `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ATP_CONTROL_BOT_TOKEN`, and related vars so the OpenClaw container does not see those tokens even if `runtime.env` has them.
- **Fix (LAB state):** Run `scripts/openclaw/disable_openclaw_telegram.sh` (or `disable_openclaw_telegram_via_ssm.sh` from Mac) to set `channels.telegram.enabled: false` in `/opt/openclaw/home-data/openclaw.json` and restart OpenClaw.
- **Re-enable OpenClaw Telegram only** with a **dedicated** LAB bot token — never the PROD ATP Control token while PROD polls it.

## Variables de entorno

```bash
# Trading (HILOVIVO3.0) - señales, órdenes, reportes
TELEGRAM_CHAT_ID=<chat_id_hilovivo3>
# o explícito:
TELEGRAM_CHAT_ID_TRADING=<chat_id_atp_alerts>

# Ops (AWS_alerts) - health, anomalías, servidor
TELEGRAM_CHAT_ID_OPS=<chat_id_aws_alerts>
```

Si `TELEGRAM_CHAT_ID_OPS` no está configurado, las alertas ops van al mismo chat que trading (comportamiento anterior).

## SSM (Producción)

- `/automated-trading-platform/prod/telegram/chat_id` → HILOVIVO3.0 (trading)
- `/automated-trading-platform/prod/telegram/chat_id_ops` → AWS_alerts (ops)

## Scripts de actualización

```bash
# Actualizar canal de trading (HILOVIVO3.0)
TELEGRAM_CHAT_ID=-1001234567890 ./scripts/aws/update_telegram_chat_id.sh

# Actualizar canal ops (AWS_alerts)
TELEGRAM_CHAT_ID_OPS=-1009876543210 ./scripts/aws/update_telegram_chat_id_ops.sh
```

## Obtener Chat IDs

1. Envía un mensaje en el chat destino (HILOVIVO3.0 o AWS_alerts)
2. Ejecuta: `./scripts/diag/run_get_channel_id_prod.sh`
3. Copia el ID del chat que quieras (negativo para canales)
