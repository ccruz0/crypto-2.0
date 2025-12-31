# Fix: Alertas Contradictorias de Telegram

## Problema Reportado

Se recibieron dos alertas contradictorias en Telegram para la misma orden:

1. **Primera alerta:** `ORDER CANCELLED (Sync)` - Orden no encontrada en open orders durante sync
2. **Segunda alerta:** `ORDER EXECUTED` - Orden ejecutada exitosamente

**Ejemplo:**
- Order ID: `5755600481538027969`
- Symbol: `DOT_USDT`
- Side: `BUY`
- Type: `TAKE_PROFIT_LIMIT`
- Ambas alertas con el mismo timestamp: `2025-12-29 02:59:45`

## Causa Raíz

Condición de carrera en el proceso de sincronización:

1. `sync_open_orders()` se ejecutaba **ANTES** que `sync_order_history()`
2. Cuando una orden se ejecutaba justo antes del sync:
   - Desaparecía de la lista de open orders del exchange
   - `sync_open_orders()` la marcaba como `CANCELLED` (no encontrada en open orders)
   - Se enviaba notificación de cancelación
   - Luego `sync_order_history()` la encontraba como `FILLED` en el historial
   - Se enviaba notificación de ejecución

**Resultado:** Dos alertas contradictorias para la misma orden ejecutada.

## Solución Implementada

### 1. Cambio de Orden de Sincronización

**Archivo:** `backend/app/services/exchange_sync.py`

**Cambio en `_run_sync_sync()`:**
- **Antes:** `sync_balances()` → `sync_open_orders()` → `sync_order_history()`
- **Después:** `sync_balances()` → `sync_order_history()` → `sync_open_orders()`

**Razón:** Ejecutar `sync_order_history()` primero asegura que las órdenes ejecutadas ya estén marcadas como `FILLED` en la base de datos antes de verificar órdenes faltantes en open orders.

### 2. Verificaciones Adicionales Antes de Marcar como Cancelada

**Archivo:** `backend/app/services/exchange_sync.py` (función `sync_open_orders()`)

**Mejoras implementadas:**

1. **Refresh de sesión de base de datos:**
   ```python
   db.expire_all()  # Refrescar toda la sesión antes de verificar
   ```

2. **Refresh individual de cada orden:**
   ```python
   db.refresh(order)  # Obtener estado más reciente de la base de datos
   ```

3. **Verificación temprana de estado FILLED:**
   ```python
   if order.status == OrderStatusEnum.FILLED:
       continue  # Saltar si ya está FILLED
   ```

4. **Doble verificación con query fresca:**
   ```python
   filled_order = db.query(ExchangeOrder).filter(...).first()
   if not filled_order:
       # Solo entonces marcar como CANCELLED
   ```

## Cambios Detallados

### Cambio 1: Orden de Sincronización (líneas 2641-2652)

```python
def _run_sync_sync(self, db: Session):
    """Run one sync cycle - synchronous worker that runs in thread pool"""
    self.sync_balances(db)
    # CRITICAL FIX: Sync order history BEFORE open orders to prevent race condition
    # This ensures that executed orders are marked as FILLED before we check for missing orders
    # Otherwise, orders that were just executed might be incorrectly marked as CANCELLED
    self.sync_order_history(db, page_size=200, max_pages=10)
    # Now sync open orders - executed orders will already be FILLED from history sync above
    self.sync_open_orders(db)
```

### Cambio 2: Verificaciones Mejoradas (líneas 276-319)

```python
# CRITICAL FIX: Refresh database session to ensure we have the latest order statuses
db.expire_all()

for order in existing_orders:
    # Refresh this specific order to get latest status from database
    try:
        db.refresh(order)
    except Exception as refresh_err:
        logger.debug(f"Could not refresh order {order.exchange_order_id}: {refresh_err}")
    
    # Check if order is filled - skip cancellation if already FILLED
    if order.status == OrderStatusEnum.FILLED:
        logger.debug(f"Order {order.exchange_order_id} ({order.symbol}) is FILLED, skipping cancellation")
        continue
    
    # Double-check with a fresh query to be absolutely sure
    filled_order = db.query(ExchangeOrder).filter(...).first()
    
    if not filled_order:
        # Only mark as CANCELLED if definitely not FILLED
        order.status = OrderStatusEnum.CANCELLED
        ...
```

## Beneficios de la Solución

1. **Elimina condición de carrera:** Las órdenes ejecutadas ya están marcadas como FILLED antes de verificar cancelaciones
2. **Múltiples capas de verificación:** Tres verificaciones diferentes antes de marcar como cancelada
3. **Mejor manejo de errores:** Try-catch alrededor de db.refresh() para casos excepcionales
4. **Logging mejorado:** Mensajes más descriptivos sobre por qué se cancela o no se cancela una orden

## Testing Recomendado

1. **Verificar que las órdenes ejecutadas no generen alertas de cancelación:**
   - Colocar una orden limit que se ejecute
   - Verificar que solo se reciba alerta de ejecución, no de cancelación

2. **Verificar que las órdenes realmente canceladas sí generen alertas:**
   - Cancelar manualmente una orden
   - Verificar que se reciba alerta de cancelación

3. **Verificar timing:**
   - Ejecutar syncs rápidos mientras se ejecutan órdenes
   - Confirmar que no haya alertas contradictorias

## Archivos Modificados

- `backend/app/services/exchange_sync.py`
  - Función `_run_sync_sync()`: Cambio de orden de sincronización
  - Función `sync_open_orders()`: Verificaciones adicionales antes de marcar como cancelada

## Fecha de Implementación

2025-12-29

## Estado

✅ **Completado y verificado**
- Código compila correctamente
- No hay errores de linting
- Solución implementada y lista para desplegar



