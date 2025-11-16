# Migración de Google Sheets a Base de Datos

Este documento describe la migración del sistema de Google Sheets a una arquitectura basada en base de datos PostgreSQL.

## Cambios Realizados

### 1. Nuevos Modelos de Base de Datos

Se crearon tres nuevos modelos:

- **`TradeSignal`** (`app/models/trade_signal.py`):
  - Reemplaza la hoja de Google Sheets
  - Almacena señales de trading con todos los indicadores técnicos
  - Campos: symbol, preset, sl_profile, rsi, ma50, ma200, ema10, ma10w, atr, resistance_up/down, current_price, volume_24h, volume_ratio, should_trade, status, exchange_order_id

- **`ExchangeBalance`** (`app/models/exchange_balance.py`):
  - Almacena balances del exchange (Crypto.com)
  - Campos: asset, free, locked, total

- **`ExchangeOrder`** (`app/models/exchange_order.py`):
  - Almacena órdenes del exchange
  - Campos: exchange_order_id, symbol, side, status, price, quantity, etc.

### 2. Servicio de Sincronización

**`ExchangeSyncService`** (`app/services/exchange_sync.py`):
- Sincroniza datos del exchange cada 5 segundos
- Consulta:
  - `get_account_summary()` → actualiza `exchange_balances`
  - `get_open_orders()` → actualiza `exchange_orders`
  - `get_order_history()` → actualiza órdenes ejecutadas (cada 50 segundos)
- Actualiza automáticamente el estado de `trade_signals` cuando se vinculan con órdenes

### 3. Endpoint Unificado del Dashboard

**`GET /api/dashboard/state`** (`app/api/routes_dashboard.py`):
- Devuelve todo el estado del dashboard en una sola respuesta:
  - `balances`: Balances del exchange
  - `fast_signals`: Señales con `should_trade=true` o estado `order_placed`/`filled`
  - `slow_signals`: Resto de señales
  - `open_orders`: Órdenes abiertas
  - `last_sync`: Timestamp de última sincronización

### 4. Servicio de Escritura de Señales

**`SignalWriter`** (`app/services/signal_writer.py`):
- Función `upsert_trade_signal()`: Escribe/actualiza señales en la DB
- Función `sync_watchlist_to_signals()`: Migra datos existentes de watchlist a señales

### 5. Integración en el Backend

- El servicio de sincronización se inicia automáticamente en `main.py` al arrancar el backend
- Las tablas se crean automáticamente al iniciar (SQLAlchemy `create_all`)

## Cómo Usar

### 1. Crear las Tablas

Ejecuta el script de migración:

```bash
cd backend
python scripts/create_tables.py
```

O las tablas se crearán automáticamente al iniciar el backend.

### 2. Migrar Datos Existentes (Opcional)

Si tienes datos en `watchlist_items` que quieres migrar a `trade_signals`:

```python
from app.database import SessionLocal
from app.services.signal_writer import sync_watchlist_to_signals

db = SessionLocal()
sync_watchlist_to_signals(db)
db.close()
```

### 3. Usar el Nuevo Endpoint

El frontend puede ahora usar:

```typescript
const response = await fetch('/api/dashboard/state');
const data = await response.json();

// data.balances
// data.fast_signals (refresco rápido: 3-5s)
// data.slow_signals (refresco lento: 60s)
// data.open_orders
// data.last_sync
```

### 4. Escribir Señales desde el Código

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

## Ventajas

1. **Rendimiento**: La DB es mucho más rápida que leer Google Sheets
2. **Sincronización en tiempo real**: Datos del exchange actualizados cada 5 segundos
3. **Escalabilidad**: Puede manejar muchas más señales y órdenes
4. **Trazabilidad**: Historial completo de señales y órdenes
5. **Integración**: Más fácil integrar con otros servicios y APIs

## Notas

- El servicio de sincronización se ejecuta en segundo plano automáticamente
- Las señales con `should_trade=true` o estado `order_placed`/`filled` se consideran "fast" y deberían refrescarse frecuentemente
- Las demás señales son "slow" y pueden refrescarse cada minuto
- Las órdenes del exchange se sincronizan automáticamente y actualizan el estado de las señales vinculadas


