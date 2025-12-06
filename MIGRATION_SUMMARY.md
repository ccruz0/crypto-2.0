# ✅ Migración de Google Sheets a Base de Datos - Completada

## 📋 Resumen

Se ha completado exitosamente la migración del sistema de Google Sheets a una arquitectura basada en PostgreSQL. El dashboard ahora obtiene todos los datos desde la base de datos y el exchange (Crypto.com) directamente.

## 🎯 Cambios Implementados

### 1. Nuevos Modelos de Base de Datos

✅ **`TradeSignal`** (`backend/app/models/trade_signal.py`)
   - Reemplaza completamente la hoja de Google Sheets
   - Almacena señales de trading con todos los indicadores técnicos
   - Campos: symbol, preset, sl_profile, rsi, ma50, ma200, ema10, ma10w, atr, resistance_up/down, current_price, volume_24h, volume_ratio, should_trade, status, exchange_order_id

✅ **`ExchangeBalance`** (`backend/app/models/exchange_balance.py`)
   - Almacena balances del exchange (Crypto.com)
   - Campos: asset, free, locked, total

✅ **`ExchangeOrder`** (`backend/app/models/exchange_order.py`)
   - Almacena órdenes del exchange
   - Campos: exchange_order_id, symbol, side, status, price, quantity, etc.

### 2. Servicio de Sincronización Automática

✅ **`ExchangeSyncService`** (`backend/app/services/exchange_sync.py`)
   - Se ejecuta automáticamente cada 5 segundos
   - Sincroniza:
     - `get_account_summary()` → actualiza `exchange_balances`
     - `get_open_orders()` → actualiza `exchange_orders`
     - `get_order_history()` → actualiza órdenes ejecutadas (cada 50 segundos)
   - Actualiza automáticamente el estado de `trade_signals` cuando se vinculan con órdenes

### 3. Endpoint Unificado del Dashboard

✅ **`GET /api/dashboard/state`** (`backend/app/api/routes_dashboard.py`)
   - Devuelve TODO el estado del dashboard en una sola respuesta:
     ```json
     {
       "balances": [...],           // Balances del exchange
       "fast_signals": [...],        // Señales activas (should_trade=true o order_placed/filled)
       "slow_signals": [...],       // Resto de señales
       "open_orders": [...],        // Órdenes abiertas
       "last_sync": "2025-10-31T..." // Timestamp de última sincronización
     }
     ```

### 4. Servicios de Escritura

✅ **`SignalWriter`** (`backend/app/services/signal_writer.py`)
   - `upsert_trade_signal()`: Escribe/actualiza señales en la DB
   - `sync_watchlist_to_signals()`: Migra datos existentes de watchlist a señales

### 5. Frontend Actualizado

✅ **Nueva función API** (`frontend/src/lib/api.ts`)
   - `getDashboardState()`: Función para obtener el estado completo del dashboard
   - Tipos TypeScript definidos: `DashboardState`, `DashboardSignal`, `DashboardBalance`, `DashboardOrder`

## 🚀 Próximos Pasos para Usar

### 1. Las Tablas se Crean Automáticamente

Las tablas se crearán automáticamente cuando el backend inicie (ya configurado en `main.py` con `Base.metadata.create_all(bind=engine)`).

Para verificar que las tablas se crearon correctamente:

```bash
# Conectarse a la base de datos dentro del contenedor Docker
docker compose exec db psql -U trader -d atp -c "\dt"

# Deberías ver:
# - trade_signals
# - exchange_balances  
# - exchange_orders
```

### 2. Usar el Nuevo Endpoint en el Frontend

El frontend ahora puede usar:

```typescript
import { getDashboardState } from '@/lib/api';

const state = await getDashboardState();

// state.balances - Balances del exchange
// state.fast_signals - Señales que requieren refresco rápido (3-5s)
// state.slow_signals - Señales que requieren refresco lento (60s)
// state.open_orders - Órdenes abiertas
// state.last_sync - Última sincronización
```

