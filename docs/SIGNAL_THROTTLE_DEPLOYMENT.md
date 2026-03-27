# Signal Throttle Logging Fix - Deployment Summary

**Fecha:** 2025-12-09  
**Estado:** ✅ Desplegado exitosamente

---

## Cambios Desplegados

### 1. Mejoras en Logging

**Archivo:** `backend/app/services/signal_monitor.py`

#### Cambio 1: Nivel de log para throttle
- **Antes:** `logger.debug()` - No visible en logs con nivel INFO
- **Después:** `logger.info()` - Visible en logs
- **Línea:** ~1226
- **Impacto:** Ahora se verán mensajes cuando las alertas sean bloqueadas por throttle

#### Cambio 2: Logging adicional para record_signal_event
- **Agregado:** Logging antes y después de `record_signal_event()`
- **Líneas:** ~1294-1305
- **Impacto:** Permite rastrear si los eventos se están registrando correctamente en la base de datos

### 2. Mensajes de Log Nuevos

Ahora verás en los logs:

1. **Cuando una alerta es bloqueada por throttle:**
   ```
   ⏭️  BUY alert throttled for {symbol}: {reason}
   ```

2. **Antes de registrar evento:**
   ```
   📝 Recording signal event for {symbol} BUY at {price} (strategy: {strategy_key})
   ```

3. **Después de registrar evento exitosamente:**
   ```
   ✅ Signal event recorded successfully for {symbol} BUY
   ```

4. **Si falla el registro:**
   ```
   ❌ Failed to persist BUY throttle state for {symbol}: {error}
   ```

---

## Estado del Despliegue

✅ **Archivo sincronizado:** `signal_monitor.py` copiado a AWS  
✅ **Contenedor actualizado:** Archivo copiado al contenedor Docker  
✅ **Contenedor reiniciado:** `automated-trading-platform-backend-aws-1` reiniciado  
✅ **Servicio funcionando:** Backend y signal monitor activos

---

## Cómo Monitorear

### 1. Ver Logs en Tiempo Real

```bash
# Ver todos los logs del backend
bash scripts/aws_backend_logs.sh -f

# Filtrar solo mensajes relacionados con throttle
bash scripts/aws_backend_logs.sh -f | grep -E "(throttled|Recording signal|Signal event recorded)"

# Ver señales detectadas y decisiones
bash scripts/aws_backend_logs.sh -f | grep -E "(BUY signal detected|alert decision|processing alert)"
```

### 2. Verificar Eventos en Dashboard

1. Ir a `dashboard.hilovivo.com`
2. Navegar a la sección "Signal Throttle"
3. Verificar que aparezcan eventos nuevos (no solo los de hace días)
4. Los eventos deberían aparecer cuando:
   - Se detecta una señal BUY/SELL
   - La señal pasa el throttle
   - Se envía la alerta exitosamente
   - Se registra el evento con `record_signal_event()`

### 3. Verificar Logs Recientes

```bash
# Ver últimos 1000 logs y filtrar por throttle
bash scripts/aws_backend_logs.sh --tail 1000 | grep -E "(throttled|Recording|Signal event)" | tail -30

# Ver si hay errores al registrar eventos
bash scripts/aws_backend_logs.sh --tail 2000 | grep -E "(Failed to persist|throttle state)" | tail -20
```

---

## Diagnóstico Esperado

### Escenario 1: Alertas siendo bloqueadas por throttle

Si ves muchos mensajes de:
```
⏭️  BUY alert throttled for {symbol}: THROTTLED_MIN_TIME (elapsed X.XXm < 5.00m)
⏭️  BUY alert throttled for {symbol}: THROTTLED_MIN_CHANGE (price change X.XX% < 1.00%)
```

**Significado:** Las señales están siendo detectadas pero bloqueadas por:
- **Cooldown:** No ha pasado suficiente tiempo desde la última alerta (5 minutos)
- **Cambio de precio:** El precio no ha cambiado lo suficiente (1.0%)

**Solución:** Esto es normal. Las alertas se enviarán cuando se cumplan las condiciones.

### Escenario 2: Alertas siendo enviadas pero no registradas

Si ves:
```
✅ BUY alert SENT for {symbol}...
📝 Recording signal event for {symbol} BUY...
```

Pero NO ves:
```
✅ Signal event recorded successfully...
```

**Significado:** Hay un error al registrar el evento en la base de datos.

**Solución:** Revisar el error específico en los logs.

### Escenario 3: Todo funcionando correctamente

Si ves:
```
🟢 NEW BUY signal detected for {symbol} - processing alert
✅ BUY alert SENT for {symbol}...
📝 Recording signal event for {symbol} BUY at {price}...
✅ Signal event recorded successfully for {symbol} BUY
```

**Significado:** El flujo completo está funcionando correctamente.

**Resultado:** Los eventos deberían aparecer en el dashboard en la sección "Signal Throttle".

---

## Próximos Pasos

1. **Monitorear logs durante las próximas horas:**
   - Ver si aparecen los nuevos mensajes de logging
   - Identificar si las alertas están siendo bloqueadas o enviadas

2. **Verificar dashboard:**
   - Esperar 1-2 ciclos del signal monitor (30-60 segundos)
   - Verificar si aparecen eventos nuevos en "Signal Throttle"

3. **Si no aparecen eventos:**
   - Revisar logs para ver si hay errores
   - Verificar que `buy_alert_enabled=True` en los watchlist items
   - Verificar que las señales están pasando el throttle

---

## Comandos Útiles

```bash
# Ver estado del contenedor
ssh hilovivo-aws "cd ~/crypto-2.0 && docker ps | grep backend"

# Ver logs del signal monitor específicamente
bash scripts/aws_backend_logs.sh -f | grep signal_monitor

# Ver últimas 50 líneas de logs
bash scripts/aws_backend_logs.sh --tail 50

# Reiniciar contenedor si es necesario
ssh hilovivo-aws "cd ~/crypto-2.0 && docker restart automated-trading-platform-backend-aws-1"
```

---

## Archivos Modificados

- `backend/app/services/signal_monitor.py` - Mejoras en logging
- `deploy_signal_throttle_logging_fix.sh` - Script de despliegue creado

## Documentación Relacionada

- `docs/SIGNAL_THROTTLE_DIAGNOSIS.md` - Diagnóstico inicial
- `docs/SIGNAL_THROTTLE_LOG_ANALYSIS.md` - Análisis de logs
- `scripts/diagnose_signal_throttle.py` - Script de diagnóstico

---

**Última Actualización:** 2025-12-09 17:50 WITA
