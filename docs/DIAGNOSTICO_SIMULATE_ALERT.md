# Diagnóstico: Por qué las Alertas de Prueba No Generan Órdenes

## Problema
La alerta de prueba para AAVE_USDT se envió correctamente a Telegram, pero NO se creó ninguna orden ni se reportó ningún error visible.

## Análisis del Flujo

### 1. Flujo de `simulate_alert` (routes_test.py)

El endpoint `/test/simulate-alert` tiene el siguiente flujo:

```
1. Envía alerta a Telegram ✅ (esto funcionó)
2. Verifica trade_enabled
   ├─ Si False → No crea orden, solo alerta
   └─ Si True → Continúa
3. Verifica trade_amount_usd
   ├─ Si None o <= 0 → No crea orden, envía error a Telegram
   └─ Si > 0 → Continúa
4. Crea orden en background (async)
   ├─ Llama _create_buy_order()
   ├─ Si retorna None → Orden bloqueada (límites, seguridad, etc.)
   └─ Si retorna orden → Orden creada exitosamente
```

### 2. Posibles Causas

#### A. `trade_enabled = False` (MÁS PROBABLE)
**Ubicación**: Línea 287 de `routes_test.py`

**Síntoma**: 
- Alerta se envía ✅
- Orden NO se crea ❌
- No se envía notificación de error (CORREGIDO ahora)

**Solución**: 
- Habilitar "Trade" = YES en el Dashboard para AAVE_USDT
- Ahora se enviará notificación a Telegram explicando esto

#### B. `trade_amount_usd` no configurado o = 0
**Ubicación**: Línea 292 de `routes_test.py`

**Síntoma**:
- Alerta se envía ✅
- Orden NO se crea ❌
- Error se envía a Telegram ✅

**Solución**:
- Configurar "Amount USD" > 0 en el Dashboard para AAVE_USDT

#### C. Orden bloqueada por límites o verificaciones de seguridad
**Ubicación**: `signal_monitor._create_buy_order()` retorna `None`

**Causas posibles**:
1. **Límite de órdenes por símbolo alcanzado** (3 órdenes máx)
2. **Límite global de órdenes alcanzado**
3. **Orden reciente en los últimos 5 minutos** (cooldown)
4. **Valor en cartera excede 3x trade_amount_usd**
5. **Verificación de seguridad bloquea la orden**

**Síntoma**:
- `_create_buy_order()` retorna `None` sin error explícito
- Orden NO se crea ❌
- No se notifica a Telegram (CORREGIDO ahora)

**Solución**:
- Revisar logs del backend buscando:
  - `[Background] Order creation returned None`
  - `SEGURIDAD 2/2: ... BLOQUEADO`
  - `BLOCKED at final check`
  - `LÍMITE ALCANZADO`

#### D. Error en la creación de orden
**Ubicación**: Línea 424 de `routes_test.py` (except block)

**Síntoma**:
- Excepción capturada en background task
- Error se envía a Telegram ✅

## Mejoras Implementadas

### 1. Notificación cuando `trade_enabled = False`
Ahora se envía una notificación a Telegram explicando que la orden no se creó porque `trade_enabled = False`.

### 2. Notificación cuando orden retorna `None`
Ahora se envía una notificación cuando `_create_buy_order()` retorna `None`, explicando las posibles causas.

### 3. Notificación de éxito
Se envía notificación a Telegram cuando la orden se crea exitosamente, con detalles del order_id y status.

## Cómo Diagnosticar

### Opción 1: Usar el script de diagnóstico
```bash
cd /Users/carloscruz/automated-trading-platform
docker compose exec backend python scripts/diagnose_simulate_alert.py AAVE_USDT
```

Este script verifica:
- ✅ Configuración de watchlist (trade_enabled, trade_amount_usd)
- ✅ Órdenes abiertas (símbolo y global)
- ✅ Órdenes recientes (últimos 5 minutos)
- ✅ Valor en cartera vs límites

### Opción 2: Revisar logs del backend
```bash
docker compose logs backend | grep -i "AAVE_USDT\|simulate-alert\|Background.*order"
```

Buscar:
- `Trade not enabled for AAVE_USDT`
- `Cannot create order for AAVE_USDT`
- `[Background] Order creation returned None`
- `[Background] Error creating order`

### Opción 3: Verificar configuración en Dashboard
1. Abrir Dashboard
2. Buscar AAVE_USDT en watchlist
3. Verificar:
   - ✅ "Trade" = YES
   - ✅ "Amount USD" > 0

### Opción 4: Revisar Telegram
Ahora recibirás notificaciones en Telegram explicando por qué no se creó la orden:
- ⚠️ `TEST ALERT: Orden no creada` - con razón específica
- ✅ `TEST ALERT: Orden creada exitosamente` - cuando funciona

## Checklist de Verificación

Para que una alerta de prueba genere una orden, debe cumplir TODOS estos requisitos:

- [ ] ✅ Símbolo existe en watchlist
- [ ] ✅ `trade_enabled = True` (Trade = YES en Dashboard)
- [ ] ✅ `trade_amount_usd > 0` (Amount USD configurado)
- [ ] ✅ Menos de 3 órdenes abiertas para el símbolo
- [ ] ✅ No hay órdenes recientes (últimos 5 minutos)
- [ ] ✅ Valor en cartera <= 3x trade_amount_usd
- [ ] ✅ No bloqueado por verificaciones de seguridad

## Próximos Pasos

1. **Verificar configuración de AAVE_USDT**:
   - Abrir Dashboard
   - Buscar AAVE_USDT
   - Verificar Trade = YES y Amount USD > 0

2. **Revisar Telegram**:
   - Deberías recibir una notificación explicando por qué no se creó la orden

3. **Revisar logs** (si es necesario):
   - Buscar mensajes relacionados con AAVE_USDT y simulate-alert

4. **Repetir prueba**:
   - Con la configuración correcta, la orden debería crearse
   - Deberías recibir notificación de éxito en Telegram

## Archivos Modificados

1. `backend/app/api/routes_test.py`:
   - Línea ~289: Agregada notificación cuando `trade_enabled = False`
   - Línea ~419: Agregada notificación cuando orden retorna `None`
   - Línea ~353: Agregada notificación de éxito

2. `backend/scripts/diagnose_simulate_alert.py`:
   - Script nuevo para diagnóstico completo