### 3. Escribir Señales desde el Código

Cuando se calculen señales (por ejemplo, en `routes_signals.py`), usa:

```python
from app.services.signal_writer import upsert_trade_signal
from app.database import get_db

db = next(get_db())
upsert_trade_signal(
    db=db,
    symbol="BTC_USDT",
    preset="swing",
    sl_profile="conservative",
    rsi=35.5,
    ma50=45000,
    ema10=45200,
    current_price=45100,
    should_trade=True,
    status="pending"
)
```

### 4. El Servicio de Sincronización Ya Está Corriendo

El servicio de sincronización se inicia automáticamente cuando el backend arranca. Los datos se actualizan automáticamente cada 5 segundos.

Para verificar que está funcionando:

```bash
# Ver logs del backend
docker compose logs -f backend

# Deberías ver mensajes como:
# "Exchange sync service started"
# "Synced X account balances"
# "Synced X open orders"
```

## ✨ Ventajas de la Nueva Arquitectura

1. **⚡ Rendimiento**: La DB es mucho más rápida que leer Google Sheets
2. **🔄 Sincronización en tiempo real**: Datos del exchange actualizados cada 5 segundos
3. **📈 Escalabilidad**: Puede manejar muchas más señales y órdenes
4. **📊 Trazabilidad**: Historial completo de señales y órdenes
5. **🔗 Integración**: Más fácil integrar con otros servicios y APIs
6. **🎯 Endpoint único**: Una sola llamada obtiene todo el estado del dashboard

## 📝 Notas Importantes

- El servicio de sincronización se ejecuta en segundo plano automáticamente
- Las señales con `should_trade=true` o estado `order_placed`/`filled` se consideran "fast" y deberían refrescarse frecuentemente (3-5s)
- Las demás señales son "slow" y pueden refrescarse cada minuto
- Las órdenes del exchange se sincronizan automáticamente y actualizan el estado de las señales vinculadas

## 🔧 Archivos Creados/Modificados

**Nuevos modelos:**
- `backend/app/models/trade_signal.py`
- `backend/app/models/exchange_balance.py`
- `backend/app/models/exchange_order.py`

**Nuevos servicios:**
- `backend/app/services/exchange_sync.py`
- `backend/app/services/signal_writer.py`

**Nuevo endpoint:**
- `backend/app/api/routes_dashboard.py`

**Scripts:**
- `backend/scripts/create_tables.py` (las tablas se crean automáticamente)

**Documentación:**
- `backend/README_MIGRATION.md`
- `MIGRATION_SUMMARY.md` (este archivo)

**Modificaciones:**
- `backend/app/main.py`: Inicio automático del servicio de sincronización
- `backend/app/models/__init__.py`: Exportación de nuevos modelos
- `frontend/src/lib/api.ts`: Nueva función `getDashboardState()` y tipos TypeScript

## ✅ Estado Final

Todo está listo para usar. El backend ya está sincronizando datos del exchange automáticamente y el endpoint `/api/dashboard/state` está disponible para que el frontend lo consuma.


## 📋 Resumen

Se ha completado exitosamente la migración del sistema de Google Sheets a una arquitectura basada en PostgreSQL. El dashboard ahora obtiene todos los datos desde la base de datos y el exchange (Crypto.com) directamente.

## 🎯 Cambios Implementados

### 1. Nuevos Modelos de Base de Datos

✅ **`TradeSignal`** (`backend/app/models/trade_signal.py`)
   - Reemplaza completamente la hoja de Google Sheets
   - Almacena señales de trading con todos los indicadores técnicos
   - Campos: symbol, preset, sl_profile, rsi, ma50, ma200, ema10, ma10w, atr, resistance_up/down, current_price, volume_24h, volume_ratio, should_trade, status, exchange_order_id

✅ **`ExchangeBalance`** (`backend/app/models/exchange_balance.py`)
   - Almacena balances del exchange (Crypto.com)
   - Campos: asset, free, locked, total

