# Signal Throttle - Resumen de Fixes

**Fecha:** 2025-12-09  
**Estado:** ✅ Fixes desplegados

---

## Problema Identificado

El signal throttle no estaba registrando eventos en el dashboard porque:

1. **Error en `telegram_notifier.py` línea 279:**
   - `UnboundLocalError: cannot access local variable 'symbol'`
   - Ocurría cuando se intentaba usar `symbol` antes de que estuviera definido en el scope
   - Esto causaba que `send_buy_signal()` lanzara una excepción
   - La excepción impedía que se ejecutara `record_signal_event()` en `signal_monitor.py`

2. **Logging insuficiente:**
   - Los mensajes de throttle eran `logger.debug()` (no visibles)
   - No había logging antes/después de `record_signal_event()`

---

## Fixes Aplicados

### 1. Fix en `telegram_notifier.py`

**Problema:** Uso de `symbol` antes de verificar si está definido

**Solución:** Verificar si `symbol` está disponible antes de usarlo, y extraerlo del mensaje si no está disponible:

```python
# Antes (línea 279):
f"[LIVE_ALERT_GATEKEEPER] symbol={symbol or 'UNKNOWN'} side={side} ..."

# Después:
log_symbol = symbol if 'symbol' in locals() else (None)
if log_symbol is None:
    # Extraer symbol del mensaje si no está disponible
    ...
f"[LIVE_ALERT_GATEKEEPER] symbol={log_symbol or 'UNKNOWN'} side={side} ..."
```

### 2. Mejoras en Logging (`signal_monitor.py`)

**Cambio 1:** Nivel de log para throttle
- **Antes:** `logger.debug()` - No visible
- **Después:** `logger.info()` - Visible en logs

**Cambio 2:** Logging adicional para `record_signal_event()`
- Agregado: `📝 Recording signal event for {symbol} BUY at {price}`
- Agregado: `✅ Signal event recorded successfully for {symbol} BUY`
- Mejorado: Error logging con `exc_info=True`

**Cambio 3:** Mejor manejo de errores
- Agregado: Liberación del lock si falla el envío
- Agregado: Traceback completo en errores

---

## Archivos Modificados

1. `backend/app/services/telegram_notifier.py`
   - Fix: Manejo seguro de variable `symbol` en línea 279

2. `backend/app/services/signal_monitor.py`
   - Mejora: Logging de throttle de `debug` a `info` (línea ~1226)
   - Mejora: Logging antes/después de `record_signal_event()` (líneas ~1295-1307)
   - Mejora: Mejor manejo de errores con traceback (línea ~1309)

---

## Resultado Esperado

Después de estos fixes:

1. ✅ **Las alertas se enviarán sin errores:**
   - No más `UnboundLocalError` en `telegram_notifier.py`
   - `send_buy_signal()` completará exitosamente

2. ✅ **Los eventos se registrarán:**
   - `record_signal_event()` se ejecutará después de envío exitoso
   - Los eventos aparecerán en la tabla `signal_throttle_state`
   - El dashboard mostrará eventos nuevos en "Signal Throttle"

3. ✅ **Mejor visibilidad:**
   - Los mensajes de throttle serán visibles en logs
   - Se podrá rastrear el flujo completo de registro de eventos

---

## Verificación

### 1. Monitorear Logs

```bash
# Ver si hay errores de symbol
bash scripts/aws_backend_logs.sh -f | grep -E "(UnboundLocalError|cannot access local variable)"

# Ver mensajes de throttle
bash scripts/aws_backend_logs.sh -f | grep -E "(throttled|Recording signal|Signal event recorded)"

# Ver alertas enviadas
bash scripts/aws_backend_logs.sh -f | grep -E "(BUY alert SENT|send_buy_signal called)"
```

### 2. Verificar Dashboard

1. Ir a `dashboard.hilovivo.com`
2. Navegar a "Signal Throttle"
3. Verificar que aparezcan eventos nuevos (últimas horas, no días)

### 3. Verificar Base de Datos

```sql
SELECT symbol, side, last_time, last_price 
FROM signal_throttle_state 
ORDER BY last_time DESC 
LIMIT 20;
```

---

## Próximos Pasos

1. **Monitorear durante las próximas horas:**
   - Verificar que no haya más errores de `symbol`
   - Confirmar que los eventos se están registrando
   - Verificar que el dashboard muestre eventos nuevos

2. **Si todo funciona:**
   - Los eventos deberían aparecer en el dashboard
   - El signal throttle estará funcionando correctamente

3. **Si hay problemas:**
   - Revisar logs para identificar nuevos errores
   - Verificar que `record_signal_event()` se esté ejecutando
   - Confirmar que la base de datos esté accesible

---

## Comandos Útiles

```bash
# Ver logs en tiempo real
bash scripts/aws_backend_logs.sh -f

# Ver solo errores
bash scripts/aws_backend_logs.sh --tail 5000 | grep -E "(ERROR|Exception|Traceback)"

# Ver eventos de throttle
bash scripts/aws_backend_logs.sh --tail 5000 | grep -E "(Recording signal|Signal event recorded|throttled)"

# Reiniciar contenedor si es necesario
ssh hilovivo-aws "cd ~/crypto-2.0 && docker restart automated-trading-platform-backend-aws-1"
```

---

**Última Actualización:** 2025-12-09 10:15 WITA
