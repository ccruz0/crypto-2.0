# Solución a Largo Plazo: Unificación del Sistema de Throttling

## Resumen

Se ha aplicado la solución a largo plazo para eliminar el doble sistema de throttling que causaba bloqueos inconsistentes de alertas.

## Cambios Aplicados

### 1. Eliminación de la Segunda Capa de Throttling

**Antes:**
- **Capa 1:** `should_emit_signal()` → usa `signal_throttle_states` (BD)
- **Capa 2:** `should_send_alert()` → usa `self.last_alert_states` (memoria)

**Después:**
- **Única Capa:** `should_emit_signal()` → usa solo `signal_throttle_states` (BD)

### 2. Modificaciones en `signal_monitor.py`

#### Eliminadas las llamadas a `should_send_alert()`
- **BUY alerts (líneas ~1465-1479):** Removida verificación duplicada
- **SELL alerts (líneas ~2198-2208):** Removida verificación duplicada
- Ahora se procede directamente al envío después de que `should_emit_signal()` pasa

#### Simplificado `_get_last_alert_price()`
- **Antes:** Verificaba primero `self.last_alert_states` (memoria), luego BD
- **Después:** Usa solo BD (`signal_throttle_states`)
- Eliminada lógica de sincronización memoria↔BD

#### Deprecado `_update_alert_state()`
- **Función:** Ahora es no-op (no hace nada)
- **Razón:** El estado se actualiza directamente en BD vía `record_signal_event()`

#### Deprecado `should_send_alert()`
- **Función:** Retorna `(True, "DEPRECATED")` con warning log
- **Razón:** Mantener compatibilidad si hay código legacy que lo llame

### 3. Estado de `last_alert_states`

- **Nota agregada:** Documentado que está deprecated
- **Mantenido:** Por compatibilidad, pero no se usa para decisiones de throttling
- **Futuro:** Puede eliminarse completamente en una refactorización futura

## Beneficios

### ✅ Consistencia
- Una sola fuente de verdad (`signal_throttle_states` en BD)
- Eliminada desincronización entre capas
- Comportamiento predecible y reproducible

### ✅ Persistencia
- El estado de throttling persiste después de reinicios
- No se pierde información al reiniciar el servicio

### ✅ Simplicidad
- Código más simple y fácil de mantener
- Menos puntos de fallo
- Lógica de throttling centralizada

### ✅ Debugging
- Más fácil diagnosticar problemas
- Estado visible directamente en BD
- Logs más claros

## Flujo Actualizado

### Para una Señal BUY/SELL:

```
1. Señal detectada (buy_signal=True o sell_signal=True)
   ↓
2. ÚNICA VERIFICACIÓN: should_emit_signal()
   ├─ ❌ Bloquea → buy_signal=False / sell_signal=False → FIN (no se procesa)
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
5. ✅ Alerta enviada + record_signal_event() actualiza BD
```

## Archivos Modificados

- `backend/app/services/signal_monitor.py`
  - Eliminadas llamadas a `should_send_alert()` en BUY y SELL
  - Simplificado `_get_last_alert_price()`
  - Deprecado `_update_alert_state()`
  - Deprecado `should_send_alert()`
  - Corregida indentación y estructura

## Testing Recomendado

1. **Verificar alertas BUY:** Confirmar que se envían cuando las condiciones se cumplen
2. **Verificar alertas SELL:** Confirmar que se envían cuando las condiciones se cumplen
3. **Verificar throttling:** Confirmar que respeta cooldown y cambio de precio mínimo
4. **Verificar persistencia:** Reiniciar servicio y verificar que el throttling persiste

## Notas de Implementación

- Las funciones deprecadas (`should_send_alert`, `_update_alert_state`) se mantienen por compatibilidad
- Pueden eliminarse en una refactorización futura si no hay código que las use
- `last_alert_states` también puede eliminarse en el futuro si no se usa en otros lugares

