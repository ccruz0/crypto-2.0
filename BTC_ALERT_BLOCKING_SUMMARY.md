# Resumen: Por Qué BTC_USDT No Envía Alertas

## 🔍 PROBLEMA IDENTIFICADO: DOBLE SISTEMA DE THROTTLING

El sistema tiene **DOS CAPAS INDEPENDIENTES** de throttling que pueden bloquear alertas:

### Capa 1: `should_emit_signal` (signal_throttle.py)
- **Fuente de datos:** Tabla `signal_throttle_states` en base de datos
- **Cuándo se ejecuta:** ANTES de cualquier procesamiento de alertas
- **Ubicación en código:** Líneas 1081 (BUY), 1176 (SELL)
- **Si bloquea:** Establece `buy_signal = False` o `sell_signal = False` (líneas 1157, 1262)
- **Resultado:** La señal se descarta completamente

### Capa 2: `should_send_alert` (signal_monitor.py)
- **Fuente de datos:** `self.last_alert_states` (diccionario en memoria)
- **Cuándo se ejecuta:** DESPUÉS de pasar la Capa 1, justo antes de enviar
- **Ubicación en código:** Líneas 1471 (BUY), 2207 (SELL)
- **Si bloquea:** Retorna `(False, reason)` y se salta el envío (líneas 1479, 2208)
- **Resultado:** La alerta no se envía aunque la señal fue detectada

## 📊 CONDICIONES QUE BLOQUEAN ALERTAS

### 1. Throttling por Tiempo (Cooldown)
- **Capa 1:** Requiere `min_interval_minutes` desde última señal del mismo lado
- **Capa 2:** Requiere `ALERT_COOLDOWN_MINUTES` (default: 0.1667 min = 10 seg) desde última alerta
- **Lógica:** Si el tiempo transcurrido es MENOR que el cooldown, se bloquea

### 2. Throttling por Precio
- **Capa 1:** Requiere `min_price_change_pct` (configurado por símbolo) de cambio absoluto
- **Capa 2:** Requiere `ALERT_MIN_PRICE_CHANGE_PCT` (default: 1.0%) de cambio absoluto
- **Lógica:** Si el cambio de precio absoluto es MENOR que el mínimo, se bloquea

### 3. Lógica AND (Ambas Condiciones)
⚠️ **CRÍTICO:** Ambas condiciones (cooldown Y precio) deben cumplirse simultáneamente.

```python
# Código relevante (línea 439-455)
if not cooldown_met:
    return False, "Throttled: cooldown not met..."
if not price_change_met:
    return False, "Throttled: price change not met..."
```

### 4. Flags de Configuración
- `alert_enabled = False` → BLOQUEA TODAS LAS ALERTAS
- `buy_alert_enabled = False` → BLOQUEA ALERTAS BUY
- `sell_alert_enabled = False` → BLOQUEA ALERTAS SELL

### 5. Locks de Procesamiento
- `alert_sending_locks[symbol_side]` activo (< 5 minutos)
- Previene procesamiento simultáneo de la misma alerta

## 🎯 ESTADO ACTUAL DE BTC_USDT

Según diagnóstico ejecutado:

```
✅ alert_enabled: True
✅ buy_alert_enabled: True
✅ sell_alert_enabled: True
✅ min_price_change_pct: 1.0
⚠️ alert_cooldown_minutes: None (usa default)
💰 Precio actual: 89099.0
📊 Última señal SELL: 2025-12-13 11:04:40 (hace ~8.8 días)
💰 Precio última SELL: 90585.04
📉 Cambio de precio: -1.64% (abs: 1.64%)
```

**Análisis:**
- ✅ Cambio de precio: 1.64% > 1.0% mínimo → **CUMPLE**
- ✅ Tiempo desde última SELL: ~8.8 días > cualquier cooldown → **CUMPLE**
- ✅ Flags habilitados → **CUMPLE**

**⚠️ PROBLEMA IDENTIFICADO:** Aunque ambas condiciones se cumplen, puede haber un problema de sincronización entre las dos capas de throttling.

## 🔧 RAZONES POSIBLES DEL BLOQUEO

