# Por qué la orden de compra no se ejecutó automáticamente

## Problema

La alerta simulada de SOL_USDT se envió a Telegram, pero **NO se creó la orden automáticamente**.

## Causa

El endpoint `/test/simulate-alert` **solo envía la alerta de Telegram**, pero **NO crea la orden**. Según el código:

```python
# NOTE: For now, we'll skip the actual order creation in the simulate endpoint
# to avoid event loop conflicts. The alert will still be sent to Telegram.
# Order creation should be handled by the signal_monitor service in the background.
```

## Cómo funciona la creación automática de órdenes

Las órdenes se crean automáticamente por el servicio `signal_monitor` cuando:

1. **Detecta una señal BUY REAL** (no simulada)
2. **El símbolo está en la watchlist** con:
   - `trade_enabled = true` ✅
   - `trade_amount_usd > 0` ✅
   - `alert_enabled = true` (opcional, para alertas)

## Verificar estado de SOL_USDT

Ejecuta este script para verificar el estado:

```bash
docker compose exec backend-aws python3 /app/tools/check_sol_status.py
```

O revisa directamente en la base de datos:

```sql
SELECT 
    symbol,
    trade_enabled,
    alert_enabled,
    trade_amount_usd,
    trade_on_margin
FROM watchlist_items
WHERE symbol = 'SOL_USDT';
```

## Soluciones

### Opción 1: Configurar SOL_USDT en la watchlist

1. Ve al Dashboard
2. Añade SOL_USDT a la Watchlist (si no está)
3. Configura:
   - **Trade:** YES ✅
   - **Amount USD:** > 0 (ej: 100) ✅
   - **Alert:** YES (opcional)

4. Espera a que el servicio `signal_monitor` detecte una señal BUY real

### Opción 2: Crear orden manualmente (inmediato)

Usa el endpoint de referencia manual que documentamos:

```bash
curl -X POST http://localhost:8002/manual-trade/confirm \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "SOL_USDT",
    "side": "BUY",
    "quantity": 0.595,
    "price": 168.09,
    "sl_percentage": 3.0,
    "tp_percentage": 3.0,
    "sl_tp_mode": "conservative"
  }'
```

Esto creará:
- ✅ Orden BUY LIMIT
- ✅ Orden STOP_LOSS automática
- ✅ Orden TAKE_PROFIT automática

Y podrás ver los logs de referencia con los payloads exactos.

### Opción 3: Modificar el endpoint de simulación

Si quieres que el endpoint `/test/simulate-alert` cree órdenes directamente, necesitarías modificar el código para que llame a `_create_buy_order` directamente en lugar de depender del `signal_monitor`.

## Verificar que el servicio signal_monitor está corriendo

```bash
# Ver logs del servicio
docker compose logs backend-aws 2>&1 | grep "signal_monitor" | tail -20

# Ver si está procesando SOL_USDT
docker compose logs backend-aws 2>&1 | grep "SOL_USDT" | tail -20
```

## Resumen

- ✅ La alerta se envió correctamente a Telegram
- ❌ La orden NO se creó porque el endpoint de simulación solo envía alertas
- ✅ Para crear órdenes automáticamente: configura SOL_USDT en watchlist con `trade_enabled=true` y `trade_amount_usd>0`
- ✅ Para crear orden inmediatamente: usa el endpoint `/manual-trade/confirm`