✅ **`ExchangeOrder`** (`backend/app/models/exchange_order.py`)
   - Almacena órdenes del exchange
   - Campos: exchange_order_id, symbol, side, status, price, quantity, etc.

### 2. Servicio de Sincronización Automática

✅ **`ExchangeSyncService`** (`backend/app/services/exchange_sync.py`)
   - Se ejecuta automáticamente cada 5 segundos
   - Sincroniza:
     - `get_account_summary()` → actualiza `exchange_balances`
     - `get_open_orders()` → actualiza `exchange_orders`
     - `get_order_history()` → actualiza órdenes ejecutadas (cada 50 segundos)
   - Actualiza automáticamente el estado de `trade_signals` cuando se vinculan con órdenes

### 3. Endpoint Unificado del Dashboard

✅ **`GET /api/dashboard/state`** (`backend/app/api/routes_dashboard.py`)
   - Devuelve TODO el estado del dashboard en una sola respuesta:
     ```json
     {
       "balances": [...],           // Balances del exchange
       "fast_signals": [...],        // Señales activas (should_trade=true o order_placed/filled)
       "slow_signals": [...],       // Resto de señales
       "open_orders": [...],        // Órdenes abiertas
       "last_sync": "2025-10-31T..." // Timestamp de última sincronización
     }
     ```

### 4. Servicios de Escritura

✅ **`SignalWriter`** (`backend/app/services/signal_writer.py`)
   - `upsert_trade_signal()`: Escribe/actualiza señales en la DB
   - `sync_watchlist_to_signals()`: Migra datos existentes de watchlist a señales

### 5. Frontend Actualizado

✅ **Nueva función API** (`frontend/src/lib/api.ts`)
   - `getDashboardState()`: Función para obtener el estado completo del dashboard
   - Tipos TypeScript definidos: `DashboardState`, `DashboardSignal`, `DashboardBalance`, `DashboardOrder`

## 🚀 Próximos Pasos para Usar

### 1. Las Tablas se Crean Automáticamente

Las tablas se crearán automáticamente cuando el backend inicie (ya configurado en `main.py` con `Base.metadata.create_all(bind=engine)`).

Para verificar que las tablas se crearon correctamente:

```bash
# Conectarse a la base de datos dentro del contenedor Docker
docker compose exec db psql -U trader -d atp -c "\dt"

# Deberías ver:
# - trade_signals
# - exchange_balances  
# - exchange_orders
```

### 2. Usar el Nuevo Endpoint en el Frontend

El frontend ahora puede usar:

```typescript
import { getDashboardState } from '@/lib/api';

const state = await getDashboardState();

// state.balances - Balances del exchange
// state.fast_signals - Señales que requieren refresco rápido (3-5s)
// state.slow_signals - Señales que requieren refresco lento (60s)
// state.open_orders - Órdenes abiertas
// state.last_sync - Última sincronización
```

### 3. Escribir Señales desde el Código

Cuando se calculen señales (por ejemplo, en `routes_signals.py`), usa:

```python
from app.services.signal_writer import upsert_trade_signal
from app.database import get_db

db = next(get_db())
upsert_trade_signal(
    db=db,
    symbol="BTC_USDT",
    preset="swing",
    sl_profile="conservative",
    rsi=35.5,
    ma50=45000,
    ema10=45200,
    current_price=45100,
    should_trade=True,
    status="pending"
)
```

### 4. El Servicio de Sincronización Ya Está Corriendo

El servicio de sincronización se inicia automáticamente cuando el backend arranca. Los datos se actualizan automáticamente cada 5 segundos.

Para verificar que está funcionando:

```bash
# Ver logs del backend
docker compose logs -f backend

# Deberías ver mensajes como:
# "Exchange sync service started"
# "Synced X account balances"
# "Synced X open orders"
```

## ✨ Ventajas de la Nueva Arquitectura

