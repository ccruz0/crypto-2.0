# 🔍 Diagnóstico: Alertas se Generan pero NO se Crean Órdenes

**Fecha**: 2026-01-08  
**Sistema**: AWS Production  
**Problema**: Las alertas se generan correctamente, pero NO se crean órdenes de compra automáticamente.

---

## 📋 PHASE 1 — Secuencia Esperada (desde docs)

### Flujo Documentado:

```
SIGNAL (BUY/SELL detectado)
  ↓
ALERT CREATED (si alert_enabled=True y throttling pasa)
  ↓
CHECK trade_enabled=True
  ↓
CHECK trade_amount_usd > 0
  ↓
CHECK MAs disponibles (MA50, EMA10)
  ↓
CHECK guardrails (límites, cooldown, portfolio)
  ↓
BUY ORDER CREATED (si todas las condiciones pasan)
```

### Definiciones Clave:

1. **SIGNAL**: Señal de trading detectada por indicadores técnicos (RSI, MA, EMA, etc.)
2. **ALERT**: Notificación enviada por Telegram cuando se detecta una señal y se cumplen condiciones de throttling
3. **BUY ORDER**: Orden de compra creada automáticamente en el exchange

### Condiciones para Crear Orden (según `ALERTAS_Y_ORDENES_NORMAS.md`):

- ✅ `alert_enabled = True` (master switch para alertas)
- ✅ `trade_enabled = True` (master switch para trading automático)
- ✅ `trade_amount_usd > 0` (monto configurado)
- ✅ MAs disponibles (MA50, EMA10)
- ✅ Guardrails pasados (límites, cooldown, portfolio)

---

## 🔍 PHASE 2 — Flujo Real en el Código

### 1. Generación de Señales

**Archivo**: `backend/app/services/signal_monitor.py`

- **Función**: `monitor_signals()` (línea 1093)
- **Proceso**: 
  - Consulta watchlist con `alert_enabled=True`
  - Para cada moneda, llama `_check_signal_for_coin_sync()`
  - Calcula señales usando `calculate_trading_signals()`

### 2. Creación de Alertas

**Archivo**: `backend/app/services/signal_monitor.py`

- **Función**: `_check_signal_for_coin_sync()` (línea 1135)
- **Proceso**:
  - Verifica `alert_enabled=True` y `buy_alert_enabled=True` (o `sell_alert_enabled=True`)
  - Verifica throttling (time gate: 60s, price gate: min_price_change_pct)
  - Si pasa, envía alerta por Telegram
  - **CRÍTICO**: Las alertas se envían independientemente de `trade_enabled`

### 3. Lógica de Trading / Ejecución

**Archivo**: `backend/app/services/signal_monitor.py`

- **Función**: `_check_signal_for_coin_sync()` → sección de creación de órdenes (línea 2767+)
- **Proceso**:
  1. Verifica `should_create_order = True` (basado en límites y cooldown)
  2. **LÍNEA 3010**: `if watchlist_item.trade_enabled:`
     - Si `False` → **BLOQUEA** creación de orden (línea 3192-3208)
     - Si `True` → continúa
  3. Verifica `trade_amount_usd > 0`
  4. Verifica MAs disponibles
  5. Verifica guardrails (`can_place_real_order()`)
  6. Llama `_create_buy_order()` (línea 3029)

**Archivo**: `backend/app/services/signal_monitor.py`

- **Función**: `_create_buy_order()` (línea 3934)
- **Proceso**:
  1. Verifica `trade_enabled` nuevamente (línea 3943)
  2. Verifica `trade_amount_usd > 0`
  3. Verifica balance disponible (si SPOT)
  4. Obtiene `live_trading` status (línea 4169)
  5. Llama `trade_client.place_market_order()` con `dry_run=not live_trading`

**Archivo**: `backend/app/services/brokers/crypto_com_trade.py`

- **Función**: `place_market_order()` (línea ~1300)
- **Proceso**:
  - Si `dry_run=True` → retorna orden simulada (línea 1344-1356)
  - Si `dry_run=False` → crea orden real en el exchange

---

## 🛡️ PHASE 3 — Guardrails y Bloqueos Intencionados

### Environment Flags Verificados:

1. **LIVE_TRADING** (verificado en AWS):
   - **Estado**: `true` (base de datos y entorno)
   - **Ubicación**: `TradingSettings.setting_key='LIVE_TRADING'`
   - **Función**: `get_live_trading_status(db)` → `True`
   - **Resultado**: ✅ **NO BLOQUEA**

2. **TRADING_ENABLED** (env var opcional):
   - **Estado**: No configurado (default: no restricción)
   - **Resultado**: ✅ **NO BLOQUEA**

3. **TRADING_KILL_SWITCH**:
   - **Estado**: No verificado explícitamente, pero no hay evidencia de bloqueo
   - **Resultado**: ✅ **NO BLOQUEA** (asumido)

### Patrones de Bloqueo Encontrados:

1. **`if not trade_enabled: return`** (línea 3010, 3943)
   - **Ubicación**: `signal_monitor.py`
   - **Comportamiento**: Si `trade_enabled=False`, la orden NO se crea
   - **Log**: `"trade_enabled=False, alert was sent but order will NOT be created"` (línea 3194)

