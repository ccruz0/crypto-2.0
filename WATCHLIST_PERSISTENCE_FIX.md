# Fix: Watchlist Values Not Persisting

## Problema
Los valores de la watchlist (Amount USD, SL Price, TP Price) no se guardaban correctamente y desaparecían después de refrescar la página o reconstruir el backend.

## Causas Identificadas y Correcciones

### 1. Frontend: Auto-recalculo Sobrescribiendo Valores Manuales ✅
**Problema:** El código recalculaba y guardaba SL/TP prices cada 3 segundos, sobrescribiendo valores manuales.

**Archivo:** `frontend/src/app/page.tsx`
- **Líneas ~6010-6045:** Agregada verificación para omitir recálculo si el usuario ha establecido porcentajes manuales
- **Líneas ~6057-6104:** Misma protección en el efecto de señales
- **Líneas ~6129-6161:** Protección en la carga inicial de valores

**Cambio:**
```typescript
// Ahora verifica si hay porcentajes manuales antes de recalcular
const hasManualSLPercent = coinSLPercent[symbolKey] && coinSLPercent[symbolKey] !== '';
const hasManualTPPercent = coinTPPercent[symbolKey] && coinTPPercent[symbolKey] !== '';

if (!hasManualSLPercent && !hasManualTPPercent && hasSignal) {
  // Solo recalcula si no hay valores manuales
}
```

### 2. Backend: exchange_sync Sobrescribiendo SL/TP Prices ✅
**Problema:** `exchange_sync.py` actualizaba `sl_price`/`tp_price` durante la creación de órdenes, ignorando valores manuales.

**Archivo:** `backend/app/services/exchange_sync.py`
- **Líneas ~969-980:** Agregada verificación para preservar valores cuando hay porcentajes manuales

**Cambio:**
```python
# Solo actualiza precios si el usuario no ha establecido porcentajes manuales
user_has_manual_sl = watchlist_item.sl_percentage is not None and watchlist_item.sl_percentage != 0
user_has_manual_tp = watchlist_item.tp_percentage is not None and watchlist_item.tp_percentage != 0

if not user_has_manual_sl:
    watchlist_item.sl_price = sl_price
if not user_has_manual_tp:
    watchlist_item.tp_price = tp_price
```

### 3. Backend: signal_monitor Sobrescribiendo trade_amount_usd ✅
**Problema:** `signal_monitor.py` actualizaba `trade_amount_usd` durante refrescos, sobrescribiendo valores del usuario.

**Archivo:** `backend/app/services/signal_monitor.py`
- **Líneas ~680-692:** Preserva valores existentes si el usuario ya los ha establecido
- **Líneas ~2089-2091:** Misma protección en verificación de órdenes
- **Líneas ~2415-2417:** Misma protección en última verificación

**Cambio:**
```python
# Solo actualiza si el valor actual es None/0 (usuario no lo ha establecido)
if trade_amount_usd is not None and trade_amount_usd != 0:
    if watchlist_item.trade_amount_usd is None or watchlist_item.trade_amount_usd == 0:
        watchlist_item.trade_amount_usd = trade_amount_usd
    # De lo contrario, preserva el valor del usuario
```

### 4. Backend: Protección Contra Valores None ✅
**Problema:** Si el frontend enviaba `None` para un campo, se borraban valores existentes.

**Archivo:** `backend/app/api/routes_dashboard.py`
- **Líneas ~987-1012:** Agregada protección para preservar valores cuando el nuevo valor es `None`

**Cambio:**
```python
# Protege valores establecidos por el usuario de ser sobrescritos con None
user_set_fields = {"trade_amount_usd", "sl_percentage", "tp_percentage", "sl_price", "tp_price"}
if field in user_set_fields and new_value is None and old_value is not None:
    # Solo permite borrar si el valor anterior es 0 (no un valor real del usuario)
    if old_value != 0 and old_value != 0.0:
        log.info(f"[WATCHLIST_PROTECT] Preserving user-set {field}={old_value}")
        continue  # Omite esta actualización
```

