# Explicación: Por qué no se creó SL/TP automáticamente

**Fecha:** 2025-12-04  
**Problema:** Orden automática ejecutada pero SL/TP no se creó  
**Estado:** ✅ Explicado

## Análisis de la Orden de LDO_USD

Según `orders_history.csv`, la orden más reciente de LDO_USD fue:

```
Order ID: 5755600476554550077
Fecha: 2025-10-31 00:01:07.241 UTC
Tipo: MARKET
Side: BUY
Cantidad: 11902.4
Precio promedio: 0.8402
Total: 9999.98 USD
Estado: CANCELED ⚠️
```

## Razón Principal: Orden CANCELED (no FILLED)

El sistema **solo crea SL/TP automáticamente cuando una orden está FILLED** (ejecutada completamente).

### Condiciones para Crear SL/TP Automáticamente

El código en `backend/app/services/exchange_sync.py` crea SL/TP cuando:

1. ✅ **Tipo de orden**: LIMIT o MARKET
2. ✅ **Estado**: FILLED (ejecutada completamente)
3. ✅ **No es orden SL/TP**: No es STOP_LIMIT o TAKE_PROFIT_LIMIT
4. ✅ **No existe SL/TP previo**: No hay SL/TP ya creados para esta orden

### Código Relevante

```python
# Línea 1782-1796 en exchange_sync.py
if order_type in ['LIMIT', 'MARKET']:
    # Try to create SL/TP automatically
    logger.info(f"Creating SL/TP for new main order {order_id}: side={side}, order_type={order_type}")
    try:
        self._create_sl_tp_for_filled_order(
            db=db,
            symbol=symbol,
            side=side,
            filled_price=order_price_float,
            filled_qty=executed_qty,
            order_id=order_id
        )
    except Exception as sl_tp_err:
        logger.warning(f"Error creating SL/TP for order {order_id}: {sl_tp_err}")
```

**Importante:** Esta función solo se llama cuando `exchange_sync` detecta una orden **FILLED** en el historial de órdenes.

## Por qué la Orden fue CANCELED

Las órdenes pueden ser canceladas por varias razones:

1. **Condiciones de mercado cambiaron** antes de ejecutarse
2. **Límites de la exchange** (liquidez insuficiente, límites de precio, etc.)
3. **Problemas técnicos** en la exchange
4. **Cancelación manual** (aunque en este caso fue automática)
5. **Timeouts** de la orden

## Flujo Normal vs. Flujo Real

### Flujo Normal (Orden FILLED):
```
1. SignalMonitor detecta señal BUY
2. Crea orden MARKET/LIMIT automáticamente
3. Orden se ejecuta → Estado: FILLED
4. exchange_sync detecta orden FILLED
5. Llama a _create_sl_tp_for_filled_order()
6. Crea órdenes SL y TP automáticamente
7. Envía notificación Telegram
```

### Flujo Real (Orden CANCELED):
```
1. SignalMonitor detecta señal BUY
2. Crea orden MARKET automáticamente
3. Orden se cancela → Estado: CANCELED ❌
4. exchange_sync detecta orden CANCELED
5. NO crea SL/TP (solo se crea para órdenes FILLED)
6. No hay notificación de SL/TP
```

## Verificación

Para verificar si hay órdenes FILLED sin SL/TP:

```sql
-- Buscar órdenes BUY FILLED sin SL/TP
SELECT 
    eo.exchange_order_id,
    eo.symbol,
    eo.side,
    eo.order_type,
    eo.status,
    eo.price,
    eo.quantity,
    eo.exchange_create_time,
    COUNT(sl_tp.exchange_order_id) as sl_tp_count
FROM exchange_orders eo
LEFT JOIN exchange_orders sl_tp ON (
    sl_tp.parent_order_id = eo.exchange_order_id
    AND sl_tp.order_role IN ('STOP_LOSS', 'TAKE_PROFIT')
)
WHERE eo.side = 'BUY'
  AND eo.status = 'FILLED'
  AND eo.order_type IN ('LIMIT', 'MARKET')
  AND eo.order_role IS NULL  -- No es SL/TP
GROUP BY eo.exchange_order_id
HAVING COUNT(sl_tp.exchange_order_id) = 0
ORDER BY eo.exchange_create_time DESC;
```

## Soluciones

### Opción 1: Crear SL/TP Manualmente

Si la orden fue FILLED pero no se creó SL/TP automáticamente:

1. **Usar el endpoint de la API:**
   ```bash
   POST /api/orders/create-sl-tp/{order_id}
   ```

2. **Desde el Dashboard:**
   - Ir a "Executed Orders"
   - Buscar la orden FILLED
   - Hacer clic en "Create SL/TP"

### Opción 2: Verificar Logs

Revisar logs para ver si hubo errores al crear SL/TP:

```bash
grep -i "sl.*tp\|create.*sl\|error.*sl" logs/app.log | tail -50
```

### Opción 3: Verificar Configuración

Asegurarse de que la moneda tiene configuración de SL/TP:

```sql
SELECT 
    symbol,
    sl_tp_mode,
    sl_percentage,
    tp_percentage,
    atr
FROM watchlist_items
WHERE symbol = 'LDO_USD'
  AND is_deleted = false;
```

## Prevención

Para evitar que esto suceda en el futuro:

1. **Monitorear órdenes CANCELED**: Revisar periódicamente órdenes canceladas
2. **Verificar SL/TP después de órdenes FILLED**: Usar el script de verificación
3. **Configurar alertas**: El sistema `SLTPCheckerService` puede detectar posiciones sin SL/TP

## Notas Importantes

- ✅ El sistema **SÍ crea SL/TP automáticamente** para órdenes FILLED
- ❌ El sistema **NO crea SL/TP** para órdenes CANCELED
- ⚠️ Si una orden fue FILLED pero no se creó SL/TP, puede ser un bug o un error en la creación

## Archivos Relevantes

- `backend/app/services/exchange_sync.py` - Lógica de creación automática de SL/TP
- `backend/app/services/exchange_sync.py::_create_sl_tp_for_filled_order()` - Función que crea SL/TP
- `backend/app/services/sl_tp_checker.py` - Servicio que verifica posiciones sin SL/TP