### Razón 1: Desincronización entre Capas
- **Capa 1** (`should_emit_signal`) usa `signal_throttle_states` (BD)
- **Capa 2** (`should_send_alert`) usa `self.last_alert_states` (memoria)
- Si `last_alert_states` en memoria está desactualizado, puede bloquear incorrectamente

### Razón 2: `last_alert_states` se pierde al reiniciar
- `self.last_alert_states` es un diccionario en memoria
- Se reinicia cuando el servicio se reinicia
- Puede causar bloqueos incorrectos si no se carga desde BD

### Razón 3: Default Values Inconsistentes
- `alert_cooldown_minutes = None` usa default `ALERT_COOLDOWN_MINUTES = 0.1667` (10 seg)
- Pero `should_emit_signal` puede usar `min_interval_minutes` de otro origen
- Puede causar inconsistencias entre capas

### Razón 4: Lock Activo
- Si hay un lock activo en `alert_sending_locks`, bloquea el procesamiento
- Lock dura 5 minutos (`ALERT_SENDING_LOCK_SECONDS = 300`)

## 🚨 FLUJO COMPLETO DE BLOQUEO

Para una señal BUY/SELL:

```
1. Señal detectada (buy_signal=True o sell_signal=True)
   ↓
2. CAPA 1: should_emit_signal()
   ├─ ❌ Bloquea → buy_signal=False → FIN (no se procesa)
   └─ ✅ Pasa → Continúa
   ↓
3. Verificación de flags (alert_enabled, buy_alert_enabled, sell_alert_enabled)
   ├─ ❌ Bloquea → FIN (no se procesa)
   └─ ✅ Pasa → Continúa
   ↓
4. Verificación de lock (alert_sending_locks)
   ├─ ❌ Lock activo → should_skip_alert=True → FIN (no se procesa)
   └─ ✅ Pasa → Continúa
   ↓
5. CAPA 2: should_send_alert()
   ├─ ❌ Bloquea → Retorna (False, reason) → FIN (no se envía)
   └─ ✅ Pasa → Continúa
   ↓
6. ✅ Alerta enviada
```

## 💡 SOLUCIÓN RECOMENDADA

### Solución Inmediata
1. **Verificar logs** para identificar qué capa está bloqueando
2. **Revisar `alert_sending_locks`** - puede estar activo
3. **Revisar `last_alert_states`** - puede estar desactualizado

### Solución a Largo Plazo
1. **Unificar throttling:** Eliminar `should_send_alert` o hacer que use `signal_throttle_states` (BD)
2. **Sincronizar `last_alert_states`:** Cargar desde BD al inicio y guardar después de cada alerta
3. **Mejorar logging:** Agregar logs detallados en cada punto de bloqueo

## 📝 PUNTOS DE BLOQUEO EN EL CÓDIGO

| Línea | Función | Condición | Resultado |
|-------|---------|-----------|-----------|
| 1081 | `should_emit_signal` (BUY) | Throttle check | `buy_signal = False` si bloquea |
| 1157 | Post-throttle (BUY) | `if not buy_allowed` | `buy_signal = False` |
| 1176 | `should_emit_signal` (SELL) | Throttle check | `sell_signal = False` si bloquea |
| 1262 | Post-throttle (SELL) | `if not sell_allowed` | `sell_signal = False` |
| 1303 | Flags check (BUY) | `if buy_signal and alert_enabled and buy_alert_enabled` | Skip si False |
| 1322 | Lock check (BUY) | `should_skip_alert = True` | Skip si lock activo |
| 1471 | `should_send_alert` (BUY) | Throttle check (Capa 2) | Skip si bloquea |
| 1479 | Post-alert-throttle (BUY) | `if not should_send` | Skip envío |
| 2170 | Lock check (SELL) | Lock activo | Skip si lock activo |
| 2207 | `should_send_alert` (SELL) | Throttle check (Capa 2) | Skip si bloquea |
| 2208 | Post-alert-throttle (SELL) | `if not should_send` | Skip envío |

## 🔍 PRÓXIMOS PASOS PARA DIAGNÓSTICO

1. Ejecutar script de diagnóstico mejorado para identificar capa que bloquea
2. Revisar logs del servicio para ver mensajes de bloqueo
3. Verificar estado de `alert_sending_locks` en tiempo real
4. Comparar `signal_throttle_states` (BD) vs `last_alert_states` (memoria)