### 5. Frontend: Mapeo Correcto de Campos ✅
**Problema:** `sl_price`/`tp_price` se mapeaban incorrectamente a `stop_loss`/`take_profit`.

**Archivo:** `frontend/src/app/api.ts`
- **Líneas ~571-583:** Corregido mapeo para actualizar ambos campos (nuevo y legacy)

**Cambio:**
```typescript
// Ahora actualiza ambos campos para compatibilidad
if (settings.sl_price !== undefined) {
  watchlistUpdate.sl_price = settings.sl_price;
  watchlistUpdate.stop_loss = settings.sl_price; // Backward compatibility
}
```

### 6. Logging Mejorado ✅
**Archivo:** `backend/app/api/routes_dashboard.py`
- **Líneas ~1279-1287:** Agregado logging detallado para rastrear cambios

**Logs agregados:**
- `[WATCHLIST_UPDATE]` - Registra intentos de actualización
- `[WATCHLIST_PROTECT]` - Registra cuando se preservan valores del usuario

## Archivos Modificados

1. ✅ `frontend/src/app/page.tsx` - Lógica de auto-recalculo
2. ✅ `backend/app/services/exchange_sync.py` - Preservación de valores SL/TP
3. ✅ `backend/app/services/signal_monitor.py` - Preservación de trade_amount_usd
4. ✅ `frontend/src/app/api.ts` - Mapeo de campos
5. ✅ `backend/app/api/routes_dashboard.py` - Protección contra None y logging

## Cómo Verificar que Funciona

### 1. Reiniciar el Backend
```bash
# Reinicia el backend para aplicar los cambios
cd backend
# O si usas Docker:
docker-compose restart backend
```

### 2. Probar Persistencia
1. **Establecer valores:**
   - Abre el dashboard
   - Cambia "Amount USD" para un símbolo (ej: 100)
   - Cambia "SL Price" o "TP Price" (o sus porcentajes)
   - Espera a ver el mensaje "✓ New value saved"

2. **Refrescar la página:**
   - Presiona F5 o recarga la página
   - Los valores deben persistir

3. **Reiniciar el backend:**
   - Reinicia el servicio backend
   - Los valores deben persistir en la base de datos

### 3. Revisar Logs
Busca en los logs del backend:
```bash
# Buscar actualizaciones de watchlist
grep "WATCHLIST_UPDATE" backend/logs/*.log

# Buscar protección de valores
grep "WATCHLIST_PROTECT" backend/logs/*.log
```

## Si los Valores Aún Desaparecen

Si después de aplicar estos cambios los valores aún desaparecen, verifica:

### 1. Base de Datos se Está Reinicializando
- ¿Hay algún script que ejecute `DROP TABLE` o `TRUNCATE`?
- ¿La base de datos se está recreando desde cero?
- Revisa scripts de migración o inicialización

### 2. Proceso de Backup/Restore
- ¿Hay algún proceso que esté restaurando la base de datos desde un backup?
- Verifica `aws_database_backup.py` y procesos de sincronización

### 3. Múltiples Instancias del Backend
- ¿Hay múltiples instancias del backend corriendo?
- Una instancia podría estar sobrescribiendo cambios de otra
- Verifica que solo una instancia esté escribiendo a la base de datos

### 4. Verificar Base de Datos Directamente
```sql
-- Conecta a la base de datos y verifica los valores
SELECT symbol, trade_amount_usd, sl_percentage, tp_percentage, sl_price, tp_price 
FROM watchlist_items 
WHERE symbol = 'BTC_USDT';
```

## Notas Adicionales

- Los valores se guardan en la base de datos PostgreSQL/SQLite
- El frontend también guarda en `localStorage` como respaldo temporal
- Los valores en la base de datos tienen prioridad sobre `localStorage`
- Si el backend se reconstruye pero la base de datos persiste, los valores deberían mantenerse

## Próximos Pasos

1. ✅ Aplicar todos los cambios
2. ✅ Reiniciar el backend
3. ✅ Probar estableciendo valores y refrescando
4. ✅ Monitorear logs para verificar que los valores se están guardando
5. ⚠️ Si el problema persiste, verificar procesos de base de datos

