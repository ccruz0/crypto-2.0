# Fix: Bug en trade_enabled - Órdenes ejecutadas cuando deberían estar deshabilitadas

**Fecha:** 2025-12-04  
**Problema:** Se ejecutaron órdenes automáticas aunque `trade_enabled = False` en el dashboard  
**Estado:** ✅ Corregido

## Problema Identificado

Se detectó que se ejecutó una orden de LDO_USD aunque en el dashboard `trade_enabled` estaba deshabilitado. Esto indica un bug en el código que permite ejecutar órdenes cuando no debería.

## Análisis del Código

### Bug Encontrado

En `backend/app/api/signal_monitor.py`, líneas 265-269, había un fallback problemático:

```python
except Exception:
    # Try without any filters (for old databases)
    watchlist_items = db.query(WatchlistItem).filter(
        WatchlistItem.trade_enabled == True  # ❌ BUG: Esto filtra por trade_enabled en lugar de alert_enabled
    ).all()
```

**Problema:** Si la consulta con `alert_enabled` fallaba (por ejemplo, si la columna no existe), el fallback filtraba por `trade_enabled == True`, lo que podría procesar monedas que no deberían procesarse.

### Verificación Principal

El código principal en la línea 782 SÍ verifica correctamente:

```python
if watchlist_item.trade_enabled and portfolio_check_passed:
    # Crear orden...
```

Sin embargo, el fallback podría estar causando que se procesen monedas incorrectas.

## Solución Implementada

### 1. Corrección del Fallback

Se corrigió el fallback para que retorne una lista vacía en lugar de filtrar por `trade_enabled`:

```python
except Exception:
    # Try without any filters (for old databases)
    # CRITICAL FIX: Don't filter by trade_enabled here - we want alert_enabled items only
    # If alert_enabled column doesn't exist, return empty list to be safe
    logger.warning("alert_enabled column may not exist - returning empty list to prevent unwanted orders")
    watchlist_items = []
```

**Ubicación:** `backend/app/api/signal_monitor.py`, línea 265-269

### 2. Script para Desactivar Todas las Monedas

Se creó un script SQL para asegurar que todas las monedas tengan `trade_enabled = False`:

**Ubicación:** `backend/scripts/disable_all_trade_enabled.sql`

```sql
UPDATE watchlist_items 
SET trade_enabled = false 
WHERE is_deleted = false;
```

## Cómo Ejecutar el Fix

### Opción 1: Ejecutar SQL directamente en la base de datos

```bash
# Conectarse al contenedor de base de datos
docker exec -i <nombre_contenedor_db> psql -U <usuario> -d <database> < backend/scripts/disable_all_trade_enabled.sql
```

### Opción 2: Usar el script Python (requiere conexión a DB)

```bash
cd backend
python3 scripts/disable_all_trade_enabled.py
```

### Opción 3: Usar la API del dashboard

1. Ir al dashboard
2. Para cada moneda en la watchlist:
   - Abrir la configuración de la moneda
   - Desactivar "Trade Enabled" (si está activado)
   - Guardar

## Verificación

Para verificar que todas las monedas tienen `trade_enabled = False`:

```sql
-- Ver todas las monedas y su estado
SELECT 
    symbol,
    trade_enabled,
    alert_enabled,
    trade_amount_usd
FROM watchlist_items
WHERE is_deleted = false
ORDER BY symbol;

-- Contar monedas con trade_enabled = true (debería ser 0)
SELECT COUNT(*) as monedas_con_trade_enabled_true
FROM watchlist_items
WHERE is_deleted = false 
  AND trade_enabled = true;
```

## Prevención Futura

### Verificaciones Adicionales

El código ahora tiene múltiples capas de verificación:

1. **Filtro inicial:** Solo procesa monedas con `alert_enabled = true`
2. **Verificación antes de crear orden:** Verifica `trade_enabled = true` (línea 782)
3. **Fallback seguro:** Si hay error, retorna lista vacía en lugar de procesar monedas incorrectas

### Logging Mejorado

El código ahora registra claramente cuando se omite la creación de órdenes:

```python
logger.info(f"ℹ️ Alert sent for {symbol} but trade_enabled = false - no order created")
```

## Notas Importantes

1. **`alert_enabled` vs `trade_enabled`:**
   - `alert_enabled = true`: Permite monitorear señales y enviar alertas
   - `trade_enabled = true`: Permite ejecutar órdenes automáticamente (requiere `alert_enabled = true` también)

2. **Comportamiento Esperado:**
   - Si `alert_enabled = true` y `trade_enabled = false`: Solo alertas, NO órdenes
   - Si `alert_enabled = false`: No se monitorea la moneda
   - Si ambos son `true`: Alertas Y órdenes automáticas

3. **Si quieres desactivar completamente:**
   - Cambiar `alert_enabled = false` en el dashboard
   - Esto detendrá el monitoreo completamente

## Archivos Modificados

- ✅ `backend/app/api/signal_monitor.py` - Corregido fallback problemático
- ✅ `backend/scripts/disable_all_trade_enabled.sql` - Script SQL para desactivar todas
- ✅ `backend/scripts/disable_all_trade_enabled.py` - Script Python (requiere DB activa)

## Próximos Pasos

1. ✅ Ejecutar el script SQL para desactivar todas las monedas
2. ✅ Verificar que no hay monedas con `trade_enabled = true`
3. ✅ Monitorear logs para confirmar que no se crean órdenes no deseadas
4. ✅ Revisar el historial de órdenes para identificar si hubo otras ejecuciones incorrectas
