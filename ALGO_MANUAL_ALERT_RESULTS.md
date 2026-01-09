# Resultados: Alerta Manual ALGO_USDT

## Estado Actual

**Fecha:** 2026-01-09 10:17  
**Símbolo:** ALGO_USDT  
**Side:** BUY

### Configuración:
- ✅ `trade_enabled = TRUE`
- ✅ `alert_enabled = TRUE`
- ✅ `buy_alert_enabled = TRUE`
- ✅ `trade_amount_usd = 10`
- ✅ `force_next_signal = TRUE` (scalp:conservative)

### Indicadores Actuales:
- **RSI:** 52.1
- **MA50:** 0.14
- **MA10w:** 0.14
- **Volume ratio:** 0.38x

## Problema Identificado

**RSI = 52.1 está por encima del umbral de compra**

Para estrategias conservadoras (scalp:conservative), el RSI debe ser **< 40** para disparar una señal BUY.

### Por qué no se disparó la alerta:

1. ✅ `force_next_signal = TRUE` está configurado (bypass throttle)
2. ❌ **RSI = 52.1 > 40** (condición de señal NO cumplida)
3. ❌ `force_next_signal` solo bypass el throttle, **NO fuerza las condiciones de señal**

## Soluciones

### Opción 1: Esperar a que RSI baje (< 40)
- El sistema disparará automáticamente cuando RSI < 40
- `force_next_signal` ya está configurado, así que no habrá throttle

### Opción 2: Forzar señal completamente (usando variables de entorno)
Para forzar una señal incluso si RSI no está en rango, necesitas:

```bash
# En el contenedor market-updater-aws
export DIAG_SYMBOL=ALGO_USDT
export DIAG_FORCE_SIGNAL_BUY=1
```

Esto forzará `buy_signal=True` independientemente del RSI.

### Opción 3: Usar otro símbolo con RSI < 40
Buscar un símbolo que tenga RSI < 40 para probar el decision tracing.

## Verificación de Decision Tracing

Cuando se dispare una alerta (ya sea automática o forzada), verifica:

```sql
SELECT 
    id,
    symbol,
    LEFT(message, 100) as msg,
    blocked,
    order_skipped,
    decision_type,
    reason_code,
    reason_message,
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

1. **Si la alerta se disparó pero orden NO se creó:**
   - ✅ Debe tener `decision_type = SKIPPED` o `FAILED`
   - ✅ Debe tener `reason_code` (ej: `MAX_OPEN_TRADES_REACHED`, `GUARDRAIL_BLOCKED`, etc.)
   - ✅ Debe tener `reason_message` explicativo
   - ✅ Debe tener `context_json` con detalles

2. **Si la orden se creó:**
   - ✅ Registro en `exchange_orders` con `created_at` reciente

## Próximos Pasos

1. **Monitorear** cuando RSI baje a < 40 (se disparará automáticamente)
2. **O forzar** usando `DIAG_FORCE_SIGNAL_BUY=1` para probar inmediatamente
3. **O usar** otro símbolo con RSI < 40

---

**Status:** ⏳ Esperando condiciones de señal (RSI < 40)  
**force_next_signal:** ✅ Configurado (bypass throttle activo)  
**Fecha:** 2026-01-09