Este documento describe la migración del sistema de Google Sheets a una arquitectura basada en base de datos PostgreSQL.

## Cambios Realizados

### 1. Nuevos Modelos de Base de Datos

Se crearon tres nuevos modelos:

- **`TradeSignal`** (`app/models/trade_signal.py`):
  - Reemplaza la hoja de Google Sheets
  - Almacena señales de trading con todos los indicadores técnicos
  - Campos: symbol, preset, sl_profile, rsi, ma50, ma200, ema10, ma10w, atr, resistance_up/down, current_price, volume_24h, volume_ratio, should_trade, status, exchange_order_id

- **`ExchangeBalance`** (`app/models/exchange_balance.py`):
  - Almacena balances del exchange (Crypto.com)
  - Campos: asset, free, locked, total

- **`ExchangeOrder`** (`app/models/exchange_order.py`):
  - Almacena órdenes del exchange
  - Campos: exchange_order_id, symbol, side, status, price, quantity, etc.

### 2. Servicio de Sincronización

**`ExchangeSyncService`** (`app/services/exchange_sync.py`):
- Sincroniza datos del exchange cada 5 segundos
- Consulta:
  - `get_account_summary()` → actualiza `exchange_balances`
  - `get_open_orders()` → actualiza `exchange_orders`
  - `get_order_history()` → actualiza órdenes ejecutadas (cada 50 segundos)
- Actualiza automáticamente el estado de `trade_signals` cuando se vinculan con órdenes

### 3. Endpoint Unificado del Dashboard

**`GET /api/dashboard/state`** (`app/api/routes_dashboard.py`):
- Devuelve todo el estado del dashboard en una sola respuesta:
  - `balances`: Balances del exchange
  - `fast_signals`: Señales con `should_trade=true` o estado `order_placed`/`filled`
  - `slow_signals`: Resto de señales
  - `open_orders`: Órdenes abiertas
  - `last_sync`: Timestamp de última sincronización

### 4. Servicio de Escritura de Señales

**`SignalWriter`** (`app/services/signal_writer.py`):
- Función `upsert_trade_signal()`: Escribe/actualiza señales en la DB
- Función `sync_watchlist_to_signals()`: Migra datos existentes de watchlist a señales

### 5. Integración en el Backend

- El servicio de sincronización se inicia automáticamente en `main.py` al arrancar el backend
- Las tablas se crean automáticamente al iniciar (SQLAlchemy `create_all`)

## Cómo Usar

### 1. Crear las Tablas

Ejecuta el script de migración:

```bash
cd backend
python scripts/create_tables.py
```

O las tablas se crearán automáticamente al iniciar el backend.

### 2. Migrar Datos Existentes (Opcional)

Si tienes datos en `watchlist_items` que quieres migrar a `trade_signals`:

```python
from app.database import SessionLocal
from app.services.signal_writer import sync_watchlist_to_signals

db = SessionLocal()
sync_watchlist_to_signals(db)
db.close()
```

### 3. Usar el Nuevo Endpoint

El frontend puede ahora usar:

```typescript
const response = await fetch('/api/dashboard/state');
const data = await response.json();

// data.balances
// data.fast_signals (refresco rápido: 3-5s)
// data.slow_signals (refresco lento: 60s)
// data.open_orders
// data.last_sync
```

### 4. Escribir Señales desde el Código

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

## Ventajas

1. **Rendimiento**: La DB es mucho más rápida que leer Google Sheets
2. **Sincronización en tiempo real**: Datos del exchange actualizados cada 5 segundos
3. **Escalabilidad**: Puede manejar muchas más señales y órdenes
4. **Trazabilidad**: Historial completo de señales y órdenes
5. **Integración**: Más fácil integrar con otros servicios y APIs

## Notas

- El servicio de sincronización se ejecuta en segundo plano automáticamente
- Las señales con `should_trade=true` o estado `order_placed`/`filled` se consideran "fast" y deberían refrescarse frecuentemente
- Las demás señales son "slow" y pueden refrescarse cada minuto
- Las órdenes del exchange se sincronizan automáticamente y actualizan el estado de las señales vinculadas