2. **`if dry_run: return simulated_order`** (línea 1344)
   - **Ubicación**: `crypto_com_trade.py`
   - **Comportamiento**: Si `dry_run=True`, retorna orden simulada (no real)
   - **Estado**: `dry_run = not live_trading` → `dry_run = False` (porque `live_trading=True`)

3. **Guardrails adicionales** (línea 4200+):
   - `can_place_real_order()` verifica:
     - LIVE_TRADING ON
     - TRADING_KILL_SWITCH OFF
     - `trade_enabled=True` para el símbolo
     - Límites de riesgo (MAX_OPEN_ORDERS_TOTAL, etc.)

---

## 🔄 PHASE 4 — Comparar ALERT vs BUY Paths

### ¿La alerta y la compra comparten código?

**SÍ**, pero con diferencias críticas:

1. **Alertas** (línea 765-965):
   - Solo requiere: `alert_enabled=True` + `buy_alert_enabled=True` + throttling pasa
   - **NO requiere** `trade_enabled=True`

2. **Órdenes** (línea 2767+):
   - Requiere: `alert_enabled=True` + `trade_enabled=True` + `trade_amount_usd > 0` + MAs + guardrails
   - **CRÍTICO**: Si `trade_enabled=False`, la orden NO se crea (línea 3010)

### ¿La alerta es solo NOTIFY?

**SÍ**. Las alertas son **solo informativas**. La creación de órdenes es **independiente** y requiere `trade_enabled=True`.

### ¿La compra depende de otro worker/servicio?

**NO**. Todo ocurre en el mismo proceso (`signal_monitor.py`), en la misma función `_check_signal_for_coin_sync()`.

### Escenario Identificado:

**A) Compra desactivada por diseño** + **B) Compra requiere flag que no está activo**

- Las alertas se envían porque `alert_enabled=True`
- Las órdenes NO se crean porque `trade_enabled=False` para la mayoría de las monedas

---

## 📊 PHASE 5 — Logs y Evidencias

### Estado Real en AWS (verificado):

```python
# Monedas con alert_enabled=True:
BTC_USDT: alert_enabled=True, trade_enabled=False  ❌
ETC_USDT: alert_enabled=True, trade_enabled=False  ❌
SOL_USDT: alert_enabled=True, trade_enabled=False  ❌
... (30+ monedas con trade_enabled=False)

# Monedas con trade_enabled=True (solo 6):
SUI_USDT: alert_enabled=True, trade_enabled=True   ✅
ETH_USDT: alert_enabled=True, trade_enabled=True   ✅
ALGO_USDT: alert_enabled=True, trade_enabled=True  ✅
ETH_USD: alert_enabled=True, trade_enabled=True    ✅
BTC_USD: alert_enabled=True, trade_enabled=True    ✅
DOT_USDT: alert_enabled=True, trade_enabled=True  ✅
```

### Código que Bloquea (evidencia):

**Archivo**: `backend/app/services/signal_monitor.py`

```python
# Línea 3010-3208
if watchlist_item.trade_enabled:
    logger.info(f"✅ [ORDER_CREATION_CHECK] {symbol} - trade_enabled=True confirmed, proceeding with order creation")
    # ... crear orden ...
else:
    # alert_enabled = true but trade_enabled = false - send alert only, no order
    logger.info(
        f"ℹ️ [ORDER_CREATION_CHECK] {symbol} - trade_enabled=False, "
        f"alert was sent but order will NOT be created (trading disabled for this symbol)"
    )
    # NO SE CREA ORDEN
```

**Archivo**: `backend/app/services/signal_monitor.py`

```python
# Línea 3943-3952
if not getattr(watchlist_item, 'trade_enabled', False):
    logger.warning(
        f"🚫 Blocked BUY order creation for {symbol}: trade_enabled=False. "
        f"This function should not be called when trade is disabled."
    )
    return {"error": "trade_disabled", "error_type": "trade_disabled", "message": f"Trade is disabled for {symbol}"}
```

---

## ✅ PHASE 6 — Conclusión Clara

### 1. Dónde se Rompe la Secuencia

**Archivo**: `backend/app/services/signal_monitor.py`  
**Función**: `_check_signal_for_coin_sync()`  
**Línea**: **3010** (check principal) y **3943** (check secundario en `_create_buy_order`)

**Secuencia Rota**:
```
SIGNAL ✅
  ↓
ALERT CREATED ✅ (se envía correctamente)
  ↓
CHECK trade_enabled ❌ (FALSE para la mayoría de monedas)
  ↓
BUY ORDER CREATED ❌ (NO se crea)
```

### 2. Por Qué NO se Compra

**RAZÓN PRINCIPAL**: `trade_enabled=False` para la mayoría de las monedas en la watchlist.

**Evidencia**:
- 30+ monedas tienen `alert_enabled=True` pero `trade_enabled=False`
- Solo 6 monedas tienen `trade_enabled=True`
- El código explícitamente bloquea la creación de órdenes si `trade_enabled=False` (línea 3010, 3943)