1. **⚡ Rendimiento**: La DB es mucho más rápida que leer Google Sheets
2. **🔄 Sincronización en tiempo real**: Datos del exchange actualizados cada 5 segundos
3. **📈 Escalabilidad**: Puede manejar muchas más señales y órdenes
4. **📊 Trazabilidad**: Historial completo de señales y órdenes
5. **🔗 Integración**: Más fácil integrar con otros servicios y APIs
6. **🎯 Endpoint único**: Una sola llamada obtiene todo el estado del dashboard

## 📝 Notas Importantes

- El servicio de sincronización se ejecuta en segundo plano automáticamente
- Las señales con `should_trade=true` o estado `order_placed`/`filled` se consideran "fast" y deberían refrescarse frecuentemente (3-5s)
- Las demás señales son "slow" y pueden refrescarse cada minuto
- Las órdenes del exchange se sincronizan automáticamente y actualizan el estado de las señales vinculadas

## 🔧 Archivos Creados/Modificados

**Nuevos modelos:**
- `backend/app/models/trade_signal.py`
- `backend/app/models/exchange_balance.py`
- `backend/app/models/exchange_order.py`

**Nuevos servicios:**
- `backend/app/services/exchange_sync.py`
- `backend/app/services/signal_writer.py`

**Nuevo endpoint:**
- `backend/app/api/routes_dashboard.py`

**Scripts:**
- `backend/scripts/create_tables.py` (las tablas se crean automáticamente)

**Documentación:**
- `backend/README_MIGRATION.md`
- `MIGRATION_SUMMARY.md` (este archivo)

**Modificaciones:**
- `backend/app/main.py`: Inicio automático del servicio de sincronización
- `backend/app/models/__init__.py`: Exportación de nuevos modelos
- `frontend/src/lib/api.ts`: Nueva función `getDashboardState()` y tipos TypeScript

## ✅ Estado Final

Todo está listo para usar. El backend ya está sincronizando datos del exchange automáticamente y el endpoint `/api/dashboard/state` está disponible para que el frontend lo consuma.


## 📋 Resumen

Se ha completado exitosamente la migración del sistema de Google Sheets a una arquitectura basada en PostgreSQL. El dashboard ahora obtiene todos los datos desde la base de datos y el exchange (Crypto.com) directamente.

## 🎯 Cambios Implementados

### 1. Nuevos Modelos de Base de Datos

✅ **`TradeSignal`** (`backend/app/models/trade_signal.py`)
   - Reemplaza completamente la hoja de Google Sheets
   - Almacena señales de trading con todos los indicadores técnicos
   - Campos: symbol, preset, sl_profile, rsi, ma50, ma200, ema10, ma10w, atr, resistance_up/down, current_price, volume_24h, volume_ratio, should_trade, status, exchange_order_id

✅ **`ExchangeBalance`** (`backend/app/models/exchange_balance.py`)
   - Almacena balances del exchange (Crypto.com)
   - Campos: asset, free, locked, total

✅ **`ExchangeOrder`** (`backend/app/models/exchange_order.py`)
   - Almacena órdenes del exchange
   - Campos: exchange_order_id, symbol, side, status, price, quantity, etc.

### 2. Servicio de Sincronización Automática

✅ **`ExchangeSyncService`** (`backend/app/services/exchange_sync.py`)
   - Se ejecuta automáticamente cada 5 segundos
   - Sincroniza:
     - `get_account_summary()` → actualiza `exchange_balances`
     - `get_open_orders()` → actualiza `exchange_orders`
     - `get_order_history()` → actualiza órdenes ejecutadas (cada 50 segundos)
   - Actualiza automáticamente el estado de `trade_signals` cuando se vinculan con órdenes

### 3. Endpoint Unificado del Dashboard