Este documento describe la migración del sistema de Google Sheets a una arquitectura basada en base de datos PostgreSQL.

## Cambios Realizados

### 1. Nuevos Modelos de Base de Datos

Se crearon tres nuevos modelos:

- **`TradeSignal`** (`app/models/trade_signal.py`):
  - Reemplaza la hoja de Google Sheets
  - Almacena señales de trading con todos los indicadores técnicos
  - Campos: symbol, preset, sl_profile, rsi, ma50, ma200, ema10, ma10w, atr, resistance_up/down, current_price, volume_24h, volume_ratio, should_trade, status, exchange_order_id

- **`ExchangeBalance`** (`app/models/exchange_balance.py`):
  - Almacena balances del exchange (Crypto.com)
  - Campos: asset, free, locked, total

- **`ExchangeOrder`** (`app/models/exchange_order.py`):
  - Almacena órdenes del exchange
  - Campos: exchange_order_id, symbol, side, status, price, quantity, etc.

### 2. Servicio de Sincronización

**`ExchangeSyncService`** (`app/services/exchange_sync.py`):
- Sincroniza datos del exchange cada 5 segundos
- Consulta:
  - `get_account_summary()` → actualiza `exchange_balances`
  - `get_open_orders()` → actualiza `exchange_orders`
  - `get_order_history()` → actualiza órdenes ejecutadas (cada 50 segundos)
- Actualiza automáticamente el estado de `trade_signals` cuando se vinculan con órdenes

### 3. Endpoint Unificado del Dashboard

**`GET /api/dashboard/state`** (`app/api/routes_dashboard.py`):
- Devuelve todo el estado del dashboard en una sola respuesta:
  - `balances`: Balances del exchange
  - `fast_signals`: Señales con `should_trade=true` o estado `order_placed`/`filled`
  - `slow_signals`: Resto de señales
  - `open_orders`: Órdenes abiertas
  - `last_sync`: Timestamp de última sincronización

### 4. Servicio de Escritura de Señales

**`SignalWriter`** (`app/services/signal_writer.py`):
- Función `upsert_trade_signal()`: Escribe/actualiza señales en la DB
- Función `sync_watchlist_to_signals()`: Migra datos existentes de watchlist a señales

### 5. Integración en el Backend

- El servicio de sincronización se inicia automáticamente en `main.py` al arrancar el backend
- Las tablas se crean automáticamente al iniciar (SQLAlchemy `create_all`)

## Cómo Usar

### 1. Crear las Tablas

Ejecuta el script de migración:

```bash
cd backend
python scripts/create_tables.py
```

O las tablas se crearán automáticamente al iniciar el backend.

### 2. Migrar Datos Existentes (Opcional)

Si tienes datos en `watchlist_items` que quieres migrar a `trade_signals`:

```python
from app.database import SessionLocal
from app.services.signal_writer import sync_watchlist_to_signals

db = SessionLocal()
sync_watchlist_to_signals(db)
db.close()
```

### 3. Usar el Nuevo Endpoint

El frontend puede ahora usar:

```typescript
const response = await fetch('/api/dashboard/state');
const data = await response.json();

// data.balances
// data.fast_signals (refresco rápido: 3-5s)
// data.slow_signals (refresco lento: 60s)
// data.open_orders
// data.last_sync
```

### 4. Escribir Señales desde el Código

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

## Ventajas

1. **Rendimiento**: La DB es mucho más rápida que leer Google Sheets
2. **Sincronización en tiempo real**: Datos del exchange actualizados cada 5 segundos
3. **Escalabilidad**: Puede manejar muchas más señales y órdenes
4. **Trazabilidad**: Historial completo de señales y órdenes
5. **Integración**: Más fácil integrar con otros servicios y APIs

## Notas

- El servicio de sincronización se ejecuta en segundo plano automáticamente
- Las señales con `should_trade=true` o estado `order_placed`/`filled` se consideran "fast" y deberían refrescarse frecuentemente
- Las demás señales son "slow" y pueden refrescarse cada minuto
- Las órdenes del exchange se sincronizan automáticamente y actualizan el estado de las señales vinculadas


