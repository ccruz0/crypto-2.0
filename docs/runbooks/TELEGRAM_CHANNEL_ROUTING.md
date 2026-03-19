# Telegram Channel Routing

## Overview

Four distinct channels. See `docs/audits/TELEGRAM_ROUTING_AUDIT.md` for full audit.

| Canal | Bot | Env Vars | Contenido |
|-------|-----|----------|-----------|
| **HiloVivo 3.0** (trading) | @HILOVIVO30_bot | TELEGRAM_CHAT_ID_TRADING | Señales BUY/SELL, órdenes, SL/TP, reportes |
| **AWS Alerts** (ops/infra) | @AWS_alerts_hilovivo_bot | TELEGRAM_CHAT_ID_OPS, TELEGRAM_ALERT_* | Health, EC2/Docker, anomalías |
| **ATP Control** (dev/tasks) | @ATP_control_bot | TELEGRAM_ATP_CONTROL_* | Tasks, approvals, investigations |
| **Claw** (commands) | @Claw_cruz_bot | (reply to user) | /task /help, OpenClaw responses |

## Variables de entorno

```bash
# Trading (HILOVIVO3.0) - señales, órdenes, reportes
TELEGRAM_CHAT_ID=<chat_id_hilovivo3>
# o explícito:
TELEGRAM_CHAT_ID_TRADING=<chat_id_hilovivo3>

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
