# Telegram Channel Routing (Trading vs Ops)

## Overview

Alertas de Telegram se enrutan a dos canales distintos:

| Canal | Chat | Contenido |
|-------|------|------------|
| **HILOVIVO3.0** (trading) | `TELEGRAM_CHAT_ID` / `TELEGRAM_CHAT_ID_TRADING` | Señales BUY/SELL, órdenes creadas, reportes de ventas, SL/TP |
| **AWS_alerts** (ops) | `TELEGRAM_CHAT_ID_OPS` | Health alerts, anomalías, scheduler inactivity, system down |

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