Este documento describe la migración del sistema de Google Sheets a una arquitectura basada en base de datos PostgreSQL.

## Cambios Realizados

### 1. Nuevos Modelos de Base de Datos

Se crearon tres nuevos modelos:

- **`TradeSignal`** (`app/models/trade_signal.py`):
  - Reemplaza la hoja de Google Sheets
  - Almacena señales de trading con todos los indicadores técnicos
  - Campos: symbol, preset, sl_profile, rsi, ma50, ma200, ema10, ma10w, atr, resistance_up/down, current_price, volume_24h, volume_ratio, should_trade, status, exchange_order_id

- **`ExchangeBalance`** (`app/models/exchange_balance.py`):
  - Almacena balances del exchange (Crypto.com)
  - Campos: asset, free, locked, total

- **`ExchangeOrder`** (`app/models/exchange_order.py`):
  - Almacena órdenes del exchange
  - Campos: exchange_order_id, symbol, side, status, price, quantity, etc.

### 2. Servicio de Sincronización

**`ExchangeSyncService`** (`app/services/exchange_sync.py`):
- Sincroniza datos del exchange cada 5 segundos
- Consulta:
  - `get_account_summary()` → actualiza `exchange_balances`
  - `get_open_orders()` → actualiza `exchange_orders`
  - `get_order_history()` → actualiza órdenes ejecutadas (cada 50 segundos)
- Actualiza automáticamente el estado de `trade_signals` cuando se vinculan con órdenes

### 3. Endpoint Unificado del Dashboard

**`GET /api/dashboard/state`** (`app/api/routes_dashboard.py`):
- Devuelve todo el estado del dashboard en una sola respuesta:
  - `balances`: Balances del exchange
  - `fast_signals`: Señales con `should_trade=true` o estado `order_placed`/`filled`
  - `slow_signals`: Resto de señales
  - `open_orders`: Órdenes abiertas
  - `last_sync`: Timestamp de última sincronización

### 4. Servicio de Escritura de Señales

**`SignalWriter`** (`app/services/signal_writer.py`):
- Función `upsert_trade_signal()`: Escribe/actualiza señales en la DB
- Función `sync_watchlist_to_signals()`: Migra datos existentes de watchlist a señales

### 5. Integración en el Backend

- El servicio de sincronización se inicia automáticamente en `main.py` al arrancar el backend
- Las tablas se crean automáticamente al iniciar (SQLAlchemy `create_all`)

## Cómo Usar

### 1. Crear las Tablas

Ejecuta el script de migración:

```bash
cd backend
python scripts/create_tables.py
```

O las tablas se crearán automáticamente al iniciar el backend.

### 2. Migrar Datos Existentes (Opcional)

Si tienes datos en `watchlist_items` que quieres migrar a `trade_signals`:

```python
from app.database import SessionLocal
from app.services.signal_writer import sync_watchlist_to_signals

db = SessionLocal()
sync_watchlist_to_signals(db)
db.close()
```

### 3. Usar el Nuevo Endpoint

El frontend puede ahora usar:

```typescript
const response = await fetch('/api/dashboard/state');
const data = await response.json();

// data.balances
// data.fast_signals (refresco rápido: 3-5s)
// data.slow_signals (refresco lento: 60s)
// data.open_orders
// data.last_sync
```

### 4. Escribir Señales desde el Código

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

## Ventajas

1. **Rendimiento**: La DB es mucho más rápida que leer Google Sheets
2. **Sincronización en tiempo real**: Datos del exchange actualizados cada 5 segundos
3. **Escalabilidad**: Puede manejar muchas más señales y órdenes
4. **Trazabilidad**: Historial completo de señales y órdenes
5. **Integración**: Más fácil integrar con otros servicios y APIs

## Notas

- El servicio de sincronización se ejecuta en segundo plano automáticamente
- Las señales con `should_trade=true` o estado `order_placed`/`filled` se consideran "fast" y deberían refrescarse frecuentemente
- Las demás señales son "slow" y pueden refrescarse cada minuto
- Las órdenes del exchange se sincronizan automáticamente y actualizan el estado de las señales vinculadas

