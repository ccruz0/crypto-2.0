# Análisis de Bloqueo de Alertas BTC_USDT

## Resumen Ejecutivo

El sistema tiene **DOS CAPAS DE THROTTLING** que pueden bloquear alertas:

1. **Primera Capa: `should_emit_signal`** (signal_throttle.py)
   - Usa la tabla `signal_throttle_states` en la base de datos
   - Se ejecuta ANTES de cualquier verificación de alertas
   - Si retorna False, establece `buy_signal = False` o `sell_signal = False`
   - **Líneas críticas: 1081 (BUY), 1176 (SELL), 1157 (BUY bloqueado), 1262 (SELL bloqueado)**

2. **Segunda Capa: `should_send_alert`** (signal_monitor.py)
   - Usa `self.last_alert_states` (diccionario en memoria)
   - Se ejecuta DESPUÉS de pasar la primera capa
   - Si retorna False, bloquea el envío de la alerta
   - **Líneas críticas: 1471 (BUY), 2207 (SELL), 1479 (BUY bloqueado), 2208 (SELL bloqueado)**

## Puntos de Bloqueo Identificados

### 1. Bloqueo por `should_emit_signal` (Primera Capa)

**Ubicación:** Líneas 1081-1159 (BUY), 1176-1264 (SELL)

**Condiciones que bloquean:**
- No se cumple `min_interval_minutes` (cooldown)
- No se cumple `min_price_change_pct` (cambio de precio mínimo)
- Ambos deben cumplirse (AND logic)

**Resultado:** `buy_signal = False` o `sell_signal = False`

**Línea crítica:**
```python
if not buy_allowed:
    buy_signal = False  # Línea 1157
    if current_state == "BUY":
        current_state = "WAIT"
```

### 2. Bloqueo por Flags de Configuración

**Ubicación:** Líneas 1272-1303 (BUY), 2250-2296 (SELL)

**Condiciones que bloquean:**
- `alert_enabled = False` → BLOQUEA TODAS LAS ALERTAS
- `buy_alert_enabled = False` → BLOQUEA ALERTAS BUY
- `sell_alert_enabled = False` → BLOQUEA ALERTAS SELL

**Resultado:** No se procesa la alerta (continúa sin enviar)

### 3. Bloqueo por `should_send_alert` (Segunda Capa)

**Ubicación:** Líneas 1471-1503 (BUY), 2207-2235 (SELL)

**Condiciones que bloquean:**
- Lock activo (otro thread procesando la alerta)
- No se cumple cooldown (`ALERT_COOLDOWN_MINUTES`)
- No se cumple cambio de precio mínimo (`ALERT_MIN_PRICE_CHANGE_PCT`)
- **AMBOS deben cumplirse (AND logic)** - Línea 439-442

**Lógica crítica (Línea 439-442):**
```python
# CRITICAL: Both conditions must be met (AND logic, not OR)
if not cooldown_met and cooldown_limit > 0:
    return False, f"Cooldown not met: {time_diff:.2f} min < {cooldown_limit} min"
if not price_change_met and alert_min_price_change > 0:
    return False, f"Price change not met: {price_change_pct:.2f}% < {alert_min_price_change}%"
```

**Resultado:** Retorna `(False, reason)` y se salta el envío

### 4. Bloqueo por Lock de Alertas

**Ubicación:** Líneas 1309-1331 (BUY), 2170-2192 (SELL)

**Condiciones que bloquean:**
- `alert_sending_locks[symbol_side]` existe y no ha expirado
- Tiempo de lock: `ALERT_SENDING_LOCK_SECONDS` (300 segundos = 5 minutos)

**Resultado:** `should_skip_alert = True`, no se procesa la alerta

## Estado Actual de BTC_USDT

Según diagnóstico:
- ✅ `alert_enabled: True`
- ✅ `buy_alert_enabled: True`
- ✅ `sell_alert_enabled: True`
- ✅ `min_price_change_pct: 1.0`
- ⚠️ `alert_cooldown_minutes: None` (usa default: `ALERT_COOLDOWN_MINUTES` = 0.1667 minutos = 10 segundos)
- 📊 Última señal SELL: 2025-12-13 11:04:40 (hace ~8.8 días)
- 💰 Precio actual: 89099.0
- 💰 Precio última SELL: 90585.04
- 📉 Cambio de precio: -1.64% (abs: 1.64%)

## Problemas Identificados

### Problema 1: Doble Sistema de Throttling

Hay **DOS sistemas de throttling independientes** que pueden causar bloqueos inconsistentes:

1. `should_emit_signal` → usa `signal_throttle_states` (BD)
2. `should_send_alert` → usa `self.last_alert_states` (memoria)

**Impacto:** Una señal puede pasar `should_emit_signal` pero ser bloqueada por `should_send_alert`, o viceversa.

### Problema 2: `alert_cooldown_minutes = None`

Cuando `alert_cooldown_minutes` es `None`, el sistema usa el default `ALERT_COOLDOWN_MINUTES = 0.1667` (10 segundos), pero:

- `should_emit_signal` puede usar un valor diferente si `min_interval_minutes` viene del throttle_config
- Esto puede causar inconsistencias

### Problema 3: `last_alert_states` en Memoria vs BD

`should_send_alert` usa `self.last_alert_states` que es un diccionario en memoria del servicio. Esto significa:

- Se pierde al reiniciar el servicio
- Puede estar desincronizado con `signal_throttle_states` en la BD
- Puede causar bloqueos incorrectos después de reinicios

## Flujo Completo de una Señal BUY

1. **Cálculo de señal** (línea 1009): `buy_signal = signals.get("buy_signal", False)`
2. **Primera verificación de throttle** (línea 1081): `should_emit_signal(...)`
   - Si False → `buy_signal = False` (línea 1157) → **FIN (no se procesa)**
3. **Verificación de flags** (línea 1303): `if buy_signal and alert_enabled and buy_alert_enabled:`
   - Si alguno False → **FIN (no se procesa)**
4. **Lock check** (línea 1309-1326): Verifica `alert_sending_locks`
   - Si lock activo → `should_skip_alert = True` → **FIN (no se procesa)**
5. **Segunda verificación de throttle** (línea 1471): `should_send_alert(...)`
   - Si False → **BLOQUEO (línea 1479)** → **FIN (no se envía)**
6. **Envío de alerta** (línea 1510+): Solo si todas las verificaciones pasaron

## Recomendaciones

1. **Unificar sistema de throttling:** Usar solo `signal_throttle_states` (BD) y eliminar `should_send_alert` o hacer que use la misma fuente
2. **Sincronizar `last_alert_states`:** Cargar desde BD al inicio y guardar después de cada alerta
3. **Clarificar `alert_cooldown_minutes = None`:** Siempre usar un valor explícito o documentar el comportamiento
4. **Mejorar logging:** Agregar logs detallados en cada punto de bloqueo para facilitar diagnóstico