✅ **`GET /api/dashboard/state`** (`backend/app/api/routes_dashboard.py`)
   - Devuelve TODO el estado del dashboard en una sola respuesta:
     ```json
     {
       "balances": [...],           // Balances del exchange
       "fast_signals": [...],        // Señales activas (should_trade=true o order_placed/filled)
       "slow_signals": [...],       // Resto de señales
       "open_orders": [...],        // Órdenes abiertas
       "last_sync": "2025-10-31T..." // Timestamp de última sincronización
     }
     ```

### 4. Servicios de Escritura

✅ **`SignalWriter`** (`backend/app/services/signal_writer.py`)
   - `upsert_trade_signal()`: Escribe/actualiza señales en la DB
   - `sync_watchlist_to_signals()`: Migra datos existentes de watchlist a señales

### 5. Frontend Actualizado

✅ **Nueva función API** (`frontend/src/lib/api.ts`)
   - `getDashboardState()`: Función para obtener el estado completo del dashboard
   - Tipos TypeScript definidos: `DashboardState`, `DashboardSignal`, `DashboardBalance`, `DashboardOrder`

## 🚀 Próximos Pasos para Usar

### 1. Las Tablas se Crean Automáticamente

Las tablas se crearán automáticamente cuando el backend inicie (ya configurado en `main.py` con `Base.metadata.create_all(bind=engine)`).

Para verificar que las tablas se crearon correctamente:

```bash
# Conectarse a la base de datos dentro del contenedor Docker
docker compose exec db psql -U trader -d atp -c "\dt"

# Deberías ver:
# - trade_signals
# - exchange_balances  
# - exchange_orders
```

### 2. Usar el Nuevo Endpoint en el Frontend

El frontend ahora puede usar:

```typescript
import { getDashboardState } from '@/lib/api';

const state = await getDashboardState();

// state.balances - Balances del exchange
// state.fast_signals - Señales que requieren refresco rápido (3-5s)
// state.slow_signals - Señales que requieren refresco lento (60s)
// state.open_orders - Órdenes abiertas
// state.last_sync - Última sincronización
```

### 3. Escribir Señales desde el Código

Cuando se calculen señales (por ejemplo, en `routes_signals.py`), usa:

```python
from app.services.signal_writer import upsert_trade_signal
from app.database import get_db

db = next(get_db())
upsert_trade_signal(
    db=db,
    symbol="BTC_USDT",
    preset="swing",
    sl_profile="conservative",
    rsi=35.5,
    ma50=45000,
    ema10=45200,
    current_price=45100,
    should_trade=True,
    status="pending"
)
```

### 4. El Servicio de Sincronización Ya Está Corriendo

El servicio de sincronización se inicia automáticamente cuando el backend arranca. Los datos se actualizan automáticamente cada 5 segundos.

Para verificar que está funcionando:

```bash
# Ver logs del backend
docker compose logs -f backend

# Deberías ver mensajes como:
# "Exchange sync service started"
# "Synced X account balances"
# "Synced X open orders"
```

## ✨ Ventajas de la Nueva Arquitectura

1. **⚡ Rendimiento**: La DB es mucho más rápida que leer Google Sheets
2. **🔄 Sincronización en tiempo real**: Datos del exchange actualizados cada 5 segundos
3. **📈 Escalabilidad**: Puede manejar muchas más señales y órdenes
4. **📊 Trazabilidad**: Historial completo de señales y órdenes
5. **🔗 Integración**: Más fácil integrar con otros servicios y APIs
6. **🎯 Endpoint único**: Una sola llamada obtiene todo el estado del dashboard

## 📝 Notas Importantes

- El servicio de sincronización se ejecuta en segundo plano automáticamente
- Las señales con `should_trade=true` o estado `order_placed`/`filled` se consideran "fast" y deberían refrescarse frecuentemente (3-5s)
- Las demás señales son "slow" y pueden refrescarse cada minuto
- Las órdenes del exchange se sincronizan automáticamente y actualizan el estado de las señales vinculadas

## 🔧 Archivos Creados/Modificados