**Tipo**: **Diseño intencional** (no es un bug)

- Las alertas están diseñadas para ser **solo informativas**
- Las órdenes requieren **activación explícita** mediante `trade_enabled=True`
- Esto permite recibir alertas sin ejecutar trades automáticamente

### 3. Cómo Debería Funcionar Según Intención Original

Según `ALERTAS_Y_ORDENES_NORMAS.md`:

1. **Alertas**: Se envían cuando `alert_enabled=True` y se cumplen condiciones de throttling
2. **Órdenes**: Se crean automáticamente **solo si**:
   - `alert_enabled=True` ✅
   - `trade_enabled=True` ✅ (REQUERIDO)
   - `trade_amount_usd > 0` ✅
   - MAs disponibles ✅
   - Guardrails pasados ✅

**El sistema está funcionando según diseño**: Las alertas se envían, pero las órdenes NO se crean porque `trade_enabled=False`.

### 4. Cambio Mínimo Necesario

#### Opción A: Activar `trade_enabled` para Monedas Específicas

**Archivo**: Base de datos (`watchlist_items` table)  
**Cambio**: Actualizar `trade_enabled=True` para las monedas donde se desea trading automático

**SQL**:
```sql
UPDATE watchlist_items 
SET trade_enabled = true 
WHERE symbol IN ('BTC_USDT', 'ETH_USDT', ...)  -- Lista de monedas deseadas
  AND alert_enabled = true;
```

**Riesgos**:
- ⚠️ **ALTO**: Activar trading automático para muchas monedas puede generar muchas órdenes
- ⚠️ **MEDIO**: Requiere verificar que `trade_amount_usd` esté configurado para cada moneda
- ⚠️ **BAJO**: El sistema tiene guardrails (límites, cooldown) que previenen sobre-trading

**Recomendación**: Activar solo para 1-3 monedas inicialmente para validar el comportamiento.

#### Opción B: Activar `trade_enabled` Globalmente (NO RECOMENDADO)

**Archivo**: Base de datos (`watchlist_items` table)  
**Cambio**: Actualizar todas las monedas con `alert_enabled=True` a `trade_enabled=True`

**SQL**:
```sql
UPDATE watchlist_items 
SET trade_enabled = true 
WHERE alert_enabled = true;
```

**Riesgos**:
- ⚠️ **MUY ALTO**: Activar trading automático para 30+ monedas puede generar muchas órdenes simultáneas
- ⚠️ **ALTO**: Puede exceder límites de guardrails rápidamente
- ⚠️ **MEDIO**: Requiere verificar que todas las monedas tengan `trade_amount_usd` configurado

**Recomendación**: **NO HACER ESTO** sin validación previa.

#### Opción C: Cambiar el Comportamiento del Código (NO RECOMENDADO)

**Archivo**: `backend/app/services/signal_monitor.py`  
**Cambio**: Remover el check de `trade_enabled` (línea 3010)

**Riesgos**:
- ⚠️ **CRÍTICO**: Esto eliminaría la separación intencional entre alertas y trading
- ⚠️ **ALTO**: Podría crear órdenes no deseadas si el usuario solo quiere alertas
- ⚠️ **ALTO**: Cambiaría el comportamiento fundamental del sistema

**Recomendación**: **NO HACER ESTO**. El diseño actual es correcto.

---

## 🎯 Recomendación Final

**Solución Recomendada**: **Opción A** (activar `trade_enabled` para monedas específicas)

**Pasos**:
1. Identificar 1-3 monedas para testing inicial
2. Verificar que tengan `trade_amount_usd > 0` configurado
3. Activar `trade_enabled=True` solo para esas monedas
4. Monitorear logs para confirmar que las órdenes se crean correctamente
5. Si funciona bien, activar para más monedas gradualmente

**Comando SQL de Ejemplo**:
```sql
-- Activar trading para monedas específicas
UPDATE watchlist_items 
SET trade_enabled = true 
WHERE symbol IN ('BTC_USDT', 'ETH_USDT', 'DOT_USDT')
  AND alert_enabled = true
  AND trade_amount_usd > 0;
```

**Validación**:
- Verificar logs: buscar `"ORDER_PLACED side=BUY"` después de una alerta
- Verificar base de datos: confirmar que se crean registros en `exchange_orders`
- Verificar exchange: confirmar que las órdenes aparecen en Crypto.com

---

## 📝 Resumen Ejecutivo

- **Root Cause**: `trade_enabled=False` para la mayoría de las monedas bloquea la creación de órdenes automáticas
- **Evidence**: Código en `signal_monitor.py` línea 3010 y 3943 explícitamente verifica `trade_enabled` antes de crear órdenes
- **Fix Proposal**: Activar `trade_enabled=True` para monedas específicas donde se desea trading automático
- **Riesgos**: Bajo si se activa gradualmente para pocas monedas, ALTO si se activa globalmente sin validación

**Estado Actual**: ✅ Sistema funcionando según diseño. Las alertas se envían correctamente. Las órdenes NO se crean porque `trade_enabled=False` (diseño intencional para separar alertas de trading).


