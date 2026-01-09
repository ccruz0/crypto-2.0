# Guía para Disparar Alertas Manualmente y Verificar Decision Tracing

## Método 1: Usando el Script Simple (Recomendado)

### Uso:
```bash
./scripts/trigger_manual_alert_simple.sh SYMBOL SIDE
```

### Ejemplo:
```bash
./scripts/trigger_manual_alert_simple.sh ALGO_USDT BUY
./scripts/trigger_manual_alert_simple.sh ETH_USDT SELL
```

### Qué hace el script:
1. ✅ Establece `force_next_signal=True` en la base de datos
2. ⏳ Espera 30 segundos para el próximo ciclo de monitoreo
3. 🔍 Verifica si se disparó una alerta
4. 📊 Muestra el decision tracing (si existe)
5. ✅ Verifica si se creó una orden

## Método 2: Manualmente con SQL

### Paso 1: Establecer force_next_signal
```sql
UPDATE signal_throttle_states 
SET force_next_signal = TRUE 
WHERE symbol = 'ALGO_USDT' 
    AND side = 'BUY' 
    AND strategy_key = 'scalp:conservative';
```

### Paso 2: Verificar que se estableció
```sql
SELECT symbol, side, strategy_key, force_next_signal, last_time 
FROM signal_throttle_states 
WHERE symbol = 'ALGO_USDT' AND side = 'BUY';
```

### Paso 3: Esperar el próximo ciclo de monitoreo (30-60 segundos)

### Paso 4: Verificar alertas y decision tracing
```sql
SELECT 
    id,
    symbol,
    LEFT(message, 80) as msg_preview,
    blocked,
    order_skipped,
    decision_type,
    reason_code,
    LEFT(reason_message, 60) as reason_preview,
    context_json,
    timestamp
FROM telegram_messages
WHERE symbol = 'ALGO_USDT'
    AND timestamp >= NOW() - INTERVAL '5 minutes'
    AND (
        message LIKE '%BUY SIGNAL%' 
        OR message LIKE '%SELL SIGNAL%'
        OR message LIKE '%TRADE BLOCKED%'
        OR message LIKE '%ORDER BLOCKED%'
    )
ORDER BY timestamp DESC
LIMIT 10;
```

### Paso 5: Verificar si se creó una orden
```sql
SELECT 
    exchange_order_id,
    symbol,
    side,
    status,
    price,
    quantity,
    created_at
FROM exchange_orders
WHERE symbol = 'ALGO_USDT'
    AND created_at >= NOW() - INTERVAL '5 minutes'
    AND side = 'BUY'
ORDER BY created_at DESC
LIMIT 1;
```

## Qué Verificar

### ✅ Si la alerta se disparó:
1. **Mensaje de alerta** en `telegram_messages` con `message LIKE '%BUY SIGNAL%'` o `'%SELL SIGNAL%'`
2. **Decision tracing** (si la orden no se creó):
   - `decision_type`: `SKIPPED` o `FAILED`
   - `reason_code`: Código de razón (ej: `MAX_OPEN_TRADES_REACHED`, `RECENT_ORDERS_COOLDOWN`, `GUARDRAIL_BLOCKED`, etc.)
   - `reason_message`: Mensaje explicativo
   - `context_json`: Contexto adicional (JSON)

### ✅ Si la orden se creó:
- Registro en `exchange_orders` con `created_at` reciente
- `status` puede ser `NEW`, `ACTIVE`, `FILLED`, etc.

### ❌ Si no se disparó la alerta:
**Posibles razones:**
1. **RSI no está en rango**: Para BUY, RSI debe ser < 40 (para estrategias conservadoras)
2. **alert_enabled=False**: Verificar en `watchlist_items`
3. **Condiciones de señal no cumplidas**: MA checks, volume, etc.
4. **Ciclo de monitoreo aún no corrió**: Esperar más tiempo (hasta 3 minutos)

## Verificar Condiciones de Señal

Para verificar por qué no se dispara una señal:

```sql
-- Ver configuración del símbolo
SELECT 
    symbol,
    trade_enabled,
    alert_enabled,
    buy_alert_enabled,
    sell_alert_enabled,
    trade_amount_usd,
    sl_tp_mode,
    preset
FROM watchlist_items
WHERE symbol = 'ALGO_USDT'
    AND trade_enabled = TRUE
LIMIT 1;
```

```bash
# Ver logs recientes del símbolo
docker compose --profile aws logs --tail 1000 market-updater-aws 2>&1 | grep -i 'ALGO.*RSI\|ALGO.*signal\|ALGO.*should_trigger'
```

## Ejemplo Completo

```bash
# 1. Disparar alerta manualmente
./scripts/trigger_manual_alert_simple.sh ALGO_USDT BUY

# 2. Si no aparece, verificar condiciones
docker compose --profile aws exec -T -e PGPASSWORD=traderpass db psql -U trader -d atp -c "
SELECT symbol, trade_enabled, alert_enabled, buy_alert_enabled 
FROM watchlist_items 
WHERE symbol = 'ALGO_USDT' AND trade_enabled = TRUE;
"

# 3. Ver logs para entender por qué no se disparó
docker compose --profile aws logs --tail 500 market-updater-aws 2>&1 | grep -i 'ALGO'
```

## Notas Importantes

1. **force_next_signal** solo bypass el throttle, NO fuerza las condiciones de señal (RSI, MA, etc.)
2. Si las condiciones de señal no se cumplen, la alerta NO se disparará aunque `force_next_signal=True`
3. El ciclo de monitoreo corre cada ~3 minutos, así que puede tomar tiempo
4. Para forzar una señal completamente, necesitarías usar variables de entorno como `DIAG_FORCE_SIGNAL_BUY=1` y `DIAG_SYMBOL=ALGO_USDT`

## Troubleshooting

### Problema: No se dispara la alerta
**Solución:**
1. Verificar `alert_enabled=True` o `buy_alert_enabled=True`
2. Verificar RSI está en rango (< 40 para BUY en estrategias conservadoras)
3. Verificar logs para ver qué condiciones fallan
4. Esperar más tiempo (hasta 3 minutos)

### Problema: Alerta se dispara pero no hay decision tracing
**Solución:**
1. Verificar que el fix del fallback está desplegado (commit 8803491)
2. Verificar logs para ver si el fallback se ejecutó
3. Verificar que `should_create_order=False` fue establecido

### Problema: Alerta se dispara pero orden no se crea sin razón
**Solución:**
1. Verificar decision tracing en `telegram_messages`
2. Buscar mensajes con `blocked=True` o `order_skipped=True`
3. Verificar `decision_type` y `reason_code`

---

**Fecha:** 2026-01-09  
**Status:** ✅ Scripts creados y listos para usar