**Nuevos modelos:**
- `backend/app/models/trade_signal.py`
- `backend/app/models/exchange_balance.py`
- `backend/app/models/exchange_order.py`

**Nuevos servicios:**
- `backend/app/services/exchange_sync.py`
- `backend/app/services/signal_writer.py`

**Nuevo endpoint:**
- `backend/app/api/routes_dashboard.py`

**Scripts:**
- `backend/scripts/create_tables.py` (las tablas se crean automáticamente)

**Documentación:**
- `backend/README_MIGRATION.md`
- `MIGRATION_SUMMARY.md` (este archivo)

**Modificaciones:**
- `backend/app/main.py`: Inicio automático del servicio de sincronización
- `backend/app/models/__init__.py`: Exportación de nuevos modelos
- `frontend/src/lib/api.ts`: Nueva función `getDashboardState()` y tipos TypeScript

## ✅ Estado Final

Todo está listo para usar. El backend ya está sincronizando datos del exchange automáticamente y el endpoint `/api/dashboard/state` está disponible para que el frontend lo consuma.


## 📋 Resumen

Se ha completado exitosamente la migración del sistema de Google Sheets a una arquitectura basada en PostgreSQL. El dashboard ahora obtiene todos los datos desde la base de datos y el exchange (Crypto.com) directamente.

## 🎯 Cambios Implementados

### 1. Nuevos Modelos de Base de Datos

✅ **`TradeSignal`** (`backend/app/models/trade_signal.py`)
   - Reemplaza completamente la hoja de Google Sheets
   - Almacena señales de trading con todos los indicadores técnicos
   - Campos: symbol, preset, sl_profile, rsi, ma50, ma200, ema10, ma10w, atr, resistance_up/down, current_price, volume_24h, volume_ratio, should_trade, status, exchange_order_id

✅ **`ExchangeBalance`** (`backend/app/models/exchange_balance.py`)
   - Almacena balances del exchange (Crypto.com)
   - Campos: asset, free, locked, total

✅ **`ExchangeOrder`** (`backend/app/models/exchange_order.py`)
   - Almacena órdenes del exchange
   - Campos: exchange_order_id, symbol, side, status, price, quantity, etc.

### 2. Servicio de Sincronización Automática

✅ **`ExchangeSyncService`** (`backend/app/services/exchange_sync.py`)
   - Se ejecuta automáticamente cada 5 segundos
   - Sincroniza:
     - `get_account_summary()` → actualiza `exchange_balances`
     - `get_open_orders()` → actualiza `exchange_orders`
     - `get_order_history()` → actualiza órdenes ejecutadas (cada 50 segundos)
   - Actualiza automáticamente el estado de `trade_signals` cuando se vinculan con órdenes

### 3. Endpoint Unificado del Dashboard

✅ **`GET /api/dashboard/state`** (`backend/app/api/routes_dashboard.py`)
   - Devuelve TODO el estado del dashboard en una sola respuesta:
     ```json
     {
       "balances": [...],           // Balances del exchange
       "fast_signals": [...],        // Señales activas (should_trade=true o order_placed/filled)
       "slow_signals": [...],       // Resto de señales
       "open_orders": [...],        // Órdenes abiertas
       "last_sync": "2025-10-31T..." // Timestamp de última sincronización
     }
     ```

### 4. Servicios de Escritura

✅ **`SignalWriter`** (`backend/app/services/signal_writer.py`)
   - `upsert_trade_signal()`: Escribe/actualiza señales en la DB
   - `sync_watchlist_to_signals()`: Migra datos existentes de watchlist a señales

### 5. Frontend Actualizado

✅ **Nueva función API** (`frontend/src/lib/api.ts`)
   - `getDashboardState()`: Función para obtener el estado completo del dashboard
   - Tipos TypeScript definidos: `DashboardState`, `DashboardSignal`, `DashboardBalance`, `DashboardOrder`

## 🚀 Próximos Pasos para Usar

### 1. Las Tablas se Crean Automáticamente

