# Monitoreo Activo de Alertas y Decision Tracing

## 🔍 Sistema de Monitoreo Configurado

**Fecha de inicio:** 2026-01-09  
**Status:** ✅ Activo

### Qué se monitorea:

1. **Nuevas alertas** (BUY/SELL SIGNAL)
2. **Decision tracing** cuando órdenes no se crean
3. **Órdenes creadas** vs alertas enviadas
4. **Razones de bloqueo** (decision_type, reason_code, reason_message)

### Frecuencia de verificación:
- Cada 30 segundos
- Últimos 3 minutos de actividad

## 📊 Estado Actual

### ALGO_USDT:
- ✅ `force_next_signal = TRUE` (scalp:conservative)
- ✅ `trade_enabled = TRUE`
- ✅ `alert_enabled = TRUE`
- ⏳ Esperando RSI < 40 para señal BUY

### Otros símbolos:
- Monitoreando todos los símbolos activos
- Verificando decision tracing para cada alerta

## 🎯 Qué Buscar

Cuando se dispare una alerta, el sistema verificará:

### ✅ Si la alerta se disparó:
- Mensaje en `telegram_messages` con `BUY SIGNAL` o `SELL SIGNAL`

### ✅ Si la orden NO se creó:
- **DEBE tener:**
  - `decision_type = SKIPPED` o `FAILED`
  - `reason_code` (ej: `MAX_OPEN_TRADES_REACHED`, `GUARDRAIL_BLOCKED`, etc.)
  - `reason_message` explicativo
  - `context_json` con detalles

### ✅ Si la orden se creó:
- Registro en `exchange_orders` con `created_at` reciente

## 🔧 Scripts Disponibles

### Monitoreo continuo:
```bash
./scripts/monitor_alerts_continuous.sh
```

### Trigger manual:
```bash
./scripts/trigger_manual_alert_simple.sh SYMBOL SIDE
```

### Verificación directa:
```sql
SELECT id, symbol, blocked, decision_type, reason_code, reason_message
FROM telegram_messages
WHERE timestamp >= NOW() - INTERVAL '5 minutes'
    AND (message LIKE '%BUY SIGNAL%' OR message LIKE '%TRADE BLOCKED%')
ORDER BY timestamp DESC;
```

## 📈 Próximos Eventos Esperados

1. **Alerta automática** cuando RSI < 40 para ALGO_USDT
2. **Decision tracing** si la orden no se crea
3. **Verificación** de que el fix funciona correctamente

## ✅ Sistema Listo

- ✅ Fix del fallback decision tracing desplegado
- ✅ Scripts de monitoreo creados
- ✅ Monitoreo activo
- ✅ Esperando próxima alerta

---

**Status:** 🔍 Monitoreo activo  
**Última actualización:** 2026-01-09

