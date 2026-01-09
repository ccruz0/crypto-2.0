# Decision Tracing Test Summary

## ✅ Trabajo Completado

### 1. Fix del Fallback Decision Tracing
- **Problema:** El fallback decision tracing no se ejecutaba porque estaba en el bloque incorrecto
- **Fix:** Movido `else` a `if not should_create_order:` al mismo nivel que `if should_create_order:`
- **Commit:** `8803491` - "fix: Move fallback decision tracing to correct level"
- **Status:** ✅ Desplegado

### 2. Scripts de Monitoreo Creados
- **trigger_manual_alert_simple.sh:** Script bash para disparar alertas manualmente
- **trigger_manual_alert.py:** Script Python más completo
- **MANUAL_ALERT_TRIGGER_GUIDE.md:** Guía completa de uso
- **Status:** ✅ Listos para usar

### 3. Fix de Mensajes Duplicados
- **Problema:** Mensajes duplicados sin decision tracing
- **Fix:** Eliminadas llamadas duplicadas a `add_telegram_message`
- **Commit:** `e901319` - "fix: Remove duplicate messages and add decision tracing for trade_disabled"
- **Status:** ✅ Desplegado

## 🔍 Estado Actual del Sistema

### Configuración ALGO_USDT:
- ✅ `trade_enabled = TRUE`
- ✅ `alert_enabled = TRUE`
- ✅ `buy_alert_enabled = TRUE`
- ✅ `force_next_signal = TRUE` (scalp:conservative)
- ⚠️ **RSI = 52.1** (necesita < 40 para BUY)

### Por qué no se disparó la alerta:
- `force_next_signal` solo bypass el throttle, **NO fuerza condiciones de señal**
- RSI = 52.1 > 40 (condición no cumplida)
- El sistema está funcionando correctamente - esperando condiciones adecuadas

## 📊 Cómo Verificar Decision Tracing

Cuando se dispare la próxima alerta (automática o manual), verifica:

```sql
SELECT 
    id,
    symbol,
    LEFT(message, 100) as msg_preview,
    blocked,
    order_skipped,
    decision_type,
    reason_code,
    LEFT(reason_message, 80) as reason_preview,
    context_json,
    timestamp
FROM telegram_messages
WHERE symbol = 'ALGO_USDT'
    AND timestamp >= NOW() - INTERVAL '5 minutes'
    AND (
        message LIKE '%BUY SIGNAL%' 
        OR message LIKE '%TRADE BLOCKED%'
    )
ORDER BY timestamp DESC;
```

### Qué buscar:

1. **Si alerta se disparó pero orden NO se creó:**
   - ✅ `decision_type = SKIPPED` o `FAILED`
   - ✅ `reason_code` (ej: `MAX_OPEN_TRADES_REACHED`, `GUARDRAIL_BLOCKED`, etc.)
   - ✅ `reason_message` explicativo
   - ✅ `context_json` con detalles

2. **Si orden se creó:**
   - ✅ Registro en `exchange_orders` con `created_at` reciente

## 🎯 Próximos Pasos

### Opción 1: Esperar Alerta Natural
- El sistema disparará automáticamente cuando RSI < 40
- `force_next_signal` ya está configurado (bypass throttle activo)
- **Ventaja:** Condiciones reales, test más auténtico

### Opción 2: Forzar Señal (Requiere Configuración)
Para forzar completamente una señal:
1. Agregar `DIAG_SYMBOL=ALGO_USDT` y `DIAG_FORCE_SIGNAL_BUY=1` al `.env` o `docker-compose.yml`
2. Reiniciar servicio
3. Esperar ciclo de monitoreo

### Opción 3: Usar Otro Símbolo
Buscar símbolo con RSI < 40 para probar inmediatamente.

## ✅ Sistema Listo

El sistema está **completamente listo** para:
1. ✅ Disparar alertas cuando condiciones se cumplan
2. ✅ Registrar decision tracing cuando órdenes no se crean
3. ✅ Mostrar razones en Monitor UI
4. ✅ Monitorear alertas en tiempo real

**El fix del fallback está desplegado y funcionará cuando se dispare la próxima alerta.**

---

**Status:** ✅ Sistema listo, esperando condiciones de señal  
**Fecha:** 2026-01-09  
**Próxima acción:** Monitorear próxima alerta para verificar decision tracing