Las tablas se crearán automáticamente cuando el backend inicie (ya configurado en `main.py` con `Base.metadata.create_all(bind=engine)`).

Para verificar que las tablas se crearon correctamente:

```bash
# Conectarse a la base de datos dentro del contenedor Docker
docker compose exec db psql -U trader -d atp -c "\dt"

# Deberías ver:
# - trade_signals
# - exchange_balances  
# - exchange_orders
```

### 2. Usar el Nuevo Endpoint en el Frontend

El frontend ahora puede usar:

```typescript
import { getDashboardState } from '@/lib/api';

const state = await getDashboardState();

// state.balances - Balances del exchange
// state.fast_signals - Señales que requieren refresco rápido (3-5s)
// state.slow_signals - Señales que requieren refresco lento (60s)
// state.open_orders - Órdenes abiertas
// state.last_sync - Última sincronización
```

### 3. Escribir Señales desde el Código

Cuando se calculen señales (por ejemplo, en `routes_signals.py`), usa:

```python
from app.services.signal_writer import upsert_trade_signal
from app.database import get_db

db = next(get_db())
upsert_trade_signal(
    db=db,
    symbol="BTC_USDT",
    preset="swing",
    sl_profile="conservative",
    rsi=35.5,
    ma50=45000,
    ema10=45200,
    current_price=45100,
    should_trade=True,
    status="pending"
)
```

### 4. El Servicio de Sincronización Ya Está Corriendo

El servicio de sincronización se inicia automáticamente cuando el backend arranca. Los datos se actualizan automáticamente cada 5 segundos.

Para verificar que está funcionando:

```bash
# Ver logs del backend
docker compose logs -f backend

# Deberías ver mensajes como:
# "Exchange sync service started"
# "Synced X account balances"
# "Synced X open orders"
```

## ✨ Ventajas de la Nueva Arquitectura

1. **⚡ Rendimiento**: La DB es mucho más rápida que leer Google Sheets
2. **🔄 Sincronización en tiempo real**: Datos del exchange actualizados cada 5 segundos
3. **📈 Escalabilidad**: Puede manejar muchas más señales y órdenes
4. **📊 Trazabilidad**: Historial completo de señales y órdenes
5. **🔗 Integración**: Más fácil integrar con otros servicios y APIs
6. **🎯 Endpoint único**: Una sola llamada obtiene todo el estado del dashboard

## 📝 Notas Importantes

- El servicio de sincronización se ejecuta en segundo plano automáticamente
- Las señales con `should_trade=true` o estado `order_placed`/`filled` se consideran "fast" y deberían refrescarse frecuentemente (3-5s)
- Las demás señales son "slow" y pueden refrescarse cada minuto
- Las órdenes del exchange se sincronizan automáticamente y actualizan el estado de las señales vinculadas

## 🔧 Archivos Creados/Modificados

**Nuevos modelos:**
- `backend/app/models/trade_signal.py`
- `backend/app/models/exchange_balance.py`
- `backend/app/models/exchange_order.py`

**Nuevos servicios:**
- `backend/app/services/exchange_sync.py`
- `backend/app/services/signal_writer.py`

**Nuevo endpoint:**
- `backend/app/api/routes_dashboard.py`

**Scripts:**
- `backend/scripts/create_tables.py` (las tablas se crean automáticamente)

**Documentación:**
- `backend/README_MIGRATION.md`
- `MIGRATION_SUMMARY.md` (este archivo)

**Modificaciones:**
- `backend/app/main.py`: Inicio automático del servicio de sincronización
- `backend/app/models/__init__.py`: Exportación de nuevos modelos
- `frontend/src/lib/api.ts`: Nueva función `getDashboardState()` y tipos TypeScript

## ✅ Estado Final

Todo está listo para usar. El backend ya está sincronizando datos del exchange automáticamente y el endpoint `/api/dashboard/state` está disponible para que el frontend lo consuma.

