# Comparación de Signal Enable: Frontend vs Backend

## 📊 Resumen Ejecutivo

**Problema principal**: La base de datos **NO tiene las columnas** `alert_enabled`, `buy_alert_enabled`, `sell_alert_enabled`, pero tanto el frontend como el backend intentan usarlas.

## 🔍 Estado Actual de la Base de Datos

### Columnas que SÍ existen:
- ✅ `trade_enabled` (Boolean)
- ✅ `is_deleted` (Boolean)
- ✅ `trade_amount_usd` (Float)
- ✅ `trade_on_margin` (Boolean)
- ✅ Todas las demás columnas de watchlist_items

### Columnas que NO existen (pero se usan en el código):
- ❌ `alert_enabled` (Boolean) - **FALTA**
- ❌ `buy_alert_enabled` (Boolean) - **FALTA**
- ❌ `sell_alert_enabled` (Boolean) - **FALTA**

## 🎨 Frontend (dashboard)

### Campos usados:
1. **`alert_enabled`** - Master switch para alertas
2. **`buy_alert_enabled`** - Habilitar alertas BUY
3. **`sell_alert_enabled`** - Habilitar alertas SELL
4. **`trade_enabled`** - Habilitar trading automático

### Funciones de actualización:
- `updateWatchlistAlert(symbol, alertEnabled)` → `PUT /watchlist/{symbol}/alert`
- `updateBuyAlert(symbol, buyAlertEnabled)` → `PUT /watchlist/{symbol}/buy-alert`
- `updateSellAlert(symbol, sellAlertEnabled)` → `PUT /watchlist/{symbol}/sell-alert`
- `saveCoinSettings(symbol, settings)` → `PUT /dashboard/{item_id}` (incluye `trade_enabled`)

### Lógica del frontend:
- Cuando se activa `alert_enabled`, también se activan `buy_alert_enabled` y `sell_alert_enabled`
- Los campos se persisten en `localStorage` para optimismo UI
- El frontend espera recibir estos campos en las respuestas del backend

## 🔧 Backend

### Modelo (`app/models/watchlist.py`):
```python
alert_enabled = Column(Boolean, default=False)  # Master switch
buy_alert_enabled = Column(Boolean, default=False)  # Enable BUY alerts
sell_alert_enabled = Column(Boolean, default=False)  # Enable SELL alerts
trade_enabled = Column(Boolean, default=False)
```

### Endpoints que usan estos campos:

1. **`PUT /watchlist/{symbol}/alert`** (`routes_market.py:1266`)
   - Intenta actualizar `alert_enabled`, `buy_alert_enabled`, `sell_alert_enabled`
   - **FALLA** porque las columnas no existen en la DB

2. **`PUT /watchlist/{symbol}/buy-alert`** (`routes_market.py:1374`)
   - Intenta actualizar `buy_alert_enabled` y `alert_enabled`
   - **FALLA** porque las columnas no existen en la DB

3. **`PUT /watchlist/{symbol}/sell-alert`** (`routes_market.py:1554`)
   - Intenta actualizar `sell_alert_enabled` y `alert_enabled`
   - **FALLA** porque las columnas no existen en la DB

4. **`PUT /dashboard/{item_id}`** (`routes_dashboard.py:1323`)
   - Maneja `trade_enabled` correctamente (columna existe)
   - Intenta manejar `alert_enabled`, `buy_alert_enabled`, `sell_alert_enabled` pero falla silenciosamente

### Signal Monitor (`app/services/signal_monitor.py`):
- **ANTES**: Intentaba consultar `alert_enabled == True` → **FALLABA**
- **AHORA**: Usa `trade_enabled == True` como fallback (funciona, pero no es lo ideal)

## ⚠️ Problemas Identificados

### 1. Inconsistencia Modelo vs Base de Datos
- El modelo SQLAlchemy define columnas que no existen en la base de datos
- Esto causa errores `no such column: watchlist_items.alert_enabled` en todas las consultas

### 2. Endpoints Rotos
- Los endpoints `/watchlist/{symbol}/alert`, `/watchlist/{symbol}/buy-alert`, `/watchlist/{symbol}/sell-alert` fallan silenciosamente
- El frontend cree que actualizó los valores, pero en realidad no se guardaron

### 3. Signal Monitor no funciona correctamente
- No puede consultar por `alert_enabled` porque la columna no existe
- Usa `trade_enabled` como fallback, pero esto mezcla dos conceptos diferentes:
  - `trade_enabled` = Habilitar trading automático (crear órdenes)
  - `alert_enabled` = Habilitar alertas (enviar notificaciones)

### 4. Lógica de Negocio Confusa
- El backend intenta usar `alert_enabled` como master switch para alertas
- Pero la base de datos solo tiene `trade_enabled`
- El código intenta derivar `alert_enabled` de `buy_alert_enabled` y `sell_alert_enabled`, pero estas columnas tampoco existen

## ✅ Soluciones Recomendadas

### Opción 1: Agregar las columnas faltantes (RECOMENDADO)
```sql
ALTER TABLE watchlist_items ADD COLUMN alert_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE watchlist_items ADD COLUMN buy_alert_enabled BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE watchlist_items ADD COLUMN sell_alert_enabled BOOLEAN NOT NULL DEFAULT FALSE;
```

**Ventajas**:
- Alinea el modelo con la base de datos
- Permite separar alertas de trading (puedes tener alertas sin trading)
- Corrige todos los endpoints que ya están implementados

### Opción 2: Usar solo `trade_enabled` (TEMPORAL)
- Simplificar la lógica para usar solo `trade_enabled`
- Modificar el frontend para que solo use `trade_enabled`
- **Desventaja**: No se pueden tener alertas sin trading

### Opción 3: Migración gradual
1. Agregar las columnas con valores por defecto basados en `trade_enabled`
2. Migrar los datos existentes
3. Mantener compatibilidad con código que usa `trade_enabled`

## 📝 Archivos Afectados

### Backend:
- `backend/app/models/watchlist.py` - Modelo define columnas que no existen
- `backend/app/api/routes_market.py` - Endpoints que fallan al actualizar columnas faltantes
- `backend/app/api/routes_dashboard.py` - Maneja `trade_enabled` pero intenta usar `alert_enabled`
- `backend/app/services/signal_monitor.py` - Ya corregido para usar fallback

### Frontend:
- `frontend/src/lib/api.ts` - Funciones que llaman a endpoints rotos
- `frontend/src/app/page.tsx` - UI que muestra y actualiza estos campos

## 🚀 Acción Inmediata Requerida

**Para que UNI funcione correctamente**:
1. Ejecutar la migración para agregar las columnas faltantes
2. O modificar el código para usar solo `trade_enabled` (solución temporal)

**Estado actual**: El sistema usa `trade_enabled` como workaround, pero esto mezcla dos conceptos diferentes y puede causar confusión.







